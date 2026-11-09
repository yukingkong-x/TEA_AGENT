"""verifications 验证记录（PRD 6.9，Self-Loop 核心证据）。"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import DECIMAL, BigInteger, Enum, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

CONCLUSIONS = ("success", "failed", "needs_human")


class Verification(IdMixin, TimestampMixin, Base):
    __tablename__ = "verifications"

    run_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    task_no: Mapped[str | None] = mapped_column(String(32), index=True, comment="被验证的任务")
    baseline_value: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), comment="执行前基准值 38.5")
    target_low: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), comment="目标下限 55")
    target_high: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), comment="目标上限 65")
    measured_value: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), comment="复测值 45.0")
    achievement: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), comment="达成率 41.18（%）")
    confidence: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), comment="置信度 0-100")
    conf_detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, comment="三路证据分数")
    conclusion: Mapped[str | None] = mapped_column(
        Enum(*CONCLUSIONS, name="verify_conclusion"), comment="结论"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Verification {self.task_no} {self.conclusion}>"
