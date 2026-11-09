"""workflows 工作流定义表（PRD 6.4，dag_json 结构见第 9 章）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Workflow(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflows"

    wf_key: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="patrol_irrigation（标准巡园浇水）"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="巡园浇水工作流")
    dag_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="节点与边")
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"), comment="每次保存 +1"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Workflow {self.wf_key} v{self.version}>"
