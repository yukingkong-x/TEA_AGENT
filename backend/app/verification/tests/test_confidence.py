"""REQ-F-017 三路置信度单测。每一条扣分都要留下人能读懂的理由(报告页要用)。"""
import pytest

from app.verification.confidence import Evidence, compute


def ideal() -> Evidence:
    """理想复测:在线、3 次稳定、无跳变、浇水后上升、速率合理、无历史分布。"""
    return Evidence(samples=[56.8, 57.0, 57.2], baseline=45.0, duration_s=30)


def test_measured_is_median_not_mean():
    assert Evidence(samples=[40, 60, 50], baseline=30, duration_s=30).measured == 50


def test_ideal_evidence_reaches_full_confidence():
    result = compute(ideal())
    assert result.total == 1.0
    assert result.reasons == []


def test_offline_device_costs_four_tenths():
    evidence = ideal()
    evidence.device_online = False
    result = compute(evidence)
    assert result.data_quality == 0.6
    assert result.total == 0.8
    assert any("离线" in reason for reason in result.reasons)


def test_large_spread_decays_data_quality():
    result = compute(Evidence(samples=[50, 57, 65], baseline=45, duration_s=30))
    assert result.data_quality < 0.8
    assert any("抖动" in reason for reason in result.reasons)


def test_single_sample_is_penalised():
    result = compute(Evidence(samples=[57], baseline=45, duration_s=30))
    assert any("只有 1 个" in reason for reason in result.reasons)


def test_jump_from_previous_point_is_penalised():
    result = compute(Evidence(samples=[57, 57, 57], baseline=45, duration_s=30, previous_value=30))
    assert result.data_quality == 0.8
    assert any("跳变" in reason for reason in result.reasons)


def test_no_rise_penalises_rule_cross():
    result = compute(Evidence(samples=[45, 45, 45], baseline=45, duration_s=30))
    assert result.rule_cross == 0.25          # 物理 0,速率 0.5 → 平均 0.25
    assert any("未上升" in reason for reason in result.reasons)


def test_rate_out_of_band_gets_half():
    result = compute(Evidence(samples=[45.3, 45.3, 45.3], baseline=45, duration_s=30))
    assert result.rule_cross == 0.75
    assert any("单位时间提升量" in reason for reason in result.reasons)


def test_history_deviation_decays_consistency():
    result = compute(Evidence(
        samples=[57, 57, 57], baseline=45, duration_s=30,
        history_mean=30, history_sigma=5,
    ))
    # 偏差 27,超 3σ=15 → 1 − (27−15)/15 = 0.2
    assert result.consistency == pytest.approx(0.2)
    assert any("偏离" in reason for reason in result.reasons)


def test_no_history_distribution_does_not_fabricate_penalty():
    assert compute(ideal()).consistency == 1.0


def test_empty_samples_is_low_confidence():
    result = compute(Evidence(samples=[], baseline=45, duration_s=30))
    assert result.total == 0.0
    assert result.low is True
    assert any("没有复测读数" in reason for reason in result.reasons)


def test_bad_case_falls_below_human_threshold():
    """PRD 11.5 验收:人为制造抖动+离线,必须能触发转人工。"""
    result = compute(Evidence(
        samples=[40, 42], baseline=45, duration_s=30, device_online=False, previous_value=20,
    ))
    # 离线 + 读数不足 3 个 + 跳变 → 数据质量 0.2;浇水后没升 → 规则交叉 0.25
    assert result.total < 0.6
    assert result.low is True
