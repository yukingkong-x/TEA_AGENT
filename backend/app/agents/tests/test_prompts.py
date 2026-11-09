"""REQ-F-002 Agent 团队定义契约测试(PRD 8.1 编制总表 + 8.2 提示词 + 6.3 表结构)。"""
import json

import pytest

from app.agents.prompts import AGENTS, to_db_rows

# 手抄 PRD 8.1 总表,逐字段核对(期望值独立于被测代码)
EXPECTED = {
    "scout": ("巡园管家", 0.3, ["get_env_status", "get_soil_status", "raise_alert"]),
    "weather": ("气象员", 0.3, ["get_weather"]),
    "soil": ("土壤师", 0.3, ["get_soil_status"]),
    "pest": ("植保员", 0.4, ["query_knowledge"]),
    "decision": ("灌溉决策官", 0.2, ["create_task"]),
    "executor": ("执行管家", 0.2, ["send_device_cmd", "raise_alert"]),
    "verifier": ("验证审计官", 0.3,
                 ["verify_result", "calc_achievement", "write_report", "create_task", "raise_alert"]),
}


def test_seven_agents_match_prd_81_table():
    # 断点:8.1 表任一字段(名字/温度/工具绑定)被改错,或 Agent 数量不对 → 本测试失败
    assert set(AGENTS) == set(EXPECTED)
    for key, (name, temperature, tools) in EXPECTED.items():
        spec = AGENTS[key]
        assert spec.agent_key == key
        assert spec.name == name
        assert spec.temperature == temperature
        assert spec.tools == tools
        assert spec.avatar  # 头像 emoji 非空(前端依赖)
        assert len(spec.system_prompt) > 100  # 8.2 全文未被截断


def test_send_device_cmd_bound_only_to_executor():
    # 断点:权限铁律被破坏(send_device_cmd 出现在其他 Agent 的绑定里)→ 本测试失败
    holders = [key for key, spec in AGENTS.items() if "send_device_cmd" in spec.tools]
    assert holders == ["executor"]


@pytest.mark.parametrize("key,anchor", [
    ("scout", "【巡园播报】"),
    ("weather", "【气象评估】"),
    ("soil", "【墒情报告】"),
    ("pest", "【植保核查】"),
    ("decision", "【决策】"),
    ("executor", "【执行反馈】"),
    ("verifier", "【验证报告】"),
])
def test_prompts_carry_output_format_anchors(key, anchor):
    # 断点:8.2 提示词被误改/截断导致输出格式锚点丢失 → 本测试失败
    assert anchor in AGENTS[key].system_prompt


def test_decision_and_verifier_carry_role_rules():
    # 断点:决策/验证的人设铁律句被删改 → 本测试失败
    assert "唯一有权拍板" in AGENTS["decision"].system_prompt
    assert "你是平台的公信力所在" in AGENTS["verifier"].system_prompt


def test_to_db_rows_matches_agents_table_contract():
    # 断点:首启写入 agents 表(PRD 6.3)的字段名/类型不对 → 本测试失败
    rows = to_db_rows()
    assert len(rows) == 7
    by_key = {r["agent_key"]: r for r in rows}
    scout = by_key["scout"]
    assert scout["name"] == "巡园管家"
    assert scout["avatar"]
    assert isinstance(scout["tools_json"], str)
    assert json.loads(scout["tools_json"]) == ["get_env_status", "get_soil_status", "raise_alert"]
    assert scout["temperature"] == 0.3
    assert scout["model"] is None  # 默认取全局配置
    assert scout["enabled"] is True
