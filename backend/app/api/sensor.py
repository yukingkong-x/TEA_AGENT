"""传感器数据（PRD 7.4）：大屏首屏用 latest，曲线用 history。

Mock 模式下也读 sensor_data 表 —— 模拟器发的报文走同一条链路入库，
所以「Mock 与 Real 只差数据来源」这件事在接口层是透明的（PRD 12.1）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.devices import Device
from ..models.sensor_data import SensorData

router = APIRouter(prefix="/sensor", tags=["sensor"])


def _parse_dt(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return default


@router.get("/latest", summary="全部设备最新读数（大屏）")
def latest(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    devices = db.scalars(select(Device).order_by(Device.id)).all()
    out: list[dict[str, Any]] = []
    for device in devices:
        pairs = db.execute(
            select(SensorData.metric, func.max(SensorData.ts)).where(
                SensorData.device_id == device.device_id
            ).group_by(SensorData.metric)
        ).all()
        metrics: dict[str, Any] = {}
        latest_ts: datetime | None = None
        for metric, ts in pairs:
            row = db.scalar(
                select(SensorData)
                .where(
                    SensorData.device_id == device.device_id,
                    SensorData.metric == metric,
                    SensorData.ts == ts,
                )
                .order_by(SensorData.id.desc())
                .limit(1)
            )
            if row is None:
                continue
            metrics[metric] = float(row.value) if isinstance(row.value, Decimal) else row.value
            if latest_ts is None or (ts and ts > latest_ts):
                latest_ts = ts
        out.append(
            {
                "device_id": device.device_id,
                "name": device.name,
                "role": device.role,
                "is_mock": device.is_mock,
                "online": device.online,
                "metrics": metrics,
                "ts": latest_ts.isoformat(timespec="seconds") if latest_ts else None,
            }
        )
    return out


@router.get("/history", summary="历史曲线")
def history(
    device_id: str = Query(..., description="设备 id"),
    metric: str = Query("soil_moisture", description="temperature_c / humidity_air / lux / soil_moisture"),
    start: str | None = Query(None, alias="from"),
    end: str | None = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now()
    since = _parse_dt(start, now - timedelta(hours=6))
    until = _parse_dt(end, now)
    # limit 必须取「最新的 N 个点」：先按 ts 倒序取 limit 条，再反转回升序。
    # （此前升序 + limit 返回的是窗口里最老的 N 个点，遥测明明在流、接口却一直给旧数据）
    rows = db.scalars(
        select(SensorData)
        .where(
            SensorData.device_id == device_id,
            SensorData.metric == metric,
            SensorData.ts >= since,
            SensorData.ts <= until,
        )
        .order_by(SensorData.ts.desc())
        .limit(limit)
    ).all()
    rows = list(reversed(rows))
    points = [
        {
            "ts": r.ts.isoformat(timespec="seconds"),
            "value": float(r.value) if isinstance(r.value, Decimal) else r.value,
        }
        for r in rows
    ]
    return {
        "device_id": device_id,
        "metric": metric,
        "from": since.isoformat(timespec="seconds"),
        "to": until.isoformat(timespec="seconds"),
        "count": len(points),
        "points": points,
    }


@router.get("/day", summary="近 N 小时全指标摘要（10 分钟桶，日高日低/DLI/变压用）")
def day_summary(
    device_id: str = Query(..., description="设备 id"),
    hours: int = Query(24, ge=1, le=168, description="回看窗口（小时）"),
    bucket_minutes: int = Query(10, ge=1, le=60, description="聚合桶宽（分钟）"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """一条请求带回该设备全部指标的降采样序列与窗口极值。

    前端的三类衍生指标都靠它算，不再各拉一遍 history：
    · 气温日高/日低 → metrics[temperature_c].min/max
    · 3h 变压 → pressure 序列里隔 3h 的两点相减
    · DLI 日累计 → lux 序列梯形积分（前端做，1 lx ≈ 0.0182 μmol/m²/s）
    """
    now = datetime.now()
    since = now - timedelta(hours=hours)
    rows = db.execute(
        select(SensorData.metric, SensorData.ts, SensorData.value).where(
            SensorData.device_id == device_id,
            SensorData.ts >= since,
            SensorData.ts <= now,
        )
    ).all()

    buckets: dict[str, dict[datetime, tuple[float, int]]] = {}
    stats: dict[str, dict[str, float]] = {}
    step = timedelta(minutes=bucket_minutes)
    for metric, ts, value in rows:
        # 哨兵值过滤：设备读数失败时固件/入库链路会落 -999，
        # 混进序列会把 min/max 和曲线打成「-999℃」，宁可少一个点也不画假谷底
        num = float(value) if isinstance(value, Decimal) else float(value)
        if num <= -900:
            continue
        # 归到桶起点：分钟对齐到 bucket_minutes 的整数倍，秒清零
        start = ts.replace(second=0, microsecond=0, minute=(ts.minute // bucket_minutes) * bucket_minutes)
        bucket = buckets.setdefault(metric, {})
        total, count = bucket.get(start, (0.0, 0))
        bucket[start] = (total + num, count + 1)
        stat = stats.setdefault(metric, {"min": num, "max": num})
        stat["min"] = min(stat["min"], num)
        stat["max"] = max(stat["max"], num)

    metrics: dict[str, Any] = {}
    for metric, bucket in buckets.items():
        points = [
            {"ts": start.isoformat(timespec="seconds"), "value": round(total / count, 2)}
            for start, (total, count) in sorted(bucket.items())
        ]
        metrics[metric] = {
            "points": points,
            "min": stats[metric]["min"],
            "max": stats[metric]["max"],
            "count": len(points),
        }
    return {
        "device_id": device_id,
        "from": since.isoformat(timespec="seconds"),
        "to": now.isoformat(timespec="seconds"),
        "bucket_minutes": bucket_minutes,
        "metrics": metrics,
    }
