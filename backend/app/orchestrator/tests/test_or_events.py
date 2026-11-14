"""任务轨迹事件的拼装与去重（REQ-F-015）。

轨迹抽屉的体验取决于两个判断：**哪些事件值得留一行**、**哪些是同一件事的重复**。
这两个判断都在这里，所以能脱离数据库直接测。
"""
import json

from app.orchestrator import events as E


def test_status_event_maps_from_to_reason():
    row = E.from_task_status({
        "task_no": "task-20261114-0007", "run_id": 12, "from": "pending", "to": "dispatched",
        "reason": "dispatch", "retry_count": 0, "score": 0.71,
        "assigned_agent": "executor", "assigned_device": "k10-act-03",
    })
    assert (row["from_status"], row["to_status"]) == ("pending", "dispatched")
    assert row["reason"] == "dispatch"
    assert row["actor"] == "scheduler"
    assert row["event"] == E.EVENT_TASK_STATUS
    # 整条事件都留在 payload 里，抽屉展开能看到分数与设备
    assert row["payload_json"]["score"] == 0.71
    assert row["payload_json"]["assigned_device"] == "k10-act-03"


def test_breaker_rejection_keeps_retry_after():
    """熔断拒绝的「剩余 Ns」在 result 里，抽屉要读得到，所以提到 payload 顶层。"""
    row = E.from_task_status({
        "task_no": "t1", "from": "pending", "to": "dead", "reason": "breaker_open",
        "result": {"rejected": "breaker_open", "retry_after_s": 42},
    })
    assert row["payload_json"]["rejected"] == "breaker_open"
    assert row["payload_json"]["retry_after_s"] == 42


def test_missing_task_no_yields_empty_and_caller_skips():
    assert E.from_task_status({"from": "pending", "to": "dispatched"})["task_no"] == ""


def test_duplicate_is_same_event_not_same_payload():
    """挂起等设备时每 tick 发一条 retrying→retrying，retry_count 不变，
    但 `updated_at` 会变——后者不算新事件。"""
    first = E.build(task_no="t1", from_status="retrying", to_status="retrying",
                    reason="retry_hold_offline")
    again = E.build(task_no="t1", from_status="retrying", to_status="retrying",
                    reason="retry_hold_offline", payload={"retry_count": 2})
    assert E.is_duplicate(first, again) is True

    # 状态或原因变了就是新事件
    moved = E.build(task_no="t1", from_status="retrying", to_status="pending",
                    reason="retry_due")
    assert E.is_duplicate(first, moved) is False


def test_duplicate_respects_task_boundary():
    a = E.build(task_no="t1", from_status="pending", to_status="dispatched")
    b = E.build(task_no="t2", from_status="pending", to_status="dispatched")
    assert E.is_duplicate(a, b) is False
    assert E.is_duplicate(None, a) is False           # 首行永远不是重复


def test_oversized_payload_keeps_whitelist_only():
    row = E.build(
        task_no="t1", from_status="running", to_status="failed", reason="timeout_60s",
        payload={"task_no": "t1", "from": "running", "to": "failed", "reason": "timeout_60s",
                 "retry_count": 1, "result": {"output": "长" * 5000}},
    )
    body = row["payload_json"]
    assert body["_truncated"] is True
    assert body["reason"] == "timeout_60s"
    assert "result" not in body                       # 长文本在 agent_messages 里，不进轨迹
    assert len(json.dumps(body, ensure_ascii=False)) < E.MAX_PAYLOAD_CHARS


def test_small_payload_is_untouched():
    payload = {"task_no": "t1", "reason": "dispatch"}
    assert E.build(task_no="t1", payload=payload)["payload_json"] == payload


def test_empty_payload_is_none_not_empty_dict():
    """JSON 列存 `{}` 和 `null` 在列表渲染里表现不同，统一成 null。"""
    assert E.build(task_no="t1", payload={})["payload_json"] is None
    assert E.build(task_no="t1", payload=None)["payload_json"] is None


def test_run_id_string_is_coerced():
    assert E.build(task_no="t1", run_id="12")["run_id"] == 12
    assert E.build(task_no="t1", run_id=None)["run_id"] is None
