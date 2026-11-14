"""熔断器（PRD 10.4）：3 次连续失败 → 300s；到期自动解除；成功清零。"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.orchestrator.breaker import Breaker

NOW = datetime(2026, 11, 14, 10, 0, 0)


def test_opens_on_third_consecutive_failure():
    breaker = Breaker(threshold=3, open_seconds=300)
    assert breaker.record_failure("dev-1", NOW) is False
    assert breaker.record_failure("dev-1", NOW) is False
    assert breaker.record_failure("dev-1", NOW) is True       # 第三次触发
    assert breaker.is_open("dev-1", NOW)


def test_does_not_reopen_while_already_open():
    breaker = Breaker(threshold=2, open_seconds=300)
    breaker.record_failure("dev-1", NOW)
    assert breaker.record_failure("dev-1", NOW) is True
    # 熔断期内继续失败，不应该重复触发报警
    assert breaker.record_failure("dev-1", NOW) is False


def test_success_resets_counter():
    breaker = Breaker(threshold=3, open_seconds=300)
    breaker.record_failure("dev-1", NOW)
    breaker.record_failure("dev-1", NOW)
    assert breaker.record_success("dev-1") is False
    breaker.record_failure("dev-1", NOW)
    assert not breaker.is_open("dev-1", NOW)                  # 只算 1 次连续失败


def test_auto_close_after_window():
    breaker = Breaker(threshold=1, open_seconds=300)
    breaker.record_failure("dev-1", NOW)
    assert breaker.is_open("dev-1", NOW)
    assert breaker.is_open("dev-1", NOW + timedelta(seconds=299))
    assert not breaker.is_open("dev-1", NOW + timedelta(seconds=301))
    assert breaker.snapshot()["dev-1"] == {"failures": 0, "open": False}


def test_remaining_seconds_counts_down():
    breaker = Breaker(threshold=1, open_seconds=300)
    breaker.record_failure("dev-1", NOW)
    assert breaker.remaining_seconds("dev-1", NOW) == 300
    assert breaker.remaining_seconds("dev-1", NOW + timedelta(seconds=120)) == 180
    assert breaker.remaining_seconds("dev-1", NOW + timedelta(seconds=400)) == 0


def test_manual_reset():
    breaker = Breaker(threshold=1, open_seconds=300)
    breaker.record_failure("dev-1", NOW)
    breaker.reset("dev-1")
    assert not breaker.is_open("dev-1", NOW)
    assert breaker.record_failure("dev-1", NOW) is True       # 重新计一次就熔断


def test_devices_are_isolated():
    breaker = Breaker(threshold=1, open_seconds=300)
    breaker.record_failure("dev-1", NOW)
    assert breaker.is_open("dev-1", NOW)
    assert not breaker.is_open("dev-2", NOW)


def test_open_devices_lists_only_open_with_remaining():
    breaker = Breaker(threshold=1, open_seconds=300)
    breaker.record_failure("dev-1", NOW)
    breaker.record_failure("dev-2", NOW + timedelta(seconds=400))
    opened = breaker.open_devices(NOW + timedelta(seconds=401))
    assert "dev-1" not in opened            # 早就过期自动解除
    assert opened["dev-2"] == 299


def test_empty_device_is_ignored():
    breaker = Breaker(threshold=1)
    assert breaker.record_failure("", NOW) is False
    assert not breaker.is_open("", NOW)


def test_invalid_construction():
    import pytest

    with pytest.raises(ValueError):
        Breaker(threshold=0)
    with pytest.raises(ValueError):
        Breaker(open_seconds=-1)
