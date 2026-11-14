"""节点级执行记录的落库入口（`workflow_node_records` 表）。

引擎里 `RunResult.nodes`（`workflow/engine.py` 的 NodeRecord）在 run 结束时已经攒齐了
每个节点的 status / duration_ms / degraded / tool_calls / tokens。这些数据现在只走
WS 广播和日志，进程一重启就没了，报告页只能拿 task_events 顶时间线——而 task_events
挂在 task_no 上，决策= none 的轮次一条都没有。

所以引擎只需在收尾处加**一行**：

    from app.core import node_records
    await asyncio.to_thread(node_records.record_run_nodes, result.run_id, result.nodes)

放在 `_drive` 的 finally 里（`result.nodes` 已全部落定，run_id 也定了）。本模块自己
吞掉所有异常：记账失败绝不能把一次成功的 run 打成失败。

已知限制（写在文档里，不藏）：引擎的 `by_id` 按 node_id 去重，Self-Loop 重跑同一个
验证节点时是同一条 NodeRecord 被覆盖，所以这里只能记到**最后一次**的状态与耗时。
要展示「第 1 轮 8.2s / 第 2 轮 6.7s」需要引擎每轮 append 新的 NodeRecord，属于引擎侧
改动，不在基座范围内。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from loguru import logger
from sqlalchemy import select

from ..db import session_scope
from ..models.workflow_node_records import WorkflowNodeRecord

# loop 节点的 output 固定是 "rounds=N"（见 engine 的 loop 分支），从里面取轮次
_ROUNDS_RE = re.compile(r"rounds=(\d+)")


def _attr(record: Any, key: str, default: Any = None) -> Any:
    """NodeRecord 对象和 dict 都吃，调用方不必先转一道。"""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _round_of(record: Any) -> int:
    explicit = _attr(record, "round_no", None)
    if explicit is None:
        explicit = _attr(record, "round", None)
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    match = _ROUNDS_RE.search(str(_attr(record, "output", "") or ""))
    return int(match.group(1)) if match else 0


def _to_row(run_id: int, record: Any, now: datetime) -> WorkflowNodeRecord:
    duration_ms = int(_attr(record, "duration_ms", 0) or 0)
    return WorkflowNodeRecord(
        run_id=int(run_id),
        node_id=str(_attr(record, "node_id", "") or ""),
        node_type=str(_attr(record, "type", "") or _attr(record, "node_type", "") or ""),
        name=(_attr(record, "name") or None),
        agent_key=(_attr(record, "agent_key") or None),
        status=str(_attr(record, "status", "pending") or "pending"),
        output=_attr(record, "output") or None,
        error=_attr(record, "error") or None,
        degraded=bool(_attr(record, "degraded", False)),
        duration_ms=max(0, duration_ms),
        tokens_in=int(_attr(record, "tokens_in", 0) or 0),
        tokens_out=int(_attr(record, "tokens_out", 0) or 0),
        tool_calls_json=(_attr(record, "tool_calls") or None),
        round_no=_round_of(record),
        finished_at=now,
        started_at=now - timedelta(milliseconds=max(0, duration_ms)) if duration_ms else None,
    )


def record_run_nodes(run_id: Optional[int], records: Iterable[Any]) -> int:
    """把一个 run 的全部节点记录写库，返回新增行数。

    幂等：同一 `(run_id, node_id)` 已有行就跳过（补写/重试不会插重复）。
    `run_id` 为空（run 没落库）或表不存在时直接返回 0，不打日志噪声。
    """
    if not run_id:
        return 0
    items = list(records or [])
    if not items:
        return 0
    now = datetime.now()
    try:
        with session_scope() as db:
            existing = set(
                db.scalars(
                    select(WorkflowNodeRecord.node_id).where(WorkflowNodeRecord.run_id == int(run_id))
                ).all()
            )
            added = 0
            for record in items:
                node_id = str(_attr(record, "node_id", "") or "")
                if not node_id or node_id in existing:
                    continue
                db.add(_to_row(int(run_id), record, now))
                existing.add(node_id)
                added += 1
            return added
    except Exception as exc:  # noqa: BLE001 记账失败不能拖垮 run
        logger.warning("节点记录落库失败（run={}）：{}", run_id, exc)
        return 0


def load_run_nodes(run_id: int) -> list[dict[str, Any]]:
    """按执行顺序返回某 run 的节点记录（表不存在时返回空列表）。"""
    try:
        with session_scope() as db:
            rows = db.scalars(
                select(WorkflowNodeRecord)
                .where(WorkflowNodeRecord.run_id == int(run_id))
                .order_by(WorkflowNodeRecord.id)
            ).all()
            return [to_dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001 接口读不到不该 500
        logger.warning("节点记录读取失败（run={}）：{}", run_id, exc)
        return []


def to_dict(row: WorkflowNodeRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "node_id": row.node_id,
        "node_type": row.node_type,
        "name": row.name,
        "agent_key": row.agent_key,
        "status": row.status,
        "output": row.output,
        "error": row.error,
        "degraded": bool(row.degraded),
        "duration_ms": int(row.duration_ms or 0),
        "tokens_in": int(row.tokens_in or 0),
        "tokens_out": int(row.tokens_out or 0),
        "tool_calls": row.tool_calls_json or [],
        "round_no": int(row.round_no or 0),
        "started_at": row.started_at.isoformat(timespec="seconds") if row.started_at else None,
        "finished_at": row.finished_at.isoformat(timespec="seconds") if row.finished_at else None,
    }


def summarize(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """报告页顶部的汇总：总耗时、最慢节点、降级数。纯函数，方便单测。"""
    if not nodes:
        return {"node_count": 0, "duration_ms": 0, "slowest": None, "degraded_count": 0, "failed_count": 0}
    slowest = max(nodes, key=lambda n: int(n.get("duration_ms") or 0))
    return {
        "node_count": len(nodes),
        "duration_ms": sum(int(n.get("duration_ms") or 0) for n in nodes),
        "slowest": {
            "node_id": slowest.get("node_id"),
            "name": slowest.get("name"),
            "duration_ms": int(slowest.get("duration_ms") or 0),
        },
        "degraded_count": sum(1 for n in nodes if n.get("degraded")),
        "failed_count": sum(1 for n in nodes if n.get("status") == "failed"),
    }
