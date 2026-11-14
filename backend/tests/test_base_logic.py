"""基座线单元测试：不依赖 MySQL / Redis / MQTT 的纯逻辑。

跑法（在 backend/ 下）：
    .venv/Scripts/python.exe -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api._dag import validate_dag  # noqa: E402
from app.core.runtime_settings import _secret_write_guard  # noqa: E402
from app.devices.command import MAX_PUMP_DURATION_S, _clamp_params  # noqa: E402
from app.mock.simulator import SoilModel  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------- DAG 校验
def _minimal_dag() -> dict:
    return {
        "nodes": [
            {"id": "n1", "type": "start", "next": ["n2"]},
            {"id": "n2", "type": "agent", "agent_key": "scout", "next": ["n3"]},
            {"id": "n3", "type": "end"},
        ]
    }


def test_dag_ok():
    assert validate_dag(_minimal_dag()) == []


def test_dag_rejects_cycle():
    dag = _minimal_dag()
    dag["nodes"][2] = {"id": "n3", "type": "end", "next": ["n2"]}
    errors = validate_dag(dag)
    assert any("环" in e for e in errors), errors


def test_dag_requires_single_start_and_end():
    dag = _minimal_dag()
    dag["nodes"].append({"id": "n4", "type": "start", "next": []})
    errors = validate_dag(dag)
    assert any("start" in e for e in errors)
    assert any("end" in e for e in errors) is False  # end 仍然只有一个


def test_dag_rejects_dangling_reference():
    dag = _minimal_dag()
    dag["nodes"][1]["next"] = ["n99"]
    assert any("n99" in e for e in validate_dag(dag))


def test_dag_loop_body_next_is_allowed_back_edge():
    """loop 的 body_next 是合法的回边，不能被当成环。"""
    dag = {
        "nodes": [
            {"id": "n1", "type": "start", "next": ["n2"]},
            {"id": "n2", "type": "agent", "agent_key": "verifier", "next": ["n3"]},
            {"id": "n3", "type": "loop", "max_iterations": 2, "body_next": "n2", "next": ["n4"]},
            {"id": "n4", "type": "end"},
        ]
    }
    assert validate_dag(dag) == []


def test_dag_unknown_agent_key():
    dag = _minimal_dag()
    errors = validate_dag(dag, known_agents={"weather"})
    assert any("scout" in e for e in errors)


def _prd_default_dag(name: str = "prd_default_dag.json") -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_dag_prd_default_workflow_passes():
    """PRD 9.1 修订后的默认工作流（n11 → n11b → n13）必须通过。

    队长的 10dfed0 把 n11.next 从 ["n13"] 改成 ["n11b"]，并明确「边只由
    next/branches/body_next 显式声明，edges 恒为空数组」。
    """
    assert validate_dag(_prd_default_dag()) == []


def test_dag_prd_legacy_form_still_passes():
    """修订**之前**的 PRD 9.1 原文形态也必须通过（向后兼容，不能只认新写法）。

    旧形态：n11.next=["n13"]、n11b 没有任何入边。如果谁把 loop 的结构豁免去掉，
    这条会立刻红——而那意味着「历史文档里的默认工作流一保存就 400」。
    """
    assert validate_dag(_prd_default_dag("prd_default_dag_legacy.json")) == []


def test_dag_loop_needs_no_inbound_edge():
    """loop 只靠 body_next 悬挂：body 可达即 loop 可达，且 loop 的 next 要继续扩散。

    n3 没有任何入边；n5 只能从 n3 的出口到达——两者都必须算可达。
    """
    dag = {
        "nodes": [
            {"id": "n1", "type": "start", "next": ["n2"]},
            {"id": "n2", "type": "agent", "agent_key": "verifier", "next": ["n4"]},
            {"id": "n3", "type": "loop", "body_next": "n2", "next": ["n5"]},
            {"id": "n5", "type": "tool", "next": ["n4"]},
            {"id": "n4", "type": "end"},
        ]
    }
    assert validate_dag(dag) == []


def test_dag_loop_with_unreachable_body_still_rejected():
    """loop 不能凭空豁免自己的 body：body 走不到，loop 与 body 一起报不可达。"""
    dag = {
        "nodes": [
            {"id": "n1", "type": "start", "next": ["n2"]},
            {"id": "n2", "type": "end"},
            {"id": "n3", "type": "loop", "body_next": "n8", "next": []},
            {"id": "n8", "type": "tool"},
        ]
    }
    errors = validate_dag(dag)
    assert any("不可达" in e for e in errors), errors
    assert any("n3" in e and "n8" in e for e in errors), errors


def test_dag_orphan_non_loop_still_rejected():
    """非 loop 的孤立节点照旧报错，并且要提示「没有任何节点指向它」。"""
    dag = _minimal_dag()
    dag["nodes"].append({"id": "n9", "type": "tool"})
    errors = validate_dag(dag)
    assert any("不可达" in e and "n9" in e for e in errors), errors
    assert any("没有任何节点指向它" in e for e in errors), errors


# ---------------------------------------------------------------- 敏感配置写入闸门
def test_secret_guard_blocks_masked_value():
    """GET /api/settings 返回 sk-a****wxyz，前端原样 PUT 回来必须拦住。"""
    assert _secret_write_guard("llm_api_key", "sk-a****wxyz") is True


def test_secret_guard_blocks_already_encrypted():
    """密文回传会二次加密，照样是灾难。"""
    assert _secret_write_guard("llm_api_key", "enc:gAAAAABfake") is True


def test_secret_guard_blocks_empty():
    """空值 = 不改，不能把已存的 key 抹成空。"""
    assert _secret_write_guard("llm_api_key", "") is True
    assert _secret_write_guard("llm_api_key", "   ") is True
    assert _secret_write_guard("llm_api_key", None) is True


def test_secret_guard_allows_plaintext():
    assert _secret_write_guard("llm_api_key", "sk-abcdef123456") is False


def test_secret_guard_ignores_normal_keys():
    """非敏感字段不受影响：空串也照常落库。"""
    assert _secret_write_guard("mode", "real") is False
    assert _secret_write_guard("mode", "") is False
    assert _secret_write_guard("weather_scenario", "rainy") is False


# ---------------------------------------------------------------- 指令参数
def test_pump_duration_clamped():
    params, clamped = _clamp_params("pump", {"duration_s": 300})
    assert params["duration_s"] == MAX_PUMP_DURATION_S
    assert clamped is True


def test_pump_duration_normal():
    params, clamped = _clamp_params("pump", {"duration_s": 30})
    assert params["duration_s"] == 30
    assert clamped is False


def test_pump_duration_missing_defaults_to_30():
    params, _ = _clamp_params("pump", {})
    assert params["duration_s"] == 30


def test_pump_duration_negative_becomes_one():
    params, _ = _clamp_params("pump", {"duration_s": -5})
    assert params["duration_s"] == 1


# ---------------------------------------------------------------- 土壤模型
def test_soil_drying():
    model = SoilModel(moisture=50.0, dry_rate_per_min=0.06)
    now = model.last_tick
    model.tick(now + 60)  # 一分钟
    assert model.moisture == pytest.approx(49.94, abs=0.01)


def test_soil_irrigation_two_stage():
    """30s 浇水 = 0.35*30 = +10.5%，其中 60% 立刻、40% 在 60s 内渗透完。"""
    model = SoilModel(moisture=38.5, dry_rate_per_min=0.0, gain_per_s=0.35)
    now = model.last_tick
    total = model.irrigate(30)
    assert total == pytest.approx(10.5)
    assert model.moisture == pytest.approx(38.5 + 10.5 * 0.6)  # 44.8

    model.tick(now + 60)
    assert model.moisture == pytest.approx(38.5 + 10.5, abs=0.02)  # 渗透完成 ≈49.0


def test_soil_stuck_moisture_blocks_gain():
    """stuck_moisture 是两轮对照演示的开关：水照浇，湿度不涨。"""
    model = SoilModel(moisture=38.5, dry_rate_per_min=0.0, gain_per_s=0.35, stuck=True)
    model.irrigate(30)
    assert model.moisture == pytest.approx(38.5)


def test_soil_moisture_bounded():
    model = SoilModel(moisture=99.0, dry_rate_per_min=0.0, gain_per_s=1.0)
    model.irrigate(120)
    assert model.moisture <= 100.0
