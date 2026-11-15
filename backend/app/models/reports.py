"""reports 报告表（PRD 6.12）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Enum, JSON
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

REPORT_TYPES = ("daily", "run")


class Report(IdMixin, TimestampMixin, Base):
    __tablename__ = "reports"

    run_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    report_type: Mapped[str] = mapped_column(
        Enum(*REPORT_TYPES, name="report_type"),
        nullable=False,
        default="run",
        comment="日报 / 单次执行报告",
    )
    content_md: Mapped[str | None] = mapped_column(LONGTEXT, comment="Markdown 全文")
    stats_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="汇总数字（任务数、成功率、平均达成率）"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Report #{self.id} {self.report_type} run={self.run_id}>"
