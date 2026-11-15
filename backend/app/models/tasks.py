"""tasks 任务表（PRD 6.6，调度器核心；状态机见 10.2）。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DECIMAL, BigInteger, DateTime, Enum, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

TASK_STATUS = (
    "pending",
    "dispatched",
    "running",
    "success",
    "failed",
    "timeout",
    "retrying",
    "dead",
    # 转人工：置信度不足/证据存疑时不硬判成败，交给人复核（PRD 10.2 / 11.3）。
    # 与 workflow_runs.status 的枚举对齐——两边口径不一致时，同一件事在画布上显示
    # 「待处理」、在任务列表显示「失败」，评审一眼就能看出是 bug。
    "needs_human",
    "canceled",
)


class Task(IdMixin, TimestampMixin, Base):
    __tablename__ = "tasks"

    task_no: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True, comment="task-20261103-0007"
    )
    run_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="所属执行实例")
    type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="agent_call / device_cmd / verify / report / selfloop"
    )
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, comment="任务参数")
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default=text("5"), comment="1-10"
    )
    score: Mapped[Decimal | None] = mapped_column(DECIMAL(6, 2), comment="调度打分")
    status: Mapped[str] = mapped_column(
        Enum(*TASK_STATUS, name="task_status"),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
        comment="状态机见 PRD 10.2",
    )
    assigned_agent: Mapped[str | None] = mapped_column(String(32), comment="接单 Agent")
    assigned_device: Mapped[str | None] = mapped_column(String(32), index=True, comment="目标设备")
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="已重试次数（上限 3）"
    )
    timeout_s: Mapped[int | None] = mapped_column(Integer, comment="超时秒数")
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, comment="时间窗")
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, comment="执行结果")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task {self.task_no} {self.type} {self.status}>"
