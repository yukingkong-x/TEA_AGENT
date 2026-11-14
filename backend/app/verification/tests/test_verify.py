"""验证引擎组合层 + 报告渲染单测。

核心场景直接抄 PRD 11.5 的验收条目:
「第 1 轮 M=45(39.39%)→ 修正 → 第 2 轮 M=57(100%),报告页完整呈现两轮对照」
"""
from app.verification.report import ReportData, RoundView, render_report
from app.verification.verify import verify

TARGET = {"target_low": 55.0, "target_high": 65.0}


def test_prd_two_round_scenario():
    first = verify(samples=[44.8, 45.0, 45.2], baseline=38.5, duration_s=30, round_no=1, **TARGET)
    assert first.achievement.value == 39.39
    assert first.verdict == "failed"
    assert first.correction is not None and first.correction.strategy == "topup"
    assert first.correction.duration_s == 20.0

    second = verify(samples=[56.9, 57.0, 57.1], baseline=45.0, duration_s=20, round_no=2, **TARGET)
    assert second.achievement.value == 100.0
    assert second.verdict == "success"
    assert second.correction is None


def test_low_confidence_goes_to_human_even_if_achievement_is_good():
    """达成率 100% 但证据不可信(单点读数 + 设备离线 + 偏离 24h 均值)→ 必须转人工。"""
    result = verify(
        samples=[57], baseline=45, duration_s=30, device_online=False,
        history_mean=10, history_sigma=2, round_no=1, **TARGET,
    )
    assert result.achievement.value == 100.0
    assert result.verdict == "needs_human"
    assert result.confidence.low is True
    assert "置信度" in result.note


def test_second_round_failure_escalates_to_human():
    result = verify(samples=[44, 45, 46], baseline=38.5, duration_s=30, round_no=2, **TARGET)
    assert result.achievement.value < 60
    assert result.verdict == "needs_human"
    assert "2 轮" in result.note
    assert result.correction is None            # 不再生成修正,防止无限循环


def test_first_round_failure_triggers_correction():
    result = verify(samples=[44, 45, 46], baseline=38.5, duration_s=30, round_no=1, **TARGET)
    assert result.verdict == "failed"
    assert result.correction is not None
    assert result.correction.is_action is True


def test_over_irrigation_is_success_with_warning():
    result = verify(samples=[72, 72, 72], baseline=38.5, duration_s=30, round_no=1, **TARGET)
    assert result.verdict == "success"
    assert result.achievement.over_irrigated is True
    assert "过" in result.note


def test_no_rise_does_not_keep_watering():
    """浇了没升 → needs_human + 复核建议,绝不能又下发一次 pump。"""
    result = verify(samples=[38, 38, 38], baseline=38.5, duration_s=30, round_no=1, **TARGET)
    assert result.verdict == "needs_human"
    assert result.correction is not None
    assert result.correction.strategy == "suspect_data"
    assert result.correction.is_action is False


def test_summary_is_one_line_for_db():
    result = verify(samples=[57, 57, 57], baseline=45, duration_s=30, round_no=1, **TARGET)
    summary = result.summary()
    assert "第 1 轮" in summary and "100.00%" in summary and "success" in summary


def test_report_renders_evidence_chain():
    data = ReportData(
        run_id=12,
        started_at="2026-11-14 10:12:33",
        finished_at="2026-11-14 10:16:01",
        outcome="success",
        rounds=[
            RoundView(round_no=1, baseline=38.5, measured=45.0, achievement=39.39,
                      confidence=1.0, verdict="failed", duration_s=30,
                      note="缺口 10.0% 在 15 以内,单次补灌 20.0s"),
            RoundView(round_no=2, baseline=45.0, measured=57.0, achievement=100.0,
                      confidence=0.93, verdict="success", duration_s=20),
        ],
        timeline=[{"ts": "10:12:40", "name": "巡园播报", "event": "node_finished",
                   "status": "done", "duration_ms": 1200}],
        confidence_reasons=["单位时间提升量 1.33%/s 不在 0.1-1.0 区间(规则交叉 0.5)"],
    )
    markdown = render_report(data)

    assert "# 巡园浇水工作流 · 执行报告" in markdown
    assert "run #12" in markdown
    assert "闭环成功" in markdown
    # 证据链:两轮对照 + 诊断 + 达成率数值都要在
    assert "第 1 轮" in markdown and "第 2 轮" in markdown
    assert "39.39" in markdown and "100.00" in markdown
    assert "## 三、诊断与修正" in markdown
    assert "单次补灌 20.0s" in markdown
    assert "巡园播报" in markdown
    assert "规则交叉 0.5" in markdown


def test_report_without_rounds_is_still_renderable():
    markdown = render_report(ReportData(run_id=1, outcome="running"))
    assert "尚未产生验证结果" in markdown
    assert "结论" in markdown
