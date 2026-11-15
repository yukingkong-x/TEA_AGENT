"""当前 run 的上下文（run_id 的跨层传递）。

## 为什么需要

任务与验证记录都带 `run_id`：报告页按 run 聚合、`GET /api/runs/{id}` 靠
`Task.run_id` 取任务/时间线/轮次。为 NULL 时报告只剩一段文字、run 详情里 tasks 恒为空。

但建单发生在工具层（`create_task`）和设备层（`command.send_cmd`），两边都拿不到引擎的
run_id，而工具 schema 里也不该出现 run_id（LLM 不会填、也不能让它填）。所以用 ContextVar：
引擎起跑时 `set_current_run_id(run_id)`，工具在同一个 asyncio 上下文里读。

放在独立叶子模块而不是 `core/tool_impl.py`：`devices/command.py` 也要读，
而 `tool_impl` 反过来要 import `command` —— 变量放 tool_impl 就成了循环依赖。

## 谁 set

- 引擎（队长）：`workflow/engine.py` 的 `_drive()` 里 set / finally reset；
- 没 set 时的兜底见 `_only_running_run_id()`：**只有一条 running 的 run 才认**，
  0 条或多条都不猜（挂错 run 比记 NULL 更难排查）。
"""
from __future__ import annotations

from contextvars import ContextVar

from loguru import logger
from sqlalchemy import select

CURRENT_RUN_ID: ContextVar[int | None] = ContextVar("current_run_id", default=None)


def current_run_id() -> int | None:
    """当前 run 的 id：ContextVar 优先，否则取唯一 running 的那条。"""
    explicit = CURRENT_RUN_ID.get()
    if explicit is not None:
        return int(explicit)
    return _only_running_run_id()


def set_current_run_id(run_id: int | None):
    """引擎起跑时调用（返回 token，调用方在 finally 里 reset）。"""
    return CURRENT_RUN_ID.set(None if run_id is None else int(run_id))


def reset_current_run_id(token) -> None:
    CURRENT_RUN_ID.reset(token)


def _only_running_run_id() -> int | None:
    from ..db import session_scope
    from ..models.workflow_runs import WorkflowRun

    try:
        with session_scope() as db:
            rows = db.scalars(
                select(WorkflowRun.id)
                .where(WorkflowRun.status == "running")
                .order_by(WorkflowRun.id.desc())
                .limit(2)
            ).all()
    except Exception as exc:  # noqa: BLE001 记账失败不能拖垮建单/下发
        logger.debug("推断 run_id 失败（按 NULL 记账）：{}", exc)
        return None
    if len(rows) == 1:
        return int(rows[0])
    if len(rows) > 1:
        logger.warning("当前有 {} 条 running 的 run，run_id 记为 NULL（不猜）", len(rows))
    return None
