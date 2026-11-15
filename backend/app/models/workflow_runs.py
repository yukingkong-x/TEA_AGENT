"""workflow_runs 执行实例表（PRD 6.5）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

RUN_STATUS = ("pending", "running", "success", "failed", "canceled", "needs_human")


class WorkflowRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_runs"

    wf_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="来源工作流")
    status: Mapped[str] = mapped_column(
        Enum(*RUN_STATUS, name="run_status"),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    trigger: Mapped[str | None] = mapped_column(
        String(32), comment="manual / schedule / event / selfloop"
    )
    context_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="全局上下文（各节点读写）"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, comment="结束时间")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WorkflowRun #{self.id} {self.status}>"
