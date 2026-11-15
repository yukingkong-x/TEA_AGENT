"""任务状态机：合法边、终态、非法流转必须炸。"""
from __future__ import annotations

import pytest

from app.orchestrator import state


def test_all_prd_statuses_exist():
    for status in ("pending", "dispatched", "running", "success", "failed",
                   "timeout", "retrying", "dead", "needs_human", "canceled"):
        assert status in state.STATUSES


def test_happy_path_is_allowed():
    path = ["pending", "dispatched", "running", "success"]
    for source, target in zip(path, path[1:]):
        assert state.can_transition(source, target)


def test_retry_loop_is_allowed():
    assert state.can_transition("timeout", "retrying")
    assert state.can_transition("retrying", "pending")
    assert state.can_transition("failed", "retrying")


def test_terminal_states_never_leave():
    for status in ("success", "dead", "canceled"):
        assert state.is_terminal(status)
        for target in state.STATUSES:
            assert not state.can_transition(status, target)


def test_cannot_go_back_from_success():
    with pytest.raises(state.IllegalTransition):
        state.ensure_transition("task-1", "success", "pending")


def test_unknown_status_is_rejected():
    assert not state.can_transition("weird", "pending")
    with pytest.raises(state.IllegalTransition):
        state.ensure_transition("task-2", "weird", "pending")


def test_needs_human_can_be_resolved_by_human():
    assert state.can_transition("needs_human", "success")
    assert state.can_transition("needs_human", "canceled")
    assert state.is_terminal("needs_human")


def test_active_and_retryable_classification():
    assert state.is_active("dispatched") and state.is_active("running")
    assert not state.is_active("pending")
    assert state.is_retryable("failed") and state.is_retryable("timeout")
    assert not state.is_retryable("retrying")
