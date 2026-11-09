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
                "ts": latest_ts.isoformat(sep=" ", timespec="seconds") if latest_ts else None,
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
    rows = db.scalars(
        select(SensorData)
        .where(
            SensorData.device_id == device_id,
            SensorData.metric == metric,
            SensorData.ts >= since,
            SensorData.ts <= until,
        )
        .order_by(SensorData.ts.asc())
        .limit(limit)
    ).all()
    points = [
        {
            "ts": r.ts.isoformat(sep=" ", timespec="seconds"),
            "value": float(r.value) if isinstance(r.value, Decimal) else r.value,
        }
        for r in rows
    ]
    return {
        "device_id": device_id,
        "metric": metric,
        "from": since.isoformat(sep=" ", timespec="seconds"),
        "to": until.isoformat(sep=" ", timespec="seconds"),
        "count": len(points),
        "points": points,
    }
