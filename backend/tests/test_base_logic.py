"""基座线单元测试：不依赖 MySQL / Redis / MQTT 的纯逻辑。

跑法（在 backend/ 下）：
    .venv/Scripts/python.exe -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api._dag import validate_dag  # noqa: E402
from app.devices.command import MAX_PUMP_DURATION_S, _clamp_params  # noqa: E402
from app.mock.simulator import SoilModel  # noqa: E402


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
