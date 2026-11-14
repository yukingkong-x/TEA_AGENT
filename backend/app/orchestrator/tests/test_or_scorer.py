"""打分公式（PRD 10.3）：四路权重、三个边界、同分 FIFO。"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.orchestrator import scorer

NOW = datetime(2026, 11, 14, 10, 0, 0)


def _task(**kwargs):
    base = {
        "task_no": "task-1",
        "priority": 5,
        "created_at": NOW - timedelta(minutes=5),
        "deadline_at": None,
        "assigned_agent": "soil",
        "assigned_device": None,
    }
    base.update(kwargs)
    return base


def test_priority_dominates_first_term():
    low = scorer.score_task(_task(priority=1), now=NOW)
    high = scorer.score_task(_task(priority=10), now=NOW)
    assert high - low == 0.36          # 0.4 × (1.0 - 0.1)


def test_no_deadline_uses_half_urgency():
    assert scorer.urgency(NOW, None, NOW) == 0.5


def test_urgency_grows_as_deadline_approaches():
    created = NOW - timedelta(minutes=10)
    early = scorer.urgency(created, NOW + timedelta(minutes=8), NOW)
    late = scorer.urgency(created, NOW + timedelta(minutes=2), NOW)
    assert early < late


def test_expired_deadline_is_max_urgency():
    assert scorer.urgency(NOW - timedelta(minutes=10), NOW - timedelta(minutes=1), NOW) == 1.0


def test_zero_window_does_not_divide_by_zero():
    assert scorer.urgency(NOW, NOW, NOW) == 1.0


def test_offline_device_loses_last_tenth():
    online = scorer.score_task(_task(assigned_device="dev-1"), now=NOW, device_online=True)
    offline = scorer.score_task(_task(assigned_device="dev-1"), now=NOW, device_online=False)
    assert round(online - offline, 2) == 0.1


def test_loaded_agent_scores_lower():
    idle = scorer.score_task(_task(), now=NOW, agent_load=0.0)
    busy = scorer.score_task(_task(), now=NOW, agent_load=1.0)
    assert round(idle - busy, 2) == 0.2


def test_load_ratio_clamped():
    assert scorer.load_ratio(0) == 0.0
    assert scorer.load_ratio(3) == 1.0
    assert scorer.load_ratio(6) == 1.0
    assert scorer.load_ratio(5, limit=0) == 0.0


def test_rank_orders_by_score_then_fifo():
    tasks = [
        _task(task_no="a", priority=1, created_at=NOW - timedelta(seconds=30)),
        _task(task_no="b", priority=9, created_at=NOW - timedelta(seconds=10)),
        _task(task_no="c", priority=1, created_at=NOW - timedelta(seconds=60)),
    ]
    ranked = scorer.rank(tasks, now=NOW)
    assert [t["task_no"] for t, _ in ranked] == ["b", "c", "a"]


def test_rank_uses_device_online_and_agent_load():
    tasks = [
        _task(task_no="offline", priority=8, assigned_device="dev-x"),
        _task(task_no="online", priority=4, assigned_device="dev-y"),
    ]
    ranked = scorer.rank(
        tasks, now=NOW,
        online_of=lambda device: device != "dev-x",
        load_of=lambda agent: 0.0,
    )
    # priority 8 的离线任务被 0.1 的在线惩罚拉下来了吗？没有——8 分仍领先，说明权重合理
    assert ranked[0][0]["task_no"] == "offline"

    tasks[0]["priority"] = 4
    ranked = scorer.rank(
        tasks, now=NOW,
        online_of=lambda device: device != "dev-x",
    )
    assert ranked[0][0]["task_no"] == "online"


def test_score_is_two_decimals_for_decimal_column():
    value = scorer.score_task(_task(priority=7), now=NOW, agent_load=0.33)
    assert value == round(value, 2)
