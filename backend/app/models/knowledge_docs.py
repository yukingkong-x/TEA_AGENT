"""knowledge_docs 知识库文档表（PRD 6.10）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Enum, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

DOC_STATUS = ("processing", "ready", "failed")


class KnowledgeDoc(IdMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_docs"

    title: Mapped[str] = mapped_column(String(128), nullable=False, comment="文档名")
    source: Mapped[str | None] = mapped_column(String(255), comment="来源（标准号/书名/URL）")
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="切片数"
    )
    chroma_ids_json: Mapped[list[str] | None] = mapped_column(JSON, comment="对应向量库 id")
    status: Mapped[str] = mapped_column(
        Enum(*DOC_STATUS, name="doc_status"),
        nullable=False,
        default="processing",
        server_default="processing",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<KnowledgeDoc {self.title} {self.status}>"
