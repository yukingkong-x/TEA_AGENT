"""接线层的取数口径:执行终端 → 土壤探头、时长从 params 里取。

这两件都是纯函数(`_pick_sensor` / `_duration_of`),不需要数据库,便于在本分支
(没有 models)上跑;真库侧的 `_sensor_of` 只是「查 devices 再调 _pick_sensor」。

实测背景(mock 环境 6 台设备):
    k10-field-01/field/A 区茶园, esp32-soil-02/soil/A 区茶垄, k10-act-03/actuator/A 区泵房
    mock-* 三台同名同址,is_mock=True
    tasks.assigned_device = mock-k10-act-03(执行终端,只有 relay_state/remaining_s)
    soil_moisture 只存在 mock-esp32-soil-02 上
"""
from __future__ import annotations

import pytest

from app.verification.wiring import _duration_of, _pick_sensor, _zone_of

FIELD_A = ("k10-field-01", "field", "A 区茶园", False)
SOIL_A = ("esp32-soil-02", "soil", "A 区茶垄", False)
ACT_A = ("k10-act-03", "actuator", "A 区泵房", False)
M_FIELD_A = ("mock-k10-field-01", "field", "A 区茶园", True)
M_SOIL_A = ("mock-esp32-soil-02", "soil", "A 区茶垄", True)
M_ACT_A = ("mock-k10-act-03", "actuator", "A 区泵房", True)

SIX = [FIELD_A, SOIL_A, ACT_A, M_FIELD_A, M_SOIL_A, M_ACT_A]


def test_zone_prefix_is_parsed_not_whole_string():
    assert _zone_of("A 区泵房") == "A"
    assert _zone_of("A 区茶垄") == "A"
    assert _zone_of("B 区茶垄") == "B"
    assert _zone_of("") == ""
    assert _zone_of(None) == ""


@pytest.mark.parametrize("actuator,expected", [
    (M_ACT_A, "mock-esp32-soil-02"),   # mock 任务只读 mock 探头
    (ACT_A, "esp32-soil-02"),          # 真机任务只读真机探头
])
def test_mock_and_real_batches_do_not_mix(actuator, expected):
    assert _pick_sensor(SIX, actuator[0]) == expected


def test_soil_device_maps_to_itself():
    assert _pick_sensor(SIX, M_SOIL_A[0]) == M_SOIL_A[0]
    assert _pick_sensor(SIX, SOIL_A[0]) == SOIL_A[0]


def test_zone_preference_when_multiple_sensors_exist():
    """B 区也有探头时,不能因为 id 小就跨园区取数。"""
    rows = [
        ("esp32-soil-01", "soil", "B 区茶垄", False),
        SOIL_A,
        ACT_A,
        ("esp32-soil-09", "soil", "A 区东垄", False),
    ]
    # 同区优先(返回 A 区第一台,不是 id 最小的 B 区)
    assert _pick_sensor(rows, ACT_A[0]) == SOIL_A[0]


def test_no_same_batch_sensor_returns_empty_instead_of_cross_batch():
    """只有真机探头、任务是 mock 时:宁可没数据转人工,也不喂另一套量纲。"""
    rows = [FIELD_A, SOIL_A, ACT_A, M_ACT_A]
    assert _pick_sensor(rows, M_ACT_A[0]) == ""
    # 此时 _sensor_of 会保留原 id(行为退回改动前),而不是塞一台真机探头
    assert _pick_sensor(rows, "") == ""


def test_unknown_device_has_no_sensor():
    assert _pick_sensor(SIX, "k10-act-99") == ""
    assert _pick_sensor([], M_ACT_A[0]) == ""


def test_field_device_resolves_by_its_own_batch():
    assert _pick_sensor(SIX, M_FIELD_A[0]) == M_SOIL_A[0]


@pytest.mark.parametrize("payload,expected", [
    ({"action": "pump", "params": {"duration_s": 6}}, 6.0),        # 当前真实格式
    ({"action": "pump", "params": {"duration_s": 30}}, 30.0),
    ({"action": "pump", "duration_s": 10}, 10.0),                  # 老格式
    ({"action": "pump", "params": {"seconds": 3}, "duration_s": 30}, 30.0),  # duration_s 优先
    ({"action": "pump", "params": {"seconds": 3}}, 3.0),
    ({"action": "pump"}, 30.0),                                    # 都没有 → 默认
    ({"action": "pump", "params": {"duration_s": None}}, 30.0),
    ({"action": "pump", "params": {"duration_s": "abc"}}, 30.0),
    ({"action": "pump", "params": "not-a-dict"}, 30.0),            # 脏数据不炸
])
def test_duration_read_from_nested_params(payload, expected):
    assert _duration_of(payload) == pytest.approx(expected)
