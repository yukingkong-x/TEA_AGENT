"""调度循环（PRD 10.1/10.4/10.5）：并行 vs 串行、超时重试、离线挂起、熔断拒绝。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.orchestrator import state
from app.orchestrator.breaker import Breaker
from app.orchestrator.scheduler import Scheduler, SchedulerDeps, retry_delay_seconds

NOW = datetime(2026, 11, 14, 10, 0, 0)


def _task(task_no, **kwargs):
    base = {
        "task_no": task_no,
        "run_id": 1,
        "type": "agent_call",
        "status": "pending",
        "priority": 5,
        "created_at": NOW - timedelta(minutes=5),
        "updated_at": NOW - timedelta(minutes=5),
        "deadline_at": None,
        "retry_count": 0,
        "timeout_s": 60,
        "assigned_agent": None,
        "assigned_device": None,
    }
    base.update(kwargs)
    return base


class Harness:
    def __init__(self, tasks, *, parallel=True, max_retries=3, devices=None, loads=None):
        self.tasks = {t["task_no"]: t for t in tasks}
        self.now = NOW
        self.events: list[dict] = []
        self.parallel = parallel
        self.max_retries = max_retries
        self.devices = dict(devices or {})
        self.loads = dict(loads or {})
        self.breaker = Breaker(threshold=3, open_seconds=300)

    def deps(self) -> SchedulerDeps:
        return SchedulerDeps(
            list_tasks=lambda: [dict(t) for t in self.tasks.values()],
            apply=lambda task_no, fields: self.tasks[task_no].update(fields),
            emit=self.events.append,
            now=lambda: self.now,
            agent_load=lambda agent: self.loads.get(agent, 0.0),
            device_online=lambda device: self.devices.get(device, True),
            parallel_enabled=lambda: self.parallel,
            max_retries=self.max_retries,
            breaker=self.breaker,
        )

    def tick(self) -> dict:
        return Scheduler(self.deps()).tick()

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def status(self, task_no: str) -> str:
        return self.tasks[task_no]["status"]

    def reasons(self, task_no: str) -> list[str]:
        return [
            e["data"]["reason"] for e in self.events
            if e["type"] == "task_status" and e["data"]["task_no"] == task_no
        ]


# ─────────────────────── 派发 ───────────────────────

def test_parallel_dispatches_all_in_one_tick():
    harness = Harness([_task(f"t{i}") for i in range(3)], parallel=True)
    counts = harness.tick()
    assert counts["dispatched"] == 3
    assert all(harness.status(f"t{i}") == "dispatched" for i in range(3))


def test_serial_dispatches_one_per_tick():
    harness = Harness([_task(f"t{i}") for i in range(3)], parallel=False)
    assert harness.tick()["dispatched"] == 1
    assert harness.tick()["dispatched"] == 1
    assert harness.tick()["dispatched"] == 1
    assert harness.tick()["dispatched"] == 0        # 派完了


def test_offline_device_task_is_not_dispatched():
    harness = Harness([_task("t1", assigned_device="dev-1")], devices={"dev-1": False})
    assert harness.tick()["dispatched"] == 0
    assert harness.status("t1") == "pending"


def test_agent_capacity_is_respected_within_a_tick():
    # 同一个 Agent 上限 3：4 个任务只能派 3 个
    harness = Harness([_task(f"t{i}", assigned_agent="soil") for i in range(4)])
    assert harness.tick()["dispatched"] == 3


def test_dispatch_score_is_written():
    harness = Harness([_task("t1", priority=9)])
    harness.tick()
    assert harness.tasks["t1"]["score"] > 0
    dispatched = [e for e in harness.events if e["data"].get("to") == "dispatched"]
    assert dispatched[0]["data"]["score"] == harness.tasks["t1"]["score"]


# ─────────────────────── 超时与重试 ───────────────────────

def test_timeout_arms_retry_with_backoff():
    harness = Harness([
        _task("t1", status="dispatched", timeout_s=10, updated_at=NOW - timedelta(seconds=11)),
    ])
    counts = harness.tick()
    assert counts["timeouts"] == 1
    assert counts["retry_armed"] == 1
    assert harness.status("t1") == "retrying"
    assert harness.tasks["t1"]["retry_count"] == 1
    assert harness.reasons("t1")[:2] == ["timeout_10s", "retry_armed"]


def test_retry_waits_for_backoff_then_requeues():
    harness = Harness([
        _task("t1", status="dispatched", timeout_s=10, updated_at=NOW - timedelta(seconds=11)),
    ])
    harness.tick()                                    # → retrying，退避 2s
    harness.advance(1)
    assert harness.tick()["dispatched"] == 0
    assert harness.status("t1") == "retrying"

    harness.advance(1.5)
    counts = harness.tick()                           # 到期 → pending → 同一轮派发
    assert counts["retry_released"] == 1
    assert counts["dispatched"] == 1
    assert harness.status("t1") == "dispatched"


def test_retry_delay_sequence_is_2_4_8():
    assert [retry_delay_seconds(n) for n in (1, 2, 3)] == [2, 4, 8]


def test_retry_holds_when_device_offline():
    # 退避已到期（4s 前 armed）但设备仍离线 → 挂着等，不烧次数
    harness = Harness(
        [_task("t1", status="retrying", retry_count=2,
               updated_at=NOW - timedelta(seconds=5), assigned_device="dev-1")],
        devices={"dev-1": False},
    )
    counts = harness.tick()
    assert counts["retry_held"] == 1
    assert harness.status("t1") == "retrying"
    assert harness.tasks["t1"]["retry_count"] == 2      # 挂起不烧次数
    assert "retry_hold_offline" in harness.reasons("t1")


def test_retries_exhausted_goes_dead():
    harness = Harness([_task("t1", status="failed", retry_count=3)])
    counts = harness.tick()
    assert counts["dead"] == 1
    assert harness.status("t1") == "dead"
    assert "retries_exhausted" in harness.reasons("t1")


def test_third_retry_attempt_is_allowed_then_dead():
    harness = Harness([_task("t1", status="failed", retry_count=2)])
    harness.tick()
    assert harness.status("t1") == "retrying"
    assert harness.tasks["t1"]["retry_count"] == 3


# ─────────────────────── 熔断 ───────────────────────

def test_three_failures_open_breaker_and_alert_once():
    harness = Harness(
        [_task(f"t{i}", status="failed", retry_count=3, assigned_device="dev-1") for i in range(3)],
        devices={"dev-1": True},
    )
    counts = harness.tick()
    assert counts["dead"] == 3
    assert harness.breaker.is_open("dev-1", harness.now)
    alerts = [e for e in harness.events if e["type"] == "alert"]
    assert len(alerts) == 1
    assert alerts[0]["data"]["level"] == "critical"
    assert alerts[0]["data"]["source"] == "device:dev-1"
    assert "熔断" in alerts[0]["data"]["message"]


def test_pending_task_on_breached_device_is_rejected():
    harness = Harness([_task("queued", assigned_device="dev-1")], devices={"dev-1": True})
    for _ in range(3):                                # 设备已连续失败 3 次 → 熔断中
        harness.breaker.record_failure("dev-1", harness.now)

    counts = harness.tick()
    assert counts["rejected"] == 1
    assert counts["dispatched"] == 0
    assert harness.status("queued") == "dead"
    result = harness.tasks["queued"]["result_json"]
    assert result["rejected"] == "breaker_open"
    assert result["retry_after_s"] > 0
    assert "rejected_breaker_open" in harness.reasons("queued")


def test_breaker_recovers_after_window_and_new_task_dispatches():
    harness = Harness([_task("queued", assigned_device="dev-1")], devices={"dev-1": True})
    harness.breaker.record_failure("dev-1", harness.now)
    harness.breaker.record_failure("dev-1", harness.now)
    harness.breaker.record_failure("dev-1", harness.now)
    assert harness.tick()["rejected"] == 1
    assert harness.status("queued") == "dead"

    harness.advance(301)                              # 熔断自动解除
    harness.tasks["later"] = _task("later", assigned_device="dev-1")
    assert harness.tick()["dispatched"] == 1
    assert harness.status("later") == "dispatched"


def test_success_path_after_device_recovery():
    """PRD 10.5 第二条：断设备 → 超时 → 重试期间设备恢复 → 成功。"""
    harness = Harness(
        [_task("t1", status="dispatched", timeout_s=10, updated_at=NOW - timedelta(seconds=11),
               assigned_device="dev-1", assigned_agent="executor")],
        devices={"dev-1": False},
    )
    harness.tick()                                   # 超时 → 重试挂起
    assert harness.status("t1") == "retrying"

    harness.advance(3)
    harness.devices["dev-1"] = True                  # 设备恢复
    harness.tick()                                   # 退避到期 → pending → dispatched
    assert harness.status("t1") == "dispatched"

    harness.tasks["t1"].update(status="running", updated_at=harness.now)
    harness.tasks["t1"].update(status="success", updated_at=harness.now)
    assert state.is_terminal(harness.status("t1"))


# ─────────────────────── 健壮性 ───────────────────────

def test_illegal_transition_raises_instead_of_corrupting_state():
    harness = Harness([_task("t1", status="success")])
    with pytest.raises(state.IllegalTransition):
        Scheduler(harness.deps())._move(harness.tasks["t1"], "dispatched", harness.now)


def test_empty_store_is_a_noop():
    harness = Harness([])
    counts = harness.tick()
    assert counts["dispatched"] == 0 and counts["dead"] == 0
    assert harness.events == []


def test_task_status_event_shape():
    harness = Harness([_task("t1")])
    harness.tick()
    event = harness.events[0]
    assert set(event) == {"type", "data", "ts"}
    assert event["type"] == "task_status"
    for key in ("task_no", "from", "to", "reason", "retry_count"):
        assert key in event["data"]
    assert event["data"]["from"] == "pending" and event["data"]["to"] == "dispatched"
