"""decisions 决策记录（PRD 6.8）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Decision(IdMixin, TimestampMixin, Base):
    __tablename__ = "decisions"

    run_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    decision_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="irrigate / none / escalate"
    )
    summary: Mapped[str | None] = mapped_column(String(255), comment="A 区缺水，建议浇水 30 秒")
    params_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment='{"device_id": "k10-act-03", "duration_s": 30, "target_range": [55, 65]}'
    )
    basis_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="决策依据（引用各 Agent 结论摘要）"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Decision {self.decision_type} run={self.run_id}>"
