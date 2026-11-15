"""调度主循环（PRD 10.1，REQ-F-014）。

一轮 tick 的五步，顺序不能换：
    1. 超时扫描  —— 先判死，否则「已超时但还在跑」的任务会一直占着并发槽
    2. 失败/超时 → 重试编排（顺带记熔断失败计数）
    3. retrying 到期 → 回 pending（设备离线则挂起，不烧重试次数）
    4. 熔断设备的排队任务 → rejected
    5. 打分派发（parallel_enabled=false 时每轮只派 1 个）

与基座的边界：任务快照由 `deps.list_tasks()` 给，状态回写走 `deps.apply(task_no, fields)`，
本模块不 import 任何 ORM/session。事务边界、WS 广播格式由调用方决定，回调只负责「说出来」。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from app.orchestrator import scorer, state
from app.orchestrator.breaker import Breaker

logger = logging.getLogger(__name__)

RETRY_BASE_SECONDS = 2      # PRD 10.4 的例举是 2s / 4s / 8s


@dataclass
class SchedulerDeps:
    list_tasks: Callable[[], list[dict]]
    apply: Callable[[str, dict], None]
    emit: Callable[[dict], None]
    now: Callable[[], datetime]
    agent_load: Callable[[str], float] = lambda _agent: 0.0
    device_online: Callable[[str], bool] = lambda _device: True
    parallel_enabled: Callable[[], bool] = lambda: True
    max_retries: int = 3
    max_concurrency: int = scorer.DEFAULT_AGENT_CONCURRENCY
    default_timeout_s: int = 60
    breaker: Breaker = field(default_factory=Breaker)


def retry_delay_seconds(retry_count: int) -> int:
    """第 n 次重试前的退避：2 / 4 / 8 秒（PRD 10.4 例举）。

    PRD 的公式写作 `2^retry_count × 2s`，但同一节的例举与 15.2 剧本都是 2/4/8；
    以例举为准（剧本依赖这个节奏），公式按 `2^retry_count` 秒理解。
    """
    return RETRY_BASE_SECONDS ** max(1, int(retry_count))


class Scheduler:
    def __init__(self, deps: SchedulerDeps):
        self.deps = deps

    # ─────────────────────── 对外 ───────────────────────

    def tick(self) -> dict:
        now = self.deps.now()
        counts = {
            "timeouts": 0, "retry_armed": 0, "retry_released": 0,
            "retry_held": 0, "rejected": 0, "dead": 0, "dispatched": 0,
        }
        tasks = [t for t in self.deps.list_tasks() if t.get("task_no")]

        self._scan_timeouts(tasks, now, counts)
        self._arm_retries(tasks, now, counts)
        self._release_retries(tasks, now, counts)
        self._reject_breached(tasks, now, counts)
        self._dispatch(tasks, now, counts)

        counts["open_devices"] = self.deps.breaker.open_devices(now)
        return counts

    async def serve(self, stop: asyncio.Event | None = None, interval: float = 1.0) -> None:
        """1 秒一轮的主循环。单轮异常只记日志，绝不让循环退出（演示生命线）。"""
        logger.info("调度器启动：interval=%ss max_retries=%s parallel=%s",
                    interval, self.deps.max_retries, self.deps.parallel_enabled())
        while stop is None or not stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 一轮崩了不能带走整个调度器
                logger.exception("调度轮次异常：{}: {}", type(exc).__name__, exc)
            await asyncio.sleep(interval)

    # ─────────────────────── 五步 ───────────────────────

    def _scan_timeouts(self, tasks: list[dict], now: datetime, counts: dict) -> None:
        for task in tasks:
            if not state.is_active(task.get("status")):
                continue
            timeout_s = int(task.get("timeout_s") or self.deps.default_timeout_s)
            started = task.get("updated_at") or task.get("created_at")
            if started is None:
                continue
            if (now - started).total_seconds() < timeout_s:
                continue
            self._move(task, "timeout", now, reason=f"timeout_{timeout_s}s")
            counts["timeouts"] += 1

    def _arm_retries(self, tasks: list[dict], now: datetime, counts: dict) -> None:
        for task in tasks:
            if not state.is_retryable(task.get("status")):
                continue
            device = task.get("assigned_device")

            # 每次失败（含超时）都记一次设备失败；threshold 次连续失败即熔断
            if device and self.deps.breaker.record_failure(device, now):
                self._emit_alert(
                    now, f"device:{device}",
                    f"设备 {device} 连续失败已熔断（{self.deps.breaker.open_seconds}s）",
                )

            if device and self.deps.breaker.is_open(device, now):
                self._move(task, "dead", now, reason="breaker_open",
                           result={"rejected": "breaker_open", "device": device})
                counts["dead"] += 1
                continue

            retry_count = int(task.get("retry_count") or 0)
            if retry_count >= self.deps.max_retries:
                self._move(task, "dead", now, reason="retries_exhausted")
                counts["dead"] += 1
                continue

            self._move(task, "retrying", now, reason="retry_armed",
                       extra={"retry_count": retry_count + 1})
            counts["retry_armed"] += 1

    def _release_retries(self, tasks: list[dict], now: datetime, counts: dict) -> None:
        for task in tasks:
            if state.normalize(task.get("status")) != "retrying":
                continue
            retry_count = max(1, int(task.get("retry_count") or 1))
            armed_at = task.get("updated_at") or now
            due_in = retry_delay_seconds(retry_count) - (now - armed_at).total_seconds()
            if due_in > 0:
                continue

            device = task.get("assigned_device")
            if device and not self.deps.device_online(device):
                # 设备离线：挂着等，不烧重试次数（PRD 10.4「离线则挂起重试」）
                self.deps.apply(task["task_no"], {"updated_at": now})
                task["updated_at"] = now
                self._emit(task, "retrying", "retrying", now, reason="retry_hold_offline")
                counts["retry_held"] += 1
                continue

            self._move(task, "pending", now, reason="retry_due")
            counts["retry_released"] += 1

    def _reject_breached(self, tasks: list[dict], now: datetime, counts: dict) -> None:
        for task in tasks:
            if state.normalize(task.get("status")) != "pending":
                continue
            device = task.get("assigned_device")
            if not device or not self.deps.breaker.is_open(device, now):
                continue
            self._move(task, "dead", now, reason="rejected_breaker_open",
                       result={
                           "rejected": "breaker_open",
                           "device": device,
                           "retry_after_s": self.deps.breaker.remaining_seconds(device, now),
                       })
            counts["rejected"] += 1
            counts["dead"] += 1

    def _dispatch(self, tasks: list[dict], now: datetime, counts: dict) -> None:
        pending = [t for t in tasks if state.normalize(t.get("status")) == "pending"]
        if not pending:
            return

        local_load: dict[str, int] = {}
        ranked = scorer.rank(
            pending,
            now=now,
            load_of=lambda agent: self._load(agent, local_load),
            online_of=self.deps.device_online,
        )
        serial = not self.deps.parallel_enabled()
        limit = 1 if serial else len(ranked)

        for task, score in ranked:
            if counts["dispatched"] >= limit:
                break
            device = task.get("assigned_device")
            if device and not self.deps.device_online(device):
                # 设备离线：离线任务自然沉底，但同一轮里也不派它（省一次必然失败）
                continue
            agent = task.get("assigned_agent")
            if agent and self._load(agent, local_load) >= 1.0:
                continue

            self._move(task, "dispatched", now, reason="dispatch", extra={"score": score})
            if agent:
                local_load[agent] = local_load.get(agent, 0) + 1
            counts["dispatched"] += 1

    # ─────────────────────── 工具 ───────────────────────

    def _load(self, agent: str | None, local_load: dict[str, int]) -> float:
        """Agent 并发占用比：基座读数 + 本轮已派发数（同一 tick 内不能自己骗自己）。"""
        if not agent:
            return 0.0
        base = float(self.deps.agent_load(agent) or 0.0)
        extra = local_load.get(agent, 0) / max(1, self.deps.max_concurrency)
        return min(1.0, max(0.0, base + extra))

    def _move(
        self,
        task: dict,
        target: str,
        now: datetime,
        *,
        reason: str = "",
        extra: dict | None = None,
        result: dict | None = None,
    ) -> None:
        source = state.normalize(task.get("status"))
        state.ensure_transition(task["task_no"], source, target)   # 非法流转必须炸出来

        fields: dict = {"status": target, "updated_at": now}
        if extra:
            fields.update(extra)
        if result is not None:
            fields["result_json"] = result
        self.deps.apply(task["task_no"], fields)

        task.update(fields)
        self._emit(task, source, target, now, reason=reason)

    def _emit(self, task: dict, source: str, target: str, now: datetime, *, reason: str = "") -> None:
        data = {
            "task_no": task.get("task_no"),
            "run_id": task.get("run_id"),
            "from": source,
            "to": target,
            "reason": reason,
            "retry_count": task.get("retry_count", 0),
            "assigned_agent": task.get("assigned_agent"),
            "assigned_device": task.get("assigned_device"),
        }
        if task.get("score") is not None:
            data["score"] = task.get("score")
        if isinstance(task.get("result_json"), dict):
            data["result"] = task["result_json"]
        self.deps.emit({"type": "task_status", "data": data, "ts": now.isoformat()})

    def _emit_alert(self, now: datetime, source: str, message: str) -> None:
        self.deps.emit({
            "type": "alert",
            "data": {"level": "critical", "source": source, "message": message},
            "ts": now.isoformat(),
        })
