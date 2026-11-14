"""任务轨迹落库（REQ-F-015 / 契约第 11 节）。

为什么需要这个模块：`task_events` 的拼装逻辑在 `app/orchestrator/events.py`（队长），
但**写入口不止调度器一个**。设备指令这条链（`devices/command.py`）自己改状态、
自己广播 `task_status`，从不经过调度器，所以调度器的 `_emit` 钩子抓不到它——
而「设置页点一下浇水 → 任务列表点开看轨迹」恰恰是演示里被点得最多的一条路径。
不在这里补一笔，轨迹抽屉对 `device_cmd` 任务恒为空。

三条铁律（都对应一次真实故障形态）：

1. **不能影响主流程**：轨迹是加分项，写失败只能 warning。用 SAVEPOINT
   （`begin_nested`）包住插入，失败只回滚这一行，调用方那个「改状态」的事务照常提交；
2. **不能刷重复行**：设备重复回 `received` 时 `running→running` 会每毫秒来一条，
   同构事件交给 `events.is_duplicate` 丢掉，判定口径与调度器侧完全一致；
3. **不能硬依赖队长模块**：`orchestrator.events` 缺失时静默降级（只警告一次），
   与队长那边「缺表也能跑」的取舍对齐。

`from_status=None` 表示「任务刚建出来」，不是丢字段：`send_cmd` 建任务时状态直接是
`dispatched`，从来没有落过 `pending`，编一个假的 `pending` 反而会让人以为数据库里有那一跳。
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

_warned_unavailable = False
_warned_failing = False


def record(
    db: Session,
    *,
    task_no: str,
    from_status: str | None,
    to_status: str | None,
    reason: str | None = None,
    actor: str = "device",
    run_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """追加一行轨迹，返回是否真的写了（False = 跳过/降级）。

    `db` 用调用方的会话：轨迹与状态变更要么一起提交、要么一起回滚，
    不会出现「状态改了但没有轨迹」或反过来的半截数据。
    """
    global _warned_unavailable, _warned_failing

    try:
        from ..orchestrator.events import build, is_duplicate
        from ..models.task_events import TaskEvent
    except ModuleNotFoundError:
        if not _warned_unavailable:
            _warned_unavailable = True
            logger.warning("任务轨迹模块不可用（orchestrator.events / TaskEvent 缺失），轨迹暂不记录")
        return False

    if not task_no:
        return False

    candidate = build(
        task_no=task_no,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        actor=actor,
        run_id=run_id,
        payload=payload,
    )

    try:
        with db.begin_nested():  # SAVEPOINT：这一行失败不牵连调用方事务
            previous = db.scalar(
                select(TaskEvent)
                .where(TaskEvent.task_no == task_no)
                .order_by(TaskEvent.id.desc())
                .limit(1)
            )
            prev_row = (
                None
                if previous is None
                else {
                    "task_no": previous.task_no,
                    "event": previous.event,
                    "from_status": previous.from_status,
                    "to_status": previous.to_status,
                    "reason": previous.reason,
                }
            )
            if is_duplicate(prev_row, candidate):
                return False
            db.add(TaskEvent(**candidate))
        return True
    except Exception as exc:  # noqa: BLE001 轨迹写失败绝不能影响指令下发/回执
        if not _warned_failing:
            _warned_failing = True
            logger.warning("任务轨迹落库失败（{}）：{}（后续同类失败不再刷日志）", task_no, exc)
        return False
