"""设备注册与在线判定（PRD 5.5 在线三态 / 6.1 devices 表）。

在线判定口径（唯一实现，别处不许自己算）：
    now - last_seen ≤ 45s      → online   （绿）
    45s < 间隔 ≤ 120s          → suspect  （黄）
    > 120s                     → offline  （灰 + 报警）
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.redis_client import Keys, get_last_seen, get_redis, touch_last_seen
from ..core.ws_manager import manager
from ..models.alerts import Alert
from ..models.devices import Device

ONLINE_WINDOW_S = 45
SUSPECT_WINDOW_S = 120

STATE_ONLINE = "online"
STATE_SUSPECT = "suspect"
STATE_OFFLINE = "offline"


# ------------------------------------------------------------------ 角色推断
def _guess_role(device_id: str) -> str:
    """未知设备自动登记时的角色推断（硬件同事烧完板直接上报即可）。"""
    lower = device_id.lower()
    if "soil" in lower:
        return "soil"
    if "act" in lower:
        return "actuator"
    return "field"


def ensure_device(
    db: Session,
    device_id: str,
    *,
    role: str | None = None,
    name: str | None = None,
    location: str | None = None,
    is_mock: bool = False,
    config: dict[str, Any] | None = None,
) -> Device:
    """按 device_id 取设备，没有就登记（幂等）。"""
    device = db.scalar(select(Device).where(Device.device_id == device_id))
    if device is not None:
        return device
    device = Device(
        device_id=device_id,
        name=name or device_id,
        role=role or _guess_role(device_id),
        location=location,
        is_mock=is_mock,
        # 不写 online=True：device_id 打错一个字，下发一次指令就会凭空登记一台"在线"设备，
        # 120s 后再由 sweep 补一条假的离线报警，大屏上谁也说不清这台是哪来的。
        # 新设备一律先当离线，等它自己发心跳（touch）再转在线。
        online=False,
        last_seen=None,
        config_json=config,
    )
    db.add(device)
    db.flush()
    logger.info("登记新设备：{}（role={}, mock={}）", device_id, device.role, is_mock)
    return device


# ------------------------------------------------------------------ 心跳
def touch(
    db: Session,
    device_id: str,
    *,
    ts: float | None = None,
    rssi: int | None = None,
    online: bool = True,
    is_mock: bool | None = None,
) -> Device:
    """收到 status 心跳：写 Redis last_seen + 回写 devices 表。"""
    now = ts or time.time()
    touch_last_seen(device_id, now)

    device = db.scalar(select(Device).where(Device.device_id == device_id))
    if device is None:
        device = ensure_device(db, device_id, is_mock=bool(is_mock))
    if is_mock is not None:
        device.is_mock = is_mock
    device.online = online
    device.last_seen = datetime.fromtimestamp(now)
    if rssi is not None and isinstance(device.config_json, dict):
        device.config_json = {**device.config_json, "rssi": rssi}
    return device


def online_state(device_id: str) -> str:
    last = get_last_seen(device_id)
    if last is None:
        return STATE_OFFLINE
    gap = time.time() - last
    if gap <= ONLINE_WINDOW_S:
        return STATE_ONLINE
    if gap <= SUSPECT_WINDOW_S:
        return STATE_SUSPECT
    return STATE_OFFLINE


def state_dict(device: Device) -> dict[str, Any]:
    return {
        "device_id": device.device_id,
        "name": device.name,
        "role": device.role,
        "location": device.location,
        "is_mock": device.is_mock,
        "online": device.online,
        "last_seen": device.last_seen.isoformat(sep=" ", timespec="seconds") if device.last_seen else None,
        "state": online_state(device.device_id),
    }


def list_states(db: Session, is_mock: bool | None = None, include_all: bool = False) -> list[dict[str, Any]]:
    """设备列表。

    is_mock=None（缺省）：只返回**当前运行模式**那一组——
    Mock 演示时大屏不该挂 3 台永远灰着的真设备，Real 模式也不该看到假设备。
    is_mock=True/False：显式只要 Mock / 只要真机（设置页、联调排查用）。
    include_all=True：不过滤，给「设备管理」这种需要看到全量的页面。
    """
    stmt = select(Device).order_by(Device.id)
    if not include_all:
        if is_mock is None:
            from ..core.runtime_settings import get_mode

            stmt = stmt.where(Device.is_mock.is_(get_mode() == "mock"))
        else:
            stmt = stmt.where(Device.is_mock.is_(is_mock))
    return [state_dict(d) for d in db.scalars(stmt).all()]


def deactivate_mock_devices(db: Session) -> int:
    """切到 Real 模式时停用 mock-* 设备：置离线 + 清 last_seen 与报警标记。

    不做这一步，模拟器一停，这 3 台假设备会在 120s 后连发 3 条"设备离线"报警，
    现场演示切到真机时大屏突然冒出 3 条假警报。
    """
    affected = 0
    for device in db.scalars(select(Device).where(Device.is_mock.is_(True))).all():
        device.online = False
        device.last_seen = None
        try:
            get_redis().delete(Keys.device_last_seen(device.device_id))
            get_redis().delete(Keys.device_alerted(device.device_id))
        except Exception:  # pragma: no cover
            pass
        affected += 1
    if affected:
        db.flush()
        logger.info("已停用 {} 台 Mock 设备（切 Real 模式，不再参与在线巡检）", affected)
    return affected


# ------------------------------------------------------------------ 离线巡检
def sweep_offline(db: Session) -> list[dict[str, Any]]:
    """离线巡检（由后台循环每 15s 调一次）：>120s 判定离线，写 alerts + WS 广播。

    返回本轮新产生的报警，方便调用方打日志。Redis 标记去重，避免每轮刷屏。
    """
    events: list[dict[str, Any]] = []
    now = time.time()
    for device in db.scalars(select(Device)).all():
        last = get_last_seen(device.device_id) or (
            device.last_seen.timestamp() if device.last_seen else None
        )
        if last is None:
            # 从未上报过：不算「离线报警」，只是还没接入（真设备没上电时不该刷屏）
            if device.online:
                device.online = False
            continue
        gap = now - last
        if gap > SUSPECT_WINDOW_S:
            if device.online:
                device.online = False
            flag_key = Keys.device_alerted(device.device_id)
            try:
                first_time = bool(get_redis().set(flag_key, 1, nx=True, ex=3600))
            except Exception:  # pragma: no cover
                first_time = False
            if first_time:
                alert = Alert(
                    level="warning",
                    source=f"device:{device.device_id}",
                    message=f"设备 {device.name}（{device.device_id}）离线超过 {int(gap)}s",
                )
                db.add(alert)
                db.flush()
                event = {
                    "type": "alert",
                    "alert_id": alert.id,
                    "level": alert.level,
                    "source": alert.source,
                    "message": alert.message,
                }
                events.append(event)
                manager.publish_threadsafe("alert", {k: v for k, v in event.items() if k != "type"})
                manager.publish_threadsafe("device_status", state_dict(device))
                logger.warning("设备离线报警：{}（{}s 无心跳）", device.device_id, int(gap))
        else:
            if not device.online:
                device.online = True
                manager.publish_threadsafe("device_status", state_dict(device))
                logger.info("设备恢复在线：{}", device.device_id)
            try:
                get_redis().delete(Keys.device_alerted(device.device_id))
            except Exception:  # pragma: no cover
                pass
    return events
