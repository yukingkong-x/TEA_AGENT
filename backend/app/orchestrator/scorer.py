"""PRD 10.3 打分公式（REQ-F-014）。

    score = 0.4 × priority_normalized      # priority 1-10 → 0.1-1.0
          + 0.3 × urgency                  # 无 deadline=0.5；否则 1 - 剩余/总窗
          + 0.2 × (1 - agent_load)         # 目标 Agent 并发占用比
          + 0.1 × device_online            # 离线任务自然沉底

三个 PRD 没写死、但实现必须定的边界：
1. **无 deadline 的 urgency 记 0.5**（PRD 明写）。意味着「有 deadline 且很闲」的任务
   排得比「没 deadline」的高，这是对的——没时间窗就没有紧迫性可言。
2. **无目标设备的任务 device_online 记 1.0**：`agent_call` / `report` 这类任务本来就不
   绑设备，用 0 会把它们全部压到底，和「离线任务沉底」的本意相反。
3. **score 保留 2 位小数**：tasks.score 列是 DECIMAL(6,2)，多留的精度落库就被截断，
   排序按截断后的值再 FIFO，避免「算的时候差 0.0001、存进去一样」造成顺序漂移。
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable

WEIGHT_PRIORITY = 0.4
WEIGHT_URGENCY = 0.3
WEIGHT_LOAD = 0.2
WEIGHT_ONLINE = 0.1

DEFAULT_URGENCY = 0.5
DEFAULT_AGENT_CONCURRENCY = 3
DEFAULT_PRIORITY = 5


def _naive(value: datetime | None) -> datetime | None:
    """统一成 naive 本地时间：DB 里存的是 naive，混用 tz-aware 会在减法上直接炸。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def priority_norm(priority: int | None) -> float:
    """1-10 → 0.1-1.0；缺失或越界夹到合法区间，不让脏数据把分数打成负值。"""
    try:
        value = int(priority)
    except (TypeError, ValueError):
        value = DEFAULT_PRIORITY
    value = max(1, min(10, value))
    return value / 10.0


def urgency(created_at: datetime | None, deadline_at: datetime | None, now: datetime) -> float:
    """时间窗紧迫度：剩余/总窗越小越急；过期记 1.0；无窗口记 0.5。"""
    deadline = _naive(deadline_at)
    if deadline is None:
        return DEFAULT_URGENCY
    now = _naive(now) or now
    remaining = (deadline - now).total_seconds()
    if remaining <= 0:
        return 1.0
    created = _naive(created_at)
    if created is None:
        return DEFAULT_URGENCY
    total = (deadline - created).total_seconds()
    if total <= 0:
        # 建单时就已过期（或窗口为 0）：按最紧急处理，而不是除零
        return 1.0
    return max(0.0, min(1.0, 1.0 - remaining / total))


def load_ratio(active: int, limit: int = DEFAULT_AGENT_CONCURRENCY) -> float:
    """并发占用比，0-1。limit≤0 视为不限并发（记 0 占用）。"""
    if limit <= 0:
        return 0.0
    return max(0.0, min(1.0, active / limit))


def score_task(
    task: dict,
    *,
    now: datetime,
    agent_load: float = 0.0,
    device_online: bool = True,
) -> float:
    """单个任务的分数（0-1，2 位小数）。task 为任务快照 dict。"""
    parts = (
        WEIGHT_PRIORITY * priority_norm(task.get("priority")),
        WEIGHT_URGENCY * urgency(task.get("created_at"), task.get("deadline_at"), now),
        WEIGHT_LOAD * (1.0 - max(0.0, min(1.0, float(agent_load)))),
        WEIGHT_ONLINE * (1.0 if device_online else 0.0),
    )
    return round(sum(parts), 2)


def rank(
    tasks: Iterable[dict],
    *,
    now: datetime,
    load_of: Callable[[str | None], float] | None = None,
    online_of: Callable[[str | None], bool] | None = None,
) -> list[tuple[dict, float]]:
    """同分按 FIFO（created_at 升序），再按 task_no 兜底保证顺序稳定可复现。"""
    load_of = load_of or (lambda _agent: 0.0)
    online_of = online_of or (lambda _device: True)

    scored: list[tuple[dict, float]] = []
    for task in tasks:
        agent = task.get("assigned_agent")
        device = task.get("assigned_device")
        scored.append((
            task,
            score_task(
                task,
                now=now,
                agent_load=load_of(agent),
                device_online=online_of(device) if device else True,
            ),
        ))

    scored.sort(key=lambda pair: (
        -pair[1],
        _naive(pair[0].get("created_at")) or datetime.min,
        str(pair[0].get("task_no") or ""),
    ))
    return scored
