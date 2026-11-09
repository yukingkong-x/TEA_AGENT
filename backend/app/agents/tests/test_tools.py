"""REQ-F-003 工具池单元测试(PRD 7.3 + 11.1 达成率公式 + 12.3 Mock 天气)。"""
import asyncio

import pytest

from app.agents.prompts import AGENTS
from app.agents.tools import (
    ToolNotReady,
    ToolRegistry,
    build_default_registry,
    calc_achievement,
    get_weather,
    set_weather_profile,
)

# 手抄 PRD 7.3 工具池全表 + 9.2 工作流工具 wait_penetration
PRD_TOOL_NAMES = {
    "get_weather", "get_soil_status", "get_env_status", "query_knowledge",
    "create_task", "send_device_cmd", "verify_result", "calc_achievement",
    "write_report", "raise_alert", "wait_penetration",
}

# 11.13 前依赖他人地盘、尚未接入的工具(到各自 REQ 落地后应从本表移除)
UNWIRED = {
    "get_soil_status", "get_env_status",   # 队友 B 数据源适配层(REQ-F-019)
    "query_knowledge",                     # REQ-F-020 知识库
    "create_task",                         # REQ-F-014 调度器
    "send_device_cmd",                     # devices/command.py + REQ-F-014
    "verify_result",                       # REQ-F-016 验证引擎
    "write_report",                        # REQ-F-022 报告后端
    "raise_alert",                         # 队友 B alerts 表 + WS
}


def test_all_prd_tools_are_registered():
    # 断点:工具池漏注册/改名(与 7.3 契约不一致)→ 本测试失败
    registry = build_default_registry()
    assert set(registry.names()) == PRD_TOOL_NAMES


def test_permission_whitelist_enforced():
    # 断点:白名单检查被绕开(任何 Agent 都能调 send_device_cmd)→ 本测试失败
    registry = build_default_registry()
    assert registry.can_use("executor", "send_device_cmd") is True
    assert registry.can_use("decision", "send_device_cmd") is False
    assert registry.can_use("scout", "send_device_cmd") is False
    assert registry.can_use("scout", "get_soil_status") is True
    assert registry.can_use("scout", "不存在的工具") is False
    assert registry.can_use("不存在的agent", "get_weather") is False


@pytest.mark.parametrize("baseline,target_low,target_high,measured,want", [
    # PRD 11.1 五边界 + 公式示例(期望值手算,与代码无关)
    (38.5, 55, 65, 45.0, 39.39),   # 未达标折算 (45-38.5)/(55-38.5)=39.3939…
    (38.5, 55, 65, 55.0, 100.0),   # M = L 恰好达标
    (38.5, 55, 65, 57.0, 100.0),   # M 在区间内
    (38.5, 55, 65, 70.0, 100.0),   # M > H 过浇按 100
    (38.5, 55, 65, 30.0, 0.0),     # M < B 浇了没升,封底为 0
])
def test_calc_achievement_five_boundaries(baseline, target_low, target_high, measured, want):
    # 断点:达成率公式被改错(折算/封顶/取整)→ 对应用例失败
    got = calc_achievement(baseline, target_low, target_high, measured)
    assert got == pytest.approx(want, abs=0.005)


def test_calc_achievement_rejects_invalid_range():
    # 断点:target_low <= baseline 的非法输入不设防(除零)→ 本测试失败
    with pytest.raises(ValueError):
        calc_achievement(60.0, 55.0, 65.0, 50.0)


def test_unwired_tools_raise_clear_tool_not_ready():
    # 断点:未接入工具被静默实现成假数据(蒙混过关)→ 本测试失败
    registry = build_default_registry()
    for name in UNWIRED:
        with pytest.raises(ToolNotReady, match=name):
            asyncio.run(registry.invoke(name, {}))


def test_get_weather_defaults_to_sunny_and_switches_profile():
    # 断点:12.3 档位表/默认值被改错 → 本测试失败
    try:
        default = get_weather("杭州", hours=12)
        assert default["city"] == "杭州"
        assert default["hours"] == 12
        assert default["temp_range"] == [14, 26]
        assert default["rain_prob"] == 10
        assert default["frost_risk"] is False

        set_weather_profile("rainy")
        rainy = get_weather("杭州")
        assert rainy["rain_prob"] == 70

        set_weather_profile("frost")
        frost = get_weather("杭州")
        assert frost["frost_risk"] is True
        assert frost["temp_range"][0] < 4  # 触发霜冻预警的档位
    finally:
        set_weather_profile("sunny")


def test_invoke_runs_sync_and_async_functions():
    # 断点:invoke 不能正确执行注册函数(同步/异步)→ 本测试失败
    registry = ToolRegistry(bindings=AGENTS)
    calls = []
    registry.register("echo_sync", "回显", {"type": "object", "properties": {"text": {"type": "string"}}},
                      lambda text: calls.append(text) or f"sync:{text}")

    async def slow_echo(text):
        await asyncio.sleep(0.001)
        return f"async:{text}"

    registry.register("echo_async", "回显", {"type": "object", "properties": {"text": {"type": "string"}}},
                      slow_echo)

    assert asyncio.run(registry.invoke("echo_sync", {"text": "hi"})) == "sync:hi"
    assert asyncio.run(registry.invoke("echo_async", {"text": "hi"})) == "async:hi"
    assert calls == ["hi"]


def test_openai_schemas_have_function_shape():
    # 断点:给 openai SDK 的 tools 参数结构不对(type/function/parameters)→ 本测试失败
    registry = build_default_registry()
    schemas = registry.to_openai_schemas()
    assert len(schemas) == len(PRD_TOOL_NAMES)
    names = []
    for s in schemas:
        assert s["type"] == "function"
        fn = s["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert "properties" in fn["parameters"]
        names.append(fn["name"])
    assert set(names) == PRD_TOOL_NAMES
