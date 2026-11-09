"""agent_messages Agent 对话记录（PRD 6.7，对话剧场数据源）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Enum, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

MESSAGE_ROLES = ("user", "assistant", "tool", "system")


class AgentMessage(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_messages"

    run_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    agent_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="发言者")
    role: Mapped[str] = mapped_column(
        Enum(*MESSAGE_ROLES, name="message_role"), nullable=False, comment="消息角色"
    )
    content: Mapped[str | None] = mapped_column(Text, comment="文本内容")
    tool_calls_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, comment="工具调用与返回（可折叠展示）"
    )
    citations_json: Mapped[list[Any] | None] = mapped_column(
        JSON, comment="引用的知识库条目 id 数组"
    )
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentMessage {self.agent_key}/{self.role} run={self.run_id}>"
