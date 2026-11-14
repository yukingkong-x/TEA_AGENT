"""任务状态机（PRD 10.2）——所有状态流转的唯一闸门。

为什么要有这一层：调度器、设备 ack 回调、验证引擎三处都会改任务状态，
分散写 `task.status = "xxx"` 迟早出现 `success → pending` 这种回魂状态，
任务页轨迹就会自我矛盾。这里把合法边一次性钉死，非法流转直接抛异常。

注意 `needs_human`：PRD 10.2 与 11.3 都要求它，但基座 `models/tasks.py` 的
MySQL 枚举当前只有 9 态、不含 needs_human——这是要队友 B 补的（见 docs/contracts）。
"""
from __future__ import annotations

STATUSES = (
    "pending",
    "dispatched",
    "running",
    "success",
    "failed",
    "timeout",
    "retrying",
    "dead",
    "needs_human",
    "canceled",
)

# 终态：调度器不再碰，只能人工介入
TERMINAL = frozenset({"success", "dead", "needs_human", "canceled"})

TRANSITIONS: dict[str, frozenset[str]] = {
    # 排队 → 派发；熔断期内的排队任务直接被判死（PRD 10.4 的 rejected）；
    # 取消/判死是人工或调度器的兜底出口
    "pending": frozenset({"dispatched", "canceled", "failed", "dead"}),
    "dispatched": frozenset({"running", "timeout", "failed", "canceled"}),
    "running": frozenset({"success", "failed", "timeout", "needs_human", "canceled"}),
    # 失败/超时先走重试；重试机会用尽才 dead
    "failed": frozenset({"retrying", "dead", "needs_human", "canceled"}),
    "timeout": frozenset({"retrying", "dead", "canceled"}),
    # retrying 到期回 pending 重新排队；也可人工判死
    "retrying": frozenset({"pending", "dead", "canceled"}),
    # 转人工后可被人工判成功/失败或取消
    "needs_human": frozenset({"success", "failed", "canceled"}),
    "success": frozenset(),
    "dead": frozenset(),
    "canceled": frozenset(),
}


class IllegalTransition(RuntimeError):
    def __init__(self, task_no: str, source: str, target: str) -> None:
        self.task_no = task_no
        self.source = source
        self.target = target
        super().__init__(f"任务 {task_no} 不允许 {source} → {target}")


def normalize(status: str | None) -> str:
    return (status or "").strip().lower()


def is_terminal(status: str | None) -> bool:
    return normalize(status) in TERMINAL


def can_transition(source: str | None, target: str | None) -> bool:
    src, dst = normalize(source), normalize(target)
    if src not in TRANSITIONS or dst not in TRANSITIONS:
        return False
    return dst in TRANSITIONS[src]


def ensure_transition(task_no: str, source: str | None, target: str | None) -> None:
    if not can_transition(source, target):
        raise IllegalTransition(task_no, str(source), str(target))


def is_active(status: str | None) -> bool:
    """已占用并发、正在等回执的状态。"""
    return normalize(status) in {"dispatched", "running"}


def is_retryable(status: str | None) -> bool:
    return normalize(status) in {"failed", "timeout"}
