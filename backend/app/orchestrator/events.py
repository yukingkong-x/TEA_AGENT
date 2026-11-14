"""任务轨迹事件（REQ-F-015）：给任务详情页的抽屉提供「每次状态变更的时间戳」。

PRD 986 行要求「点击行展开轨迹抽屉（pending→dispatched→running→…每次状态变更时间戳）」，
1044 行的剧本也要「全程展示状态机流转」。但两处数据源都不够：

- `tasks` 表只有 `created_at` / `updated_at`，中间态和每次变更的时间点推不出来；
- `task_status` 的 WS 推送只在内存里，页面一刷新就没了。

所以每次状态变更追加一行 `task_events`。

本模块只做**拼装与裁剪**，不 import ORM、不碰 session——落库由 wiring 注入的回调完成，
与 orchestrator 其余部分保持同样的纯逻辑边界（能全量单测，也不绑死表结构）。

去重是本模块的第二个职责：`retry_hold_offline` 每轮 tick 都会发一条同样的
`retrying → retrying`，设备离线 5 分钟就是 300 条，抽屉会被刷爆。所以「与上一行完全
同构」的事件不追加，抽屉里只留第一次挂起的时刻。
"""
from __future__ import annotations

import json
from typing import Any, Optional

MAX_PAYLOAD_CHARS = 4000
"""payload_json 的上限。超了只留白名单键——轨迹抽屉要的是状态流转，
不是某个 agent 的整段输出（那种长文本在 agent_messages 里）。"""

_KEEP_WHEN_BIG = (
    "task_no", "run_id", "from", "to", "reason",
    "retry_count", "score", "assigned_agent", "assigned_device",
    "rejected", "retry_after_s",
)

EVENT_TASK_STATUS = "task_status"
EVENT_ACK = "ack"
EVENT_VERIFY = "verify"
EVENT_NOTE = "note"


def build(
    *,
    task_no: str,
    event: str = EVENT_TASK_STATUS,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    reason: Optional[str] = None,
    actor: str = "scheduler",
    run_id: Optional[int] = None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """拼一行 `task_events` 的字段（不含 id / created_at，由基座填）。"""
    return {
        "task_no": str(task_no),
        "event": event,
        "from_status": from_status,
        "to_status": to_status,
        "reason": reason or None,
        "actor": actor,
        "run_id": int(run_id) if run_id is not None else None,
        "payload_json": _trim(payload),
    }


def from_task_status(data: dict[str, Any]) -> dict[str, Any]:
    """`task_status` 事件的 `data` → 一行轨迹。字段名沿用事件里的 `from` / `to`。"""
    result = data.get("result") if isinstance(data.get("result"), dict) else None
    payload = dict(data)
    if result and result.get("rejected") == "breaker_open":
        # 熔断拒绝的剩余时间要能被抽屉读到（「熔断拒绝 · 剩余 42s」）
        payload.setdefault("rejected", result.get("rejected"))
        payload.setdefault("retry_after_s", result.get("retry_after_s"))
    return build(
        task_no=str(data.get("task_no") or ""),
        event=EVENT_TASK_STATUS,
        from_status=data.get("from") or data.get("from_status"),
        to_status=data.get("to") or data.get("to_status"),
        reason=data.get("reason"),
        actor=str(data.get("actor") or "scheduler"),
        run_id=data.get("run_id"),
        payload=payload,
    )


def is_duplicate(previous: Optional[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    """与上一行同构就不追加（只用于 tick 反复发出的挂起/无变化事件）。

    比的是 `event + from + to + reason` 四元组，**不比 payload**——retry_count
    在挂起期间不变，但 `updated_at` 会变，那个不该算「新事件」。
    """
    if not previous:
        return False
    if previous.get("task_no") != candidate.get("task_no"):
        return False
    keys = ("event", "from_status", "to_status", "reason")
    return all(previous.get(k) == candidate.get(k) for k in keys)


def _trim(payload: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not payload:
        return None
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"_unserializable": True}
    if len(text) <= MAX_PAYLOAD_CHARS:
        return payload
    kept = {k: payload[k] for k in _KEEP_WHEN_BIG if k in payload}
    kept["_truncated"] = True
    return kept
