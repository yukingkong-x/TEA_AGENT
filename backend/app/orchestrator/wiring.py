"""把调度器接到基座：DB 快照 / 状态回写 / WS 广播 / 运行时开关。

**接线只要一行**（队友 B 在 `bootstrap.start_all()` 末尾加）：
```python
from .orchestrator.wiring import start_scheduler
start_scheduler()
```
`stop_all()` 里加 `stop_scheduler()`。

为什么单独放一个 wiring 而不是塞进 scheduler.py：引擎要保持「不 import ORM」才能在
单测里跑几百轮 tick；一旦 scheduler.py 依赖 session，所有测试都得先起数据库。
这个文件的 import 也全部放在函数内部——万一基座模型改了名，坏的是调度器，
而不是整个 FastAPI 起不来（演示生命线）。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from app.orchestrator.breaker import Breaker
from app.orchestrator.scheduler import Scheduler, SchedulerDeps

# 调度器关心的状态：终态（success/dead/canceled/needs_human）不扫，省每轮开销
SCAN_STATUSES = ("pending", "dispatched", "running", "failed", "timeout", "retrying")
ACTIVE_STATUSES = ("dispatched", "running")
SCAN_LIMIT = 200

_breaker = Breaker()
_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def get_breaker() -> Breaker:
    """设置页「解除熔断」与任务页熔断徽章都从这里拿同一个实例。"""
    return _breaker


# ─────────────────────────── 基座适配 ───────────────────────────

def _list_tasks() -> list[dict]:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.tasks import Task

    with session_scope() as db:
        rows = db.scalars(
            select(Task).where(Task.status.in_(SCAN_STATUSES)).order_by(Task.id).limit(SCAN_LIMIT)
        ).all()
        return [
            {
                "task_no": row.task_no,
                "run_id": row.run_id,
                "type": row.type,
                "status": row.status,
                "priority": row.priority,
                "score": float(row.score) if row.score is not None else None,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "deadline_at": row.deadline_at,
                "retry_count": row.retry_count or 0,
                "timeout_s": row.timeout_s,
                "assigned_agent": row.assigned_agent,
                "assigned_device": row.assigned_device,
                "result_json": row.result_json,
            }
            for row in rows
        ]


def _apply(task_no: str, fields: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.tasks import Task

    with session_scope() as db:
        task = db.scalar(select(Task).where(Task.task_no == task_no))
        if task is None:
            logger.warning("调度器回写失败：任务 {} 不存在（可能被删）", task_no)
            return
        for key, value in fields.items():
            if hasattr(task, key):
                setattr(task, key, value)
            else:
                logger.warning("调度器回写跳过未知字段 {} → {}", task_no, key)


def _agent_load(agent: str) -> float:
    """该 Agent 当前并发占用比（0-1）。读不到就按空闲处理，不让调度卡住。"""
    try:
        from sqlalchemy import func, select

        from app.core.runtime_settings import get_value
        from app.db import session_scope
        from app.models.tasks import Task

        limit = int(get_value("agent_max_concurrency", 3) or 3)
        if limit <= 0:
            return 0.0
        with session_scope() as db:
            active = db.scalar(
                select(func.count()).select_from(Task).where(
                    Task.assigned_agent == agent, Task.status.in_(ACTIVE_STATUSES)
                )
            )
        return min(1.0, float(active or 0) / limit)
    except Exception as exc:  # noqa: BLE001 计数失败不该阻塞派发
        logger.warning("读取 Agent 并发失败（{}），按空闲处理", exc)
        return 0.0


def _device_online(device_id: str) -> bool:
    """在线状态以 devices 表为准（Redis 心跳由 inspection 循环刷进来）。"""
    try:
        from sqlalchemy import select

        from app.db import session_scope
        from app.models.devices import Device

        with session_scope() as db:
            online = db.scalar(select(Device.online).where(Device.device_id == device_id))
        return True if online is None else bool(online)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取设备在线状态失败（{}），按在线处理", exc)
        return True


def _emit(event: dict) -> None:
    """调度器事件 → WS 广播 + 任务轨迹落库。

    调度器发的是**嵌套**形态 `{"type","data","ts"}`（与工作流引擎的扁平不同，
    那边由 `workflow/wiring._emit` 自己收字段），这里直接取 `data`。
    """
    from app.core.ws_manager import manager

    data = event.get("data")
    manager.publish_threadsafe(event["type"], data)

    if event.get("type") == "task_status" and isinstance(data, dict):
        _record_task_event(data)


_warned_no_event_table = False


def _record_task_event(data: dict) -> None:
    """往 `task_events` 追加一行轨迹。

    表还没建时**静默跳过并只警告一次**：这张表是 REQ-F-015 的加分项，
    缺它不能让调度器停摆；但每 tick 都刷一条 warning 会把日志淹了。
    """
    global _warned_no_event_table

    try:
        from sqlalchemy import select

        from app.db import session_scope
        from app.models.task_events import TaskEvent
    except ModuleNotFoundError:
        if not _warned_no_event_table:
            _warned_no_event_table = True
            logger.warning("task_events 表尚未建立，任务轨迹暂不可用（调度与 WS 不受影响）")
        return
    except Exception as exc:  # noqa: BLE001 库连不上也不能影响调度
        logger.warning("任务轨迹不可用（初始化失败）：{}", exc)
        return

    from app.orchestrator.events import from_task_status, is_duplicate

    candidate = from_task_status(data)
    if not candidate["task_no"]:
        return

    try:
        with session_scope() as db:
            previous = db.scalar(
                select(TaskEvent)
                .where(TaskEvent.task_no == candidate["task_no"])
                .order_by(TaskEvent.id.desc())
                .limit(1)
            )
            prev_row = None
            if previous is not None:
                prev_row = {
                    "task_no": previous.task_no,
                    "event": previous.event,
                    "from_status": previous.from_status,
                    "to_status": previous.to_status,
                    "reason": previous.reason,
                }
            if is_duplicate(prev_row, candidate):      # 挂起等设备时每 tick 一条，别刷 300 行
                return
            db.add(TaskEvent(**candidate))
    except Exception as exc:  # noqa: BLE001 轨迹写失败不能影响调度
        logger.warning("任务轨迹落库失败（{}）：{}", candidate.get("task_no"), exc)


def build_deps() -> SchedulerDeps:
    from app.core.runtime_settings import get_value

    return SchedulerDeps(
        list_tasks=_list_tasks,
        apply=_apply,
        emit=_emit,
        now=datetime.now,
        agent_load=_agent_load,
        device_online=_device_online,
        parallel_enabled=lambda: bool(get_value("parallel_enabled", True)),
        max_retries=int(get_value("max_retries", 3) or 3),
        breaker=_breaker,
    )


# ─────────────────────────── 起停 ───────────────────────────

def tick_once() -> dict:
    """跑一轮（测试/接口手动触发都走这里，复用同一个 breaker）。"""
    return Scheduler(build_deps()).tick()


def _loop() -> None:
    scheduler = Scheduler(build_deps())
    while not _stop.is_set():
        try:
            scheduler.tick()
        except Exception as exc:  # noqa: BLE001 单轮崩了不能带走整个循环
            logger.exception("调度轮次异常：{}", exc)
        _stop.wait(1.0)
    logger.info("调度线程退出")


def start_scheduler() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    _thread.start()
    logger.info("调度器启动（1s 一轮）")


def stop_scheduler() -> None:
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=3)
