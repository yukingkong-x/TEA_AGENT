"""agents Agent 配置表（PRD 6.3，REQ-F-002）。

提示词正文由队长在 app/agents/prompts.py 维护并在启动时写入本表；本表只负责存储与启停开关。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DECIMAL, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Agent(IdMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    agent_key: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        index=True,
        comment="scout / weather / soil / pest / decision / executor / verifier",
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False, comment="巡园管家")
    avatar: Mapped[str | None] = mapped_column(String(8), comment="emoji 或图标名")
    system_prompt: Mapped[str | None] = mapped_column(Text, comment="人设全文（设置页可改）")
    tools_json: Mapped[list[str] | None] = mapped_column(JSON, comment="绑定工具名列表")
    model: Mapped[str | None] = mapped_column(String(64), comment="默认取全局配置，可覆盖")
    temperature: Mapped[Decimal] = mapped_column(
        DECIMAL(3, 2), nullable=False, default=Decimal("0.30"), server_default=text("0.30")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1"), comment="停用开关"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Agent {self.agent_key} enabled={self.enabled}>"
