"""alerts 报警表（PRD 6.11）。"""
from __future__ import annotations

from sqlalchemy import Boolean, Enum, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

ALERT_LEVELS = ("info", "warning", "critical")


class Alert(IdMixin, TimestampMixin, Base):
    __tablename__ = "alerts"

    level: Mapped[str] = mapped_column(
        Enum(*ALERT_LEVELS, name="alert_level"), nullable=False, index=True
    )
    source: Mapped[str | None] = mapped_column(
        String(64), comment="device:k10-act-03 / agent:verifier"
    )
    message: Mapped[str | None] = mapped_column(String(255))
    acknowledged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0"), comment="人工确认"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Alert {self.level} {self.message}>"
