"""REQ-F-016 达成率单测:覆盖 PRD 11.5 点名的 5 个边界(M<H、M=L、M∈区间、M>H、M<B)。"""
import pytest

from app.verification.achievement import compute


def test_measured_in_range_gives_100():
    result = compute(baseline=38.5, target_low=55, target_high=65, measured=57.0)
    assert result.value == 100.0
    assert result.over_irrigated is False
    assert result.gap == 0.0


def test_measured_on_lower_bound_gives_100():
    result = compute(baseline=38.5, target_low=55, target_high=65, measured=55.0)
    assert result.value == 100.0
    assert result.gap == 0.0


def test_measured_above_high_flags_over_irrigated():
    result = compute(baseline=38.5, target_low=55, target_high=65, measured=72.0)
    assert result.value == 100.0
    assert result.over_irrigated is True


def test_prd_example_39_39():
    # PRD 11.1 原文示例:B=38.5, L=55, M=45.0 → 39.39%
    result = compute(baseline=38.5, target_low=55, target_high=65, measured=45.0)
    assert result.value == 39.39
    assert result.gap == 10.0
    assert result.over_irrigated is False


def test_measured_below_baseline_clamped_to_zero():
    result = compute(baseline=38.5, target_low=55, target_high=65, measured=30.0)
    assert result.value == 0.0
    assert result.gap == 25.0


def test_baseline_already_in_range_does_not_divide_by_zero():
    # 基线已经 ≥ 目标下限:本轮本不该浇水,记 100 而不是抛 ZeroDivisionError
    result = compute(baseline=60.0, target_low=55, target_high=65, measured=50.0)
    assert result.value == 100.0
    assert result.baseline_in_range is True
    # 复测值落在区间内时按正常路径走,不应误标 in_range
    assert compute(baseline=60.0, target_low=55, target_high=65, measured=56.0).baseline_in_range is False


def test_baseline_equals_low_is_treated_as_in_range():
    result = compute(baseline=55.0, target_low=55, target_high=65, measured=50.0)
    assert result.value == 100.0
    assert result.baseline_in_range is True


def test_invalid_target_range_rejected():
    with pytest.raises(ValueError, match="必须小于"):
        compute(baseline=30, target_low=65, target_high=55, measured=60)


@pytest.mark.parametrize("measured,expected", [(40.0, 9.09), (50.0, 69.7), (54.9, 99.39)])
def test_monotonic_between_baseline_and_low(measured, expected):
    result = compute(baseline=38.5, target_low=55, target_high=65, measured=measured)
    assert result.value == expected


def test_matches_llm_tool_formula():
    """工具层的 calc_achievement 给 LLM 用,数值口径必须和引擎一致。"""
    from app.agents.tools import calc_achievement

    for baseline, low, high, measured in [
        (38.5, 55, 65, 45.0), (38.5, 55, 65, 57.0), (30, 50, 60, 61.0), (20, 50, 60, 35.0),
    ]:
        assert calc_achievement(baseline, low, high, measured) == compute(
            baseline, low, high, measured
        ).value
