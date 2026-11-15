"""settings 全局配置表（PRD 6.14，键值对）。

写读都走 app/core/runtime_settings.py（带 Redis/内存缓存 + WS 广播），不要直接查这张表。

安全：`llm_api_key` 落库前用 Fernet 加密（SECRET_KEY 派生），API 读接口一律掩码返回。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Setting(IdMixin, TimestampMixin, Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, comment="配置键"
    )
    value: Mapped[Any | None] = mapped_column(JSON, comment="配置值（JSON，任意类型）")
    description: Mapped[str | None] = mapped_column(String(255), comment="用途说明，给设置页展示")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Setting {self.key}={self.value!r}>"
