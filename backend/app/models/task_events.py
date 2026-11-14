"""task_events 任务轨迹事件（REQ-F-015，PRD 986/1044 的轨迹抽屉数据源）。

为什么单独一张表：`tasks` 只有 `created_at`/`updated_at`，`dispatched→running→timeout→retrying`
这些中间态推不出来；`task_status` 的 WS 推送只在内存里，页面一刷新就没了。
所以每次状态变更落一行，前端轨迹抽屉按 `id` 升序直接画。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

# 取值：task_status / ack / verify / note
# 用 String 不用 Enum：Enum 加值要 ALTER 老库，`tasks.status` 上已经踩过一次
# （见 db._sync_enum_column 的注释）。这张表是纯追加写的流水，不值得再引一次 DDL 风险。
TASK_EVENT_KINDS = ("task_status", "ack", "verify", "note")


class TaskEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "task_events"
    # 覆盖索引：轨迹查询永远是「specified task_no + 按 id 升序」，一条索引走完
    __table_args__ = (Index("ix_task_events_task_no_id", "task_no", "id"),)

    task_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="任务号")
    # BigInteger 与 tasks.run_id 保持一致：Integer 在自增执行号上会溢出
    run_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="所属执行")
    event: Mapped[str] = mapped_column(String(16), nullable=False, comment="事件类型")
    from_status: Mapped[str | None] = mapped_column(String(16), comment="变更前状态")
    to_status: Mapped[str | None] = mapped_column(String(16), comment="变更后状态")
    reason: Mapped[str | None] = mapped_column(String(48), comment="机器可读原因")
    actor: Mapped[str] = mapped_column(
        String(32), nullable=False, default="scheduler", server_default="scheduler", comment="触发方"
    )
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, comment="事件原始载荷")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TaskEvent {self.task_no} {self.event} {self.from_status}->{self.to_status}>"
