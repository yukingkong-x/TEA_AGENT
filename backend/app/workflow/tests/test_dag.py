"""REQ-F-004 DAG 校验单测。

断点清单:
1. PRD 9.1 的默认工作流必须通过校验(文档即测试:PRD 改了没同步,fail);
2. 环图必须被拦住(画布拖出环就把库写脏);
3. loop 的结构豁免(无入边)必须容忍,否则画布一放 loop 就存不下;
4. 表达式沙箱必须挡住函数调用(PRD 9.2:禁 eval)。
"""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.workflow.dag import validate_dag
from app.workflow.default_dag import default_dag

AGENT_KEYS = {"scout", "weather", "soil", "pest", "decision", "executor", "verifier"}
TOOL_NAMES = {"get_weather", "get_soil_status", "get_env_status", "query_knowledge",
              "create_task", "send_device_cmd", "verify_result", "calc_achievement",
              "write_report", "raise_alert", "wait_penetration"}

REPO_ROOT = Path(__file__).resolve().parents[4]
PRD = REPO_ROOT / "PRD_茶园多智能体平台_需求文档_v1.md"


def prd_default_dag() -> dict:
    """PRD 9.1 的默认工作流。定义已收进生产代码（首启写库用），这里只做别名。"""
    return default_dag()


def check(dag: dict) -> list[str]:
    return validate_dag(dag, AGENT_KEYS, TOOL_NAMES)


def test_prd_json_block_parses_and_passes():
    """文档即测试:PRD 9.1 那段 JSON 必须能被标准解析器读,且通过校验。"""
    text = PRD.read_text(encoding="utf-8")
    section = text[text.index("# 9. 工作流引擎规格"):]
    start = section.index("```json") + len("```json")
    raw = section[start:section.index("```", start)]
    dag = json.loads(raw)  # 尾逗号会在这里直接炸
    assert dag.get("edges") == []
    assert validate_dag(dag, AGENT_KEYS, TOOL_NAMES) == []


def test_fixture_matches_prd():
    """fixture 与 PRD 漂移保护:两边节点连线不一致就 fail。"""
    text = PRD.read_text(encoding="utf-8")
    section = text[text.index("# 9. 工作流引擎规格"):]
    start = section.index("```json") + len("```json")
    dag = json.loads(section[start:section.index("```", start)])
    strip = lambda nodes: [
        (n["id"], n.get("type"), n.get("next"), n.get("body_next")) for n in nodes
    ]
    assert strip(dag["nodes"]) == strip(prd_default_dag()["nodes"])


def test_prd_default_dag_passes():
    assert check(prd_default_dag()) == []


def test_prd_default_dag_passes_without_known_agents():
    # 首启 agents 表还没写时,后端不传白名单,不能因此拒存
    assert validate_dag(prd_default_dag()) == []


def test_loop_without_inbound_is_tolerated():
    """旧形态(PRD 修订前):n11.next=[n13]、n11b 无入边 —— 画布上先放 loop 再连线是常态。"""
    dag = prd_default_dag()
    for node in dag["nodes"]:
        if node["id"] == "n11":
            node["next"] = ["n13"]
    assert check(dag) == []


def test_two_starts_rejected():
    dag = prd_default_dag()
    dag["nodes"].append({"id": "n0", "type": "start", "name": "另一个开始", "next": ["n13"]})
    errors = check(dag)
    assert any("只有一个 start" in e for e in errors)


def test_duplicate_id_rejected():
    dag = prd_default_dag()
    dag["nodes"].append({"id": "n13", "type": "end", "name": "重复"})
    assert any("id 重复" in e for e in check(dag))


def test_dangling_reference_rejected():
    dag = prd_default_dag()
    dag["nodes"][0]["next"] = ["n404"]
    assert any("不存在的节点 n404" in e for e in check(dag))


def test_cycle_rejected():
    dag = {
        "nodes": [
            {"id": "s", "type": "start", "name": "开始", "next": ["a"]},
            {"id": "a", "type": "agent", "agent_key": "scout", "name": "A", "next": ["b"]},
            {"id": "b", "type": "agent", "agent_key": "soil", "name": "B", "next": ["a"]},
            {"id": "e", "type": "end", "name": "结束"},
        ]
    }
    assert any("检测到环" in e for e in check(dag))


def test_unreachable_node_rejected():
    dag = prd_default_dag()
    dag["nodes"].append({"id": "n99", "type": "agent", "agent_key": "pest",
                         "name": "孤岛", "next": []})
    errors = check(dag)
    assert any("不可达" in e and "n99" in e for e in errors)


def test_condition_needs_both_branches():
    dag = prd_default_dag()
    for node in dag["nodes"]:
        if node["id"] == "n8":
            node["branches"] = {"true": ["n9"]}
    assert any("branches.false" in e for e in check(dag))


def test_condition_rejects_function_call():
    """PRD 9.2:表达式沙箱禁 eval,函数调用必须挡在保存前。"""
    dag = prd_default_dag()
    for node in dag["nodes"]:
        if node["id"] == "n8":
            node["expression"] = "__import__('os').system('rm -rf /') == 0"
    assert any("不允许的语法 Call" in e for e in check(dag))


def test_condition_rejects_syntax_error():
    dag = prd_default_dag()
    for node in dag["nodes"]:
        if node["id"] == "n8":
            node["expression"] = "context.last_decision =="
    assert any("语法错误" in e for e in check(dag))


def test_loop_needs_body_and_positive_iterations():
    dag = prd_default_dag()
    for node in dag["nodes"]:
        if node["id"] == "n11b":
            node["max_iterations"] = 0
            node.pop("body_next")
    errors = check(dag)
    assert any("max_iterations" in e for e in errors)
    assert any("body_next" in e for e in errors)


def test_end_must_not_have_next():
    dag = prd_default_dag()
    for node in dag["nodes"]:
        if node["id"] == "n13":
            node["next"] = ["n1"]
    assert any("end 节点 n13 不应有 next" in e for e in check(dag))


def test_unknown_agent_key_rejected():
    dag = prd_default_dag()
    for node in dag["nodes"]:
        if node["id"] == "n2":
            node["agent_key"] = "gardener"
    assert any("未定义的 agent_key=gardener" in e for e in check(dag))


def test_unknown_tool_rejected():
    dag = prd_default_dag()
    for node in dag["nodes"]:
        if node["id"] == "n10":
            node["tool"] = "water_now"
    assert any("未注册的工具 water_now" in e for e in check(dag))


def test_parallel_needs_two_branches():
    dag = prd_default_dag()
    for node in dag["nodes"]:
        if node["id"] == "n3":
            node["branches"] = ["n4"]
    assert any("至少 2 路扇出" in e for e in check(dag))


def test_missing_nodes_rejected():
    assert validate_dag({}) == ["dag.nodes 必须是非空数组"]
    assert validate_dag({"nodes": []}) == ["dag.nodes 必须是非空数组"]
