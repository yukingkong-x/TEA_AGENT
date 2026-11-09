"""devices 设备表（PRD 6.1）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

DEVICE_ROLES = ("field", "soil", "actuator")


class Device(IdMixin, TimestampMixin, Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True, comment="如 k10-field-01"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="显示名：巡园员一号")
    role: Mapped[str] = mapped_column(
        Enum(*DEVICE_ROLES, name="device_role"), nullable=False, comment="角色"
    )
    location: Mapped[str | None] = mapped_column(String(64), comment="A 区茶垄")
    is_mock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0"), comment="是否模拟设备"
    )
    online: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        comment="冗余在线状态（Redis 为准，定时回写）",
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, comment="最后心跳时间")
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, comment="采样间隔、标定基准等")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Device {self.device_id} {self.role} online={self.online}>"
