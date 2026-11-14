"""真实 device_cmd 任务的验证回归:三条错路径各留一条断言。

背景(2026-11-14 联调实测):库里任何一条 device_cmd 任务,payload 都是
`{"action": "pump", "params": {"duration_s": 30}, "device_id": "mock-k10-act-03"}` ——
不带 baseline、不带顶层 duration_s、assigned_device 是执行终端而不是土壤探头。
原来三处都按「理想 payload」写,结果是:
1. `float(task.get("baseline", 0.0))` 撞 None → POST /api/verify 必 500;
2. 取数查执行终端 → samples=[] → 达成率/置信度恒 0;
3. 时长退 30.0 → 速率判定按错时长算。
这些测试跑的是 engine + verify 的组合(不含 DB),接线的取数逻辑另在
test_wiring_pick_sensor.py 里用纯函数覆盖。
"""
from __future__ import annotations

import pytest

from app.verification import engine
from app.verification.engine import VerificationDeps, configure, verify_task
from app.verification.verify import verify


class _Deps:
    """最小假 deps,记录调用参数,不碰数据库。"""

    def __init__(self, task: dict, samples=None, previous=None, baseline_before=None):
        self.task = task
        self.samples = samples if samples is not None else [46.83, 48.9, 48.88]
        self.previous = previous
        self._baseline_before = baseline_before
        self.seen_online: list[str] = []
        self.seen_stats: list[str] = []
        self.saved: list = []
        # 可选回调显式置空,否则 engine 的 hasattr 访问会炸(它是 dataclass 的可选字段)
        self.raise_alert = None
        self.schedule_correction = None
        self.load_run = None
        self.save_report = None

    def load_task(self, task_no: str) -> dict:
        return self.task

    def load_samples(self, task_no: str):
        return self.samples

    def save_verification(self, task_no: str, result):
        self.saved.append(result)
        return 7

    def device_online(self, device_id: str) -> bool:
        self.seen_online.append(device_id)
        return True

    def previous_value(self, task_no: str):
        return self.previous

    def baseline_before(self, task_no: str):
        return self._baseline_before

    def history_stats(self, device_id: str):
        self.seen_stats.append(device_id)
        return (47.5, 1.2)


def _task(**over) -> dict:
    """接线层对真实 device_cmd 任务会给出这样的字典(baseline/previous 都可能没有)。"""
    base = {
        "task_no": "task-20261114-0002",
        "run_id": 1,
        "device_id": "mock-k10-act-03",
        "sensor_id": "mock-esp32-soil-02",
        "baseline": None,
        "duration_s": 30.0,
        "target_low": 55.0,
        "target_high": 65.0,
        "round_no": 1,
        "max_rounds": 2,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _clean_engine():
    engine._deps = None
    yield
    engine._deps = None


def test_baseline_none_does_not_raise_and_falls_back_to_previous():
    """第 1 层:baseline 键存在但值为 None,不能再炸 TypeError。"""
    deps = _Deps(_task(), previous=46.83)
    configure(deps)

    out = verify_task("task-20261114-0002")     # 改之前这一行必抛 TypeError

    assert out["baseline"] == pytest.approx(46.83)
    assert out["baseline_missing"] is False
    assert out["measured"] == pytest.approx(48.88)       # 3 条读数取中位数(48.88)
    assert out["achievement"] == pytest.approx(25.09, abs=0.02)
    assert out["verdict"] == "failed"                    # <60% 且还有轮次 → 触发修正
    assert deps.saved and deps.saved[0].achievement.baseline == pytest.approx(46.83)


def test_both_baseline_sources_missing_goes_needs_human_not_fake_success():
    """既没 payload baseline 也没历史前值 → 转人工。

    这一条是防「只修 float() 那一行」的漏网:基线退 0.0 时
    (measured − 0) / 55 ≈ 89% 会被判 success,比 500 更难发现。
    """
    configure(_Deps(_task(), previous=None))

    out = verify_task("task-20261114-0002")

    assert out["verdict"] == "needs_human"
    assert out["baseline_missing"] is True
    assert out["baseline"] is None          # 对外不伪装成 0.0
    assert out["achievement"] == 0.0        # 算不出来就报 0 且不参与判定
    assert out["confidence"] < 60.0         # 置信度同步塌下来,不是「92% 却转人工」
    assert "基线" in out["note"]


def test_payload_baseline_wins_over_previous():
    configure(_Deps(_task(baseline=38.5), previous=46.83))

    out = verify_task("task-20261114-0002")

    assert out["baseline"] == pytest.approx(38.5)


def test_baseline_before_execution_beats_now_counting_window():
    """时间戳口径优先于「现在往前数第 4 条」:等久了也不会把浇水后的读数当基线。"""
    configure(_Deps(_task(), previous=46.83, baseline_before=38.45))

    out = verify_task("task-20261114-0002")

    assert out["baseline"] == pytest.approx(38.45)
    # (48.88 − 38.45) / (55 − 38.45) = 63.02% —— 与联调实测的修后数字一致
    assert out["achievement"] == pytest.approx(63.02, abs=0.05)
    assert out["verdict"] == "success"


def test_previous_is_last_resort_when_no_timestamp_baseline():
    configure(_Deps(_task(), previous=46.83, baseline_before=None))

    out = verify_task("task-20261114-0002")

    assert out["baseline"] == pytest.approx(46.83)


def test_sensor_id_is_used_for_online_and_history():
    """第 2 层:设备在线/历史分布要查土壤探头,不是执行终端 k10-act-03。"""
    deps = _Deps(_task(), previous=46.83)
    configure(deps)

    verify_task("task-20261114-0002")

    assert deps.seen_online == ["mock-esp32-soil-02"]
    assert deps.seen_stats == ["mock-esp32-soil-02"]


def test_sensor_id_falls_back_to_device_id_when_absent():
    """没有 sensor_id 的旧 deps 仍可按 device_id 工作(行为不退步)。"""
    deps = _Deps(_task(sensor_id=None), previous=46.83)
    configure(deps)

    verify_task("task-20261114-0002")

    assert deps.seen_online == ["mock-k10-act-03"]


def test_zero_strings_and_garbage_fields_do_not_raise():
    """payload 里被写成 "abc"/"" 的字段不能把验证打成 500。"""
    configure(
        _Deps(
            _task(baseline="", duration_s="abc", target_low=None, target_high="",
                  round_no="x", max_rounds=None),
            previous=46.83,
        )
    )

    out = verify_task("task-20261114-0002")

    assert out["verdict"] in {"success", "failed", "needs_human"}


def test_empty_samples_are_needs_human_with_low_confidence():
    configure(_Deps(_task(), samples=[], previous=46.83))

    out = verify_task("task-20261114-0002")

    assert out["verdict"] == "needs_human"
    assert out["confidence"] == 0.0


def test_verify_accepts_none_baseline_directly():
    """组合层签名允许 baseline=None,不能要求调用方先编一个 0.0。"""
    result = verify(samples=[46.83, 48.9, 48.88], baseline=None, duration_s=30.0)

    assert result.baseline_missing is True
    assert result.verdict == "needs_human"
    assert result.achievement.baseline == 0.0


def test_verify_with_baseline_keeps_prd_formula():
    """有基线时公式不变:(48.88 − 46.83) / (55 − 46.83) = 25.09%。"""
    result = verify(samples=[46.83, 48.9, 48.88], baseline=46.83, duration_s=30.0)

    assert result.baseline_missing is False
    assert result.achievement.value == pytest.approx(25.09, abs=0.02)
