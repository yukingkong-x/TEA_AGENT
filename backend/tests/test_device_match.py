"""设备指代解析（core/device_match.py）：LLM 传「A区」，平台要能落到真实 device_id。

为什么值得独立的测试：这类失败看起来像「数据质量问题」——工具报「设备不存在」，
Agent 就回「传感器可能故障」，决策判 none，闭环断在下发之前，而每一步的日志都正常。
实测 2026-11-14 的 run 里四个 Agent 分别传了 `A区茶垄` / `A区` / `A区土壤传感器ID`。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import device_match  # noqa: E402

DEVICES = [
    {"device_id": "mock-esp32-soil-02", "name": "[Mock] 土壤墒情节点", "location": "A 区茶垄",
     "role": "soil", "is_mock": 1},
    {"device_id": "mock-k10-field-01", "name": "[Mock] 巡园气象站", "location": "A 区茶垄",
     "role": "field", "is_mock": 1},
    {"device_id": "mock-k10-act-03", "name": "[Mock] 灌溉执行终端", "location": "A 区泵房",
     "role": "actuator", "is_mock": 1},
    {"device_id": "esp32-soil-02", "name": "土壤墒情节点", "location": "A 区茶垄",
     "role": "soil", "is_mock": 0},
]


def test_exact_device_id_wins():
    hit = device_match.match("mock-esp32-soil-02", DEVICES)
    assert hit is not None
    assert hit.device_id == "mock-esp32-soil-02"
    assert hit.matched_by == "device_id"


def test_empty_candidates_returns_none():
    assert device_match.match("A区", []) is None


def test_location_text_resolves_to_the_right_role():
    """「A区土壤传感器ID」这种带噪声的指代 → 土壤节点，绝不能落到气象站。"""
    hit = device_match.match("A区土壤传感器ID", DEVICES)
    assert hit is not None
    assert hit.device_id == "mock-esp32-soil-02"


def test_role_keyword_overrides_location_noise():
    """query 里出现「气象」就锁 field 角色。"""
    hit = device_match.match("A区气象站", DEVICES)
    assert hit is not None
    assert hit.device_id == "mock-k10-field-01"


def test_actuator_by_pump_keyword():
    hit = device_match.match("A区灌溉泵", DEVICES)
    assert hit is not None
    assert hit.device_id == "mock-k10-act-03"


def test_prefer_mock_breaks_ties():
    """同为 soil、同 location 时，mock 模式必须选 mock 那台（两套量纲不能混）。"""
    hit = device_match.match("A区", DEVICES, role="soil", prefer_mock=True)
    assert hit is not None
    assert hit.device_id == "mock-esp32-soil-02"

    hit_real = device_match.match("A区", DEVICES, role="soil", prefer_mock=False)
    assert hit_real is not None
    assert hit_real.device_id == "esp32-soil-02"


def test_unknown_query_falls_back_to_role_instead_of_raising():
    """完全对不上时给同角色的设备（宁可给近似数据），并留下 matched_by 供排查。"""
    hit = device_match.match("随便说说", DEVICES, role="actuator")
    assert hit is not None
    assert hit.device_id == "mock-k10-act-03"
    assert hit.matched_by.startswith("role:")


def test_no_role_and_no_text_hit_returns_none():
    """既没角色线索、文本也对不上 → 返回 None，让调用方报错并列出可用设备。"""
    assert device_match.match("完全无关的说法", DEVICES) is None


def test_normalize_ignores_case_space_and_dash():
    assert device_match.normalize("Mock-ESP32 Soil 02") == "mockesp32soil02"
    assert device_match.normalize(None) == ""
