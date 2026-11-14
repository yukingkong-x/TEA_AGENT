"""接缝层单测:verify_task / generate_report 的编排(取数 → 判定 → 落库 → 触发下一步)。

这一层不测判定数学(那是 verify/achievement/confidence 的事),只测:
1. 数据取用是否正确传到判定层;
2. 转人工时有没有报警、失败时有没有排修正任务;
3. 未接线时是否明确失败(不许假装成功);
4. 报告接缝返回 report_id 且内容含证据链。
"""
import pytest

from app.verification import engine as engine_mod
from app.verification.engine import VerificationDeps, configure, generate_report, verify_task


class Repo:
    """内存版取数/落库,替身基座的 MySQL。"""

    def __init__(self, task=None, samples=None, online=True, history=(None, None)):
        self.task = task or {
            "baseline": 38.5, "duration_s": 30, "target_low": 55, "target_high": 65,
            "round_no": 1, "max_rounds": 2, "device_id": "esp32-soil-02",
        }
        self.samples = samples if samples is not None else [44.8, 45.0, 45.2]
        self.online = online
        self.history = history
        self.alerts: list[tuple] = []
        self.corrections: list[tuple] = []
        self.saved: list = []
        self.reports: list = []

    def deps(self) -> VerificationDeps:
        return VerificationDeps(
            load_task=lambda task_no: dict(self.task),
            load_samples=lambda task_no: list(self.samples),
            save_verification=self._save,
            device_online=lambda device_id: self.online,
            previous_value=lambda task_no: None,
            history_stats=lambda device_id: self.history,
            raise_alert=lambda level, message, source=None: self.alerts.append((level, message, source)),
            schedule_correction=lambda task_no, payload: self.corrections.append((task_no, payload)),
            load_run=self._load_run,
            save_report=self._save_report,
        )

    def _save(self, task_no, result):
        self.saved.append((task_no, result))
        return len(self.saved)

    def _load_run(self, run_id):
        return {
            "wf_name": "巡园浇水工作流", "trigger": "manual",
            "started_at": "2026-11-14 10:12:33", "finished_at": "2026-11-14 10:16:01",
            "outcome": "success",
            "rounds": [
                {"round_no": 1, "baseline": 38.5, "measured": 45.0, "achievement": 39.39,
                 "confidence": 1.0, "verdict": "failed", "duration_s": 30,
                 "note": "缺口 10.0% 在 15 以内,单次补灌 20.0s"},
                {"round_no": 2, "baseline": 45.0, "measured": 57.0, "achievement": 100.0,
                 "confidence": 0.93, "verdict": "success", "duration_s": 20},
            ],
            "timeline": [{"ts": "10:12:40", "name": "巡园播报", "event": "node_finished",
                          "status": "done", "duration_ms": 1200}],
        }

    def _save_report(self, run_id, markdown):
        self.reports.append((run_id, markdown))
        return 7


@pytest.fixture(autouse=True)
def _reset_deps():
    yield
    engine_mod._deps = None


def test_verify_task_returns_contract_dict():
    repo = Repo()
    configure(repo.deps())
    result = verify_task("task-001")

    assert result["task_no"] == "task-001"
    assert result["verdict"] == "failed"
    assert result["achievement"] == 39.39
    assert result["verification_id"] == 1
    assert result["correction"]["strategy"] == "topup"
    assert result["confidence_detail"]["data_quality"] == 1.0
    assert repo.saved[0][1].verdict == "failed"


def test_failed_verification_schedules_correction():
    repo = Repo()
    configure(repo.deps())
    verify_task("task-001")

    assert len(repo.corrections) == 1
    task_no, payload = repo.corrections[0]
    assert task_no == "task-001"
    assert payload["action"] == "pump"
    assert payload["duration_s"] == 20.0
    assert repo.alerts == []            # 第一轮失败不报警,只是进入 Self-Loop


def test_low_confidence_raises_critical_alert():
    # 单点读数 + 设备离线 + 偏离 24h 均值 → 三路一起扣,置信度跌破 60%
    repo = Repo(samples=[57], online=False, history=(10, 2))
    configure(repo.deps())
    result = verify_task("task-002")

    assert result["verdict"] == "needs_human"
    assert len(repo.alerts) == 1
    level, message, source = repo.alerts[0]
    assert level == "critical"
    assert "转人工" in message
    assert source == "agent:verifier"    # PRD 6.11 的来源形态
    assert repo.corrections == []        # 转人工时不排修正任务


def test_second_round_failure_escalates_without_new_correction():
    repo = Repo(samples=[44, 45, 46])
    repo.task["round_no"] = 2
    configure(repo.deps())
    result = verify_task("task-003")

    assert result["verdict"] == "needs_human"
    assert repo.corrections == []
    assert len(repo.alerts) == 1


def test_offline_device_marks_confidence_low():
    repo = Repo(samples=[57, 57, 57], online=False)
    configure(repo.deps())
    result = verify_task("task-004")

    # 离线扣 0.4(数据质量 0.6),速率 1.6%/s 超上限(规则交叉 0.75)→ 0.3+0.225+0.2
    assert result["confidence_detail"]["data_quality"] == 0.6
    assert result["confidence"] == 0.725
    assert result["verdict"] == "success"   # 0.725 仍达标,只是数据质量有扣分


def test_unwired_seam_fails_loudly():
    engine_mod._deps = None
    with pytest.raises(RuntimeError):
        verify_task("task-005")


def test_generate_report_returns_id_and_markdown():
    repo = Repo()
    configure(repo.deps())
    report_id = generate_report(12)

    assert report_id == 7
    run_id, markdown = repo.reports[0]
    assert run_id == 12
    assert "第 1 轮" in markdown and "第 2 轮" in markdown
    assert "39.39" in markdown and "100.00" in markdown
    assert "## 三、诊断与修正" in markdown


def test_generate_report_unwired_fails_loudly():
    engine_mod._deps = None
    with pytest.raises(RuntimeError):
        generate_report(1)
