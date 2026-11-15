"""PRD 20.2 规则降级模板测试(REQ-F-001 的一部分:断网时用固定模板保证流程不断)。"""
import pytest

from app.agents.fallback import (
    DEGRADED_PREFIX,
    decision_fallback,
    generic_fallback,
    scout_fallback,
)

ENV = {"temperature_c": 24.6, "humidity_air": 63.2, "lux": 1250}
SOIL = {"soil_moisture": 38.5, "updated_at": "2026-11-09 14:30", "trend": "平"}


def test_scout_fallback_splices_live_data_without_llm():
    # 断点:降级模板不再拼接真实数据(纯代码路径被破坏)→ 本测试失败
    text = scout_fallback(ENV, SOIL, now_text="14:30")
    assert "【巡园播报】" in text
    assert "14:30" in text
    assert "气温24.6℃" in text
    assert "空气湿度63.2%" in text
    assert "光照1250lux" in text
    assert "土壤湿度38.5%" in text
    assert "趋势:平" in text


@pytest.mark.parametrize("moisture,rain,frost,want", [
    (25.0, False, False, "irrigate"),   # 缺水且无预警 → 浇水 30s
    (50.0, False, False, "none"),       # 不缺水 → 无需作业
    (25.0, True, False, "none"),        # 有降雨预警 → 暂缓
    (25.0, False, True, "none"),        # 有霜冻预警 → 暂缓
])
def test_decision_fallback_hardcoded_tree(moisture, rain, frost, want):
    # 断点:硬编码决策树阈值/条件被改错 → 本测试失败
    text = decision_fallback(moisture, has_rain_alert=rain, has_frost_alert=frost)
    assert want in text
    if want == "irrigate":
        assert "30" in text


def test_generic_fallback_marks_degraded_output():
    # 断点:其他 Agent 降级时没有明确标注(界面上看不出降级)→ 本测试失败
    text = generic_fallback("weather")
    assert "气象员" in text
    assert "规则模板" in text


def test_degraded_prefix_is_a_visible_marker():
    # 断点:降级标记前缀被改丢(前端无法识别"模型降级中"徽章)→ 本测试失败
    assert "模型降级" in DEGRADED_PREFIX
