"""SQLAlchemy 基类与公共列（PRD 6：主键统一 BIGINT AUTO_INCREMENT，每表带 created_at/updated_at）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """全部模型的基类，metadata 统一在 Base.metadata 上。"""


class IdMixin:
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="主键"
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
