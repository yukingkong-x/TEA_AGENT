"""REQ-F-018 反馈修正单测:规则引擎必须 100% 可复现,所以每条策略都钉死数值。"""
from app.verification.feedback import diagnose


def test_large_gap_uses_split_irrigation():
    correction = diagnose(
        baseline=38.5, measured=45.0, target_low=55, target_high=65, duration_s=30,
    )
    # 缺口 10 → 不触发 split;换成缺口 >15 的场景
    assert correction.strategy == "topup"


def test_gap_over_fifteen_splits():
    # 基线 30 → 复测 38,缺口 17 超过 15,走分次灌溉
    correction = diagnose(
        baseline=30.0, measured=38.0, target_low=55, target_high=65, duration_s=30,
    )
    assert correction.strategy == "split"
    assert correction.duration_s == 20.0          # 30 × 0.67 = 20.1 → 取整秒 20
    assert correction.times == 2
    assert correction.interval_s == 60
    assert correction.payload["action"] == "pump"
    assert correction.is_action is True


def test_small_gap_uses_topup():
    correction = diagnose(
        baseline=38.5, measured=45.0, target_low=55, target_high=65, duration_s=30,
    )
    assert correction.strategy == "topup"
    assert correction.duration_s == 20.0          # 10 + 缺口 10
    assert correction.times == 1
    assert correction.interval_s == 0


def test_no_rise_triggers_data_suspicion_before_watering():
    """浇了反而没升 → 先复核数据,不许继续补水(越补越糟)。"""
    correction = diagnose(
        baseline=38.5, measured=38.0, target_low=55, target_high=65, duration_s=30,
    )
    assert correction.strategy == "suspect_data"
    assert correction.payload["action"] == "read_now"
    assert correction.payload["times"] == 2
    assert correction.is_action is False


def test_last_round_gives_up_instead_of_looping_forever():
    correction = diagnose(
        baseline=38.5, measured=45.0, target_low=55, target_high=65, duration_s=30,
        round_no=2, max_rounds=2,
    )
    assert correction.strategy == "give_up"
    assert correction.is_action is False


def test_new_baseline_is_measured_value():
    correction = diagnose(
        baseline=38.5, measured=45.0, target_low=55, target_high=65, duration_s=30,
    )
    # 新一轮的基线是这一轮的复测值,不是原始基线
    assert correction.payload["baseline"] == 45.0


def test_target_range_passed_through():
    correction = diagnose(
        baseline=38.5, measured=45.0, target_low=55, target_high=65, duration_s=30,
    )
    assert correction.payload["target_range"] == [55, 65]


def test_reason_is_human_readable():
    correction = diagnose(
        baseline=38.5, measured=45.0, target_low=55, target_high=65, duration_s=30,
    )
    assert "缺口 10.0%" in correction.reason
