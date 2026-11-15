"""workflow_node_records 节点级执行记录（PRD 9.1「每个节点耗时表」的数据源）。

为什么不拿 task_events 顶：task_events 挂在 `task_no` 上，**没有任务的 run 就一条都没有**
（决策 none 的巡园轮次、只跑到 condition 就结束的 run）；而且它只有状态跳变，没有
tokens / degraded / tool_calls / round，做不出「哪个 Agent 慢、哪个降级了、第几轮超时」。
报告页要的耗时表是 `run_id → 节点 → 耗时/状态/降级/工具调用`，这是另一条事实线。

和 `agent_messages` 的区别：那种表只记 LLM 发言（agent 节点），start/condition/parallel/
loop/tool 这些节点根本没有发言，但它们的耗时同样是时间线的一部分，也是「并行分支到底省了
多少」的唯一证据。

写入时机：一个 run 结束后一次性批量写（`core/node_records.record_run_nodes`）。逐节点写会
让并行分支的多个协程同时抢连接，且报告页本来就在 run 结束后才看。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class WorkflowNodeRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_node_records"
    # 报告页永远是「某个 run + 按执行顺序」，一条覆盖索引走完；
    # 唯一键让重跑/补写幂等（同一 run 同一节点只有一行，后写的跳过而不是插重复）。
    __table_args__ = (
        Index("ix_node_records_run_id_id", "run_id", "id"),
        UniqueConstraint("run_id", "node_id", name="uq_node_records_run_node"),
    )

    # BigInteger 与 tasks.run_id / task_events.run_id 一致
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属执行")
    node_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="DAG 节点 id")
    node_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="agent/condition/parallel/loop/tool/start/end")
    name: Mapped[str | None] = mapped_column(String(64), comment="节点中文名")
    agent_key: Mapped[str | None] = mapped_column(String(32), comment="仅 agent 节点")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending",
        comment="pending/running/done/failed/skipped",
    )
    output: Mapped[str | None] = mapped_column(Text, comment="节点产出摘要（正文，可能很长）")
    error: Mapped[str | None] = mapped_column(Text, comment="失败原因")
    degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0"), comment="是否走了降级模板"
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="节点耗时（毫秒）"
    )
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    tool_calls_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, comment="本节点工具调用明细")
    round_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="Self-Loop 轮次（首轮 1，重试递增）",
    )
    # 引擎的 NodeRecord 只有 duration_ms，没有开始时刻；用「写入时刻 - 耗时」反推，
    # 二者都存是为了让前端不必自己算。引擎若以后能给出 started_at，优先用它。
    started_at: Mapped[datetime | None] = mapped_column(DateTime, comment="节点开始时刻（可空）")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, comment="节点结束时刻（可空）")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WorkflowNodeRecord run={self.run_id} {self.node_id} {self.status} {self.duration_ms}ms>"
