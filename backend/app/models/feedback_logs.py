"""feedback_logs 反馈修正日志（PRD 6.13，REQ-F-018 证据链）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class FeedbackLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "feedback_logs"

    run_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="第几轮（1,2,...）")
    failure_reason: Mapped[str | None] = mapped_column(
        Text, comment="诊断：沙质土渗透快于预期，单次水量不足"
    )
    correction_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment='修正动作 {"strategy": "split", "duration_s": 20, "interval_s": 60, "times": 2}'
    )
    next_task_no: Mapped[str | None] = mapped_column(String(32), comment="修正后新任务")
    outcome: Mapped[str | None] = mapped_column(
        String(16), comment="improved / same / worse（下一轮回填）"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FeedbackLog run={self.run_id} round={self.round}>"
