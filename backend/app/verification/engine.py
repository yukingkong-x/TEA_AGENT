"""REQ-F-016/017/018 的接缝层:给基座提供 `verify_task` 与 `generate_report`。

接缝签名(见 backend/app/seams.py 的 _META):
- `verify_task(task_no: str) -> dict`
- `generate_report(run_id: int) -> int`(返回 report_id)

数据全部通过 `VerificationDeps` 注入,本模块不 import ORM —— 队长分支没有 models,
等基座合进来由 bootstrap 装配 deps。未接线时按基座约定抛 `SeamNotReady`,
路由层(exception_handler)会统一转 503 + `code: SEAM_NOT_READY`,前端显示「接入中」。

判定逻辑全在 `verify.py` / `achievement.py` / `confidence.py` / `feedback.py` 里,
本层只做「取数 → 判定 → 落库 → 触发下一步」的编排,保证判定本身可以脱离数据库单测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.verification.report import ReportData, RoundView, render_report
from app.verification.verify import VerifyResult, verify


class VerificationNotReady(RuntimeError):
    """验证引擎未接线(缺 deps)。"""


def _raise_not_ready(seam: str, reason: str) -> None:
    """优先抛基座的 SeamNotReady(路由统一转 503);基座未合入时退化为 RuntimeError。"""
    try:
        from app.seams import SeamNotReady  # 公共接缝层,两边都用
    except Exception:  # noqa: BLE001 基座还没合进这支分支
        raise VerificationNotReady(f"{seam} 尚未就绪:{reason}")
    raise SeamNotReady(seam, reason)


@dataclass
class VerificationDeps:
    """基座注入的取数/落库能力。字段都是回调,本层不关心底下是 MySQL 还是内存。"""

    # 任务:{"baseline": 38.5, "duration_s": 30, "target_low": 55, "target_high": 65,
    #        "round_no": 1, "max_rounds": 2, "device_id": "esp32-soil-02"}
    load_task: Callable[[str], dict]
    # 渗透期后的连续读数(取中位数);设备离线时返回空列表也能判 low confidence
    load_samples: Callable[[str], list[float]]
    # 落库:返回 verification 记录 id
    save_verification: Callable[[str, VerifyResult], Any]
    device_online: Optional[Callable[[str], bool]] = None
    previous_value: Optional[Callable[[str], Optional[float]]] = None
    history_stats: Optional[Callable[[str], tuple[Optional[float], Optional[float]]]] = None
    # 转人工时的报警(签名与工具层 raise_alert 一致)
    raise_alert: Optional[Callable[..., Any]] = None
    # failed 时生成下一轮修正任务(trigger=selfloop)
    schedule_correction: Optional[Callable[[str, dict], Any]] = None
    # 报告:读 run 的完整上下文
    load_run: Optional[Callable[[int], dict]] = None
    save_report: Optional[Callable[[int, str], int]] = None


_deps: Optional[VerificationDeps] = None


def configure(deps: VerificationDeps) -> None:
    global _deps
    _deps = deps


def is_ready() -> bool:
    return _deps is not None


def _require(seam: str) -> VerificationDeps:
    if _deps is None:
        _raise_not_ready(seam, "等待基座注入 VerificationDeps(bootstrap 里 configure)")
    return _deps  # type: ignore[return-value]


def verify_task(task_no: str) -> dict:
    """接缝:对一条已完成的任务做复测验证,落库并触发后续动作。"""
    deps = _require("verify_task")
    task = deps.load_task(task_no)
    samples = deps.load_samples(task_no)
    device_id = task.get("device_id", "")

    online = True
    if deps.device_online is not None and device_id:
        online = bool(deps.device_online(device_id))
    previous = deps.previous_value(task_no) if deps.previous_value else None
    mean, sigma = (None, None)
    if deps.history_stats is not None and device_id:
        mean, sigma = deps.history_stats(device_id)

    result = verify(
        samples=samples,
        baseline=float(task.get("baseline", 0.0)),
        duration_s=float(task.get("duration_s", 0.0)),
        target_low=float(task.get("target_low", 55.0)),
        target_high=float(task.get("target_high", 65.0)),
        round_no=int(task.get("round_no", 1)),
        max_rounds=int(task.get("max_rounds", 2)),
        device_online=online,
        previous_value=previous,
        history_mean=mean,
        history_sigma=sigma,
    )

    saved = deps.save_verification(task_no, result)

    if result.needs_human and deps.raise_alert is not None:
        deps.raise_alert("critical", f"{task_no} 转人工:{result.note}", "agent:verifier")
    if result.verdict == "failed" and result.correction and result.correction.is_action:
        if deps.schedule_correction is not None:
            deps.schedule_correction(task_no, result.correction.payload)

    return {
        "task_no": task_no,
        "verification_id": saved,
        "verdict": result.verdict,
        "achievement": result.achievement.value,
        "over_irrigated": result.achievement.over_irrigated,
        "gap": result.achievement.gap,
        "confidence": result.confidence.total,
        "confidence_detail": {
            "data_quality": result.confidence.data_quality,
            "rule_cross": result.confidence.rule_cross,
            "consistency": result.confidence.consistency,
            "reasons": result.confidence.reasons,
        },
        "measured": result.achievement.measured,
        "baseline": result.achievement.baseline,
        "round_no": result.round_no,
        "note": result.note,
        "correction": None if result.correction is None else {
            "strategy": result.correction.strategy,
            "reason": result.correction.reason,
            "duration_s": result.correction.duration_s,
            "times": result.correction.times,
            "interval_s": result.correction.interval_s,
        },
    }


def generate_report(run_id: int) -> int:
    """接缝:把一次 run 的完整过程渲染成 Markdown 报告,返回 report_id。"""
    deps = _require("generate_report")
    if deps.load_run is None or deps.save_report is None:
        _raise_not_ready("generate_report", "缺少 load_run / save_report")

    payload = deps.load_run(run_id)
    data = ReportData(
        run_id=run_id,
        wf_name=payload.get("wf_name", "巡园浇水工作流"),
        trigger=payload.get("trigger", "manual"),
        started_at=payload.get("started_at", ""),
        finished_at=payload.get("finished_at", ""),
        outcome=payload.get("outcome", "running"),
        rounds=[RoundView(**item) for item in payload.get("rounds", [])],
        timeline=payload.get("timeline", []),
        alerts=payload.get("alerts", []),
        confidence_reasons=payload.get("confidence_reasons", []),
        achievement_detail=payload.get("achievement_detail", {}),
    )
    markdown = render_report(data)
    return deps.save_report(run_id, markdown)
