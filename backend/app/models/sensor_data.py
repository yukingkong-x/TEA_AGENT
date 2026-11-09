"""sensor_data 遥测表（PRD 6.2，量最大）。

PRD 写「分区按月或按 id 范围」——本次实现**不分区**：赛期数据量（3 设备 × 每 30s ≈ 3 万行/天）
远达不到需要分区的规模，而 create_all 无法建分区表。索引按 PRD 建 (device_id, metric, ts)。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Index, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class SensorData(IdMixin, TimestampMixin, Base):
    __tablename__ = "sensor_data"

    device_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="设备 id")
    metric: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="temperature_c / humidity_air / lux / soil_moisture"
    )
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="数值")
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, comment="原始报文")
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="设备时间戳")

    __table_args__ = (
        Index("ix_sensor_device_metric_ts", "device_id", "metric", "ts"),
        Index("ix_sensor_ts", "ts"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SensorData {self.device_id} {self.metric}={self.value}@{self.ts}>"
