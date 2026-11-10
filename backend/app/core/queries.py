"""统一查询口径 —— 数据层只算一遍，谁用谁调。

为什么要有这层：Mock 和 Real 两种模式的数据最终都落同一张 `sensor_data` 表。
「土壤湿度多少、趋势往哪走、算不算干」这种**判断口径**只在这里算一次，
队长的工具池（get_soil_status / get_env_status / raise_alert）、API、演示脚本
都调这里 —— 否则两处各查各的，Mock/Real 一切换就会得出两个不同结论，
Agent 决策和演示解说会对不上。

约定（给队长）：
    from app.core.queries import soil_status, env_status, raise_alert, device_overview
    with session_scope() as db:
        info = soil_status(db)          # 不传 device_id = 自动找 role='soil' 的设备
        env  = env_status(db)           # role='field'
        raise_alert(db, "warning", "agent:scout", "A 区土壤低于下限")

纯逻辑函数（trend_per_min / classify_soil）不碰数据库，单测直接覆盖。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.alerts import ALERT_LEVELS, Alert
from ..models.devices import Device
from ..models.sensor_data import SensorData
from ..devices import registry
from .runtime_settings import get_value
from .ws_manager import manager

# 指标名全集（与 PRD 5.2 报文、mock/simulator.py、真固件对齐）
METRIC_SOIL = "soil_moisture"
METRIC_TEMP = "temperature_c"
METRIC_HUMID = "humidity_air"
METRIC_LUX = "lux"
METRIC_CO2 = "co2"

ENV_METRICS = (METRIC_TEMP, METRIC_HUMID, METRIC_LUX, METRIC_CO2)


# ------------------------------------------------------------------ 基础查询
def _row_dict(row: SensorData) -> dict[str, Any]:
    return {"value": float(row.value), "ts": row.ts.isoformat(sep=" ", timespec="seconds")}


def recent(
    db: Session,
    device_id: str,
    metric: str,
    *,
    n: int = 3,
    minutes: int = 30,
) -> list[dict[str, Any]]:
    """某设备某指标最近 n 个点（时间升序）。没有数据返回 []。"""
    since = datetime.now() - timedelta(minutes=minutes)
    rows = db.scalars(
        select(SensorData)
        .where(SensorData.device_id == device_id, SensorData.metric == metric, SensorData.ts >= since)
        .order_by(SensorData.ts.desc())
        .limit(n)
    ).all()
    return [_row_dict(r) for r in reversed(rows)]


def latest(db: Session, device_id: str, metric: str) -> dict[str, Any] | None:
    """最新一个点；没有数据返回 None（不要编造 0，调用方自己决定缺省语义）。"""
    row = db.scalar(
        select(SensorData)
        .where(SensorData.device_id == device_id, SensorData.metric == metric)
        .order_by(SensorData.ts.desc())
        .limit(1)
    )
    return _row_dict(row) if row else None


def _resolve_device(db: Session, device_id: str | None, role: str) -> Device:
    """给了 id 就精确找；没给就按角色取第一台（单地块演示场景足够）。"""
    if device_id:
        device = db.scalar(select(Device).where(Device.device_id == device_id))
        if device is None:
            raise ValueError(f"设备 {device_id} 不存在（先在设备列表里确认 id）")
        return device
    device = db.scalar(select(Device).where(Device.role == role).order_by(Device.id))
    if device is None:
        raise ValueError(f"没有 role={role} 的设备（检查种子数据或 Real 模式自动登记）")
    return device


# ------------------------------------------------------------------ 纯逻辑（单测覆盖）
def trend_per_min(points: Sequence[dict[str, Any]]) -> float:
    """每分钟变化率（%/min）。点数 <2 或时间跨度 <5s 时返回 0.0（不能除零、也别拿抖动当趋势）。"""
    if len(points) < 2:
        return 0.0
    try:
        t0 = datetime.fromisoformat(points[0]["ts"])
        t1 = datetime.fromisoformat(points[-1]["ts"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    dt_min = (t1 - t0).total_seconds() / 60.0
    if dt_min < 5.0 / 60.0:
        return 0.0
    try:
        dv = float(points[-1]["value"]) - float(points[0]["value"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    return round(dv / dt_min, 3)


def classify_soil(value: float, lo: float, hi: float) -> str:
    """三态口径：低于下限 dry / 区间内 ok / 高于上限 wet。"""
    if value < lo:
        return "dry"
    if value > hi:
        return "wet"
    return "ok"


# ------------------------------------------------------------------ 面向工具池的组合查询
def soil_status(db: Session, device_id: str | None = None) -> dict[str, Any]:
    """get_soil_status 的数据源：最新湿度 + 趋势 + 三态 + 阈值 + 最近 3 点。"""
    device = _resolve_device(db, device_id, role="soil")
    raw_range = get_value("irrigation_default_range", [55, 65]) or [55, 65]
    lo, hi = float(raw_range[0]), float(raw_range[1])

    points = recent(db, device.device_id, METRIC_SOIL, n=3, minutes=30)
    if points:
        moisture = points[-1]["value"]
        state = classify_soil(moisture, lo, hi)
    else:
        moisture = None
        state = "unknown"  # 还没数据 ≠ 干旱，不能触发误浇水
    return {
        "device_id": device.device_id,
        "name": device.name,
        "location": device.location,
        "moisture": moisture,
        "state": state,
        "target_range": [lo, hi],
        "trend_per_min": trend_per_min(points),
        "points": points,
        "online": registry.online_state(device.device_id),
    }


def env_status(db: Session, device_id: str | None = None) -> dict[str, Any]:
    """get_env_status 的数据源：巡园员最新环境读数（温度/湿度/光照/co2 有则给）。"""
    device = _resolve_device(db, device_id, role="field")
    readings: dict[str, dict[str, Any]] = {}
    for metric in ENV_METRICS:
        row = latest(db, device.device_id, metric)
        if row is not None:
            readings[metric] = row
    return {
        "device_id": device.device_id,
        "name": device.name,
        "location": device.location,
        "readings": readings,
        "online": registry.online_state(device.device_id),
    }


def device_overview(db: Session) -> list[dict[str, Any]]:
    """大屏/工具共用的设备总览：在线三态 + 土壤节点附最新湿度。"""
    out = registry.list_states(db)
    soil_ids = {d["device_id"] for d in out if d["role"] == "soil"}
    for item in out:
        item["soil_moisture"] = None
        if item["device_id"] in soil_ids:
            row = latest(db, item["device_id"], METRIC_SOIL)
            item["soil_moisture"] = row["value"] if row else None
    return out


# ------------------------------------------------------------------ 报警
def raise_alert(db: Session, level: str, source: str, message: str) -> dict[str, Any]:
    """raise_alert 的数据源：写库 + 推 WS（大屏红点）。level 白名单，写错直接 ValueError。"""
    if level not in ALERT_LEVELS:
        raise ValueError(f"level 必须是 {ALERT_LEVELS}，收到 {level!r}")
    alert = Alert(level=level, source=source, message=message[:255])
    db.add(alert)
    db.flush()
    payload = {"id": alert.id, "level": level, "source": source, "message": alert.message}
    manager.publish_threadsafe("alert", payload)
    return payload
