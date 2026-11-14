"""验证引擎接线：`VerificationDeps` 接到基座的库（B 在 bootstrap 里加一行）。

```python
from .verification.wiring import install as install_verification
install_verification()
```

取数口径（PRD 11.1「复测取执行后连续 3 次读数的中位数」）：
- `load_samples` 取该设备 `soil_moisture` 最近 3 条，按时间升序交给验证引擎；
- `previous_value` 取这 3 条之前的一条（判定「浇了没升」用）；
- `history_stats` 取近 24h 的均值与总体标准差（一致性分用）。

全部返回真实库里的数，取不到就返回空/None——验证引擎会把空样本判成低置信度转人工，
**不会拿默认值编一个达成率出来**。
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger

from app.verification.engine import VerificationDeps, configure, is_ready

METRIC = "soil_moisture"
SAMPLE_COUNT = 3
HISTORY_WINDOW = timedelta(hours=24)


def _f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ─────────────────────────── 取数 ───────────────────────────

def _device_of(row) -> str:
    payload = row.payload_json or {}
    return row.assigned_device or payload.get("device_id") or ""


def _recent_values(device_id: str, limit: int) -> list[Any]:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.sensor_data import SensorData

    if not device_id:
        return []
    with session_scope() as db:
        rows = db.scalars(
            select(SensorData)
            .where(SensorData.device_id == device_id, SensorData.metric == METRIC)
            .order_by(SensorData.ts.desc())
            .limit(limit)
        ).all()
        return [(row.value, row.ts) for row in rows]


def _load_task(task_no: str) -> dict:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.tasks import Task

    with session_scope() as db:
        row = db.scalar(select(Task).where(Task.task_no == task_no))
        if row is None:
            raise LookupError(f"任务 {task_no} 不存在")
        payload = dict(row.payload_json or {})
        device_id = _device_of(row)
        return {
            "task_no": row.task_no,
            "run_id": row.run_id,
            "device_id": device_id,
            "baseline": _f(payload.get("baseline")),
            "duration_s": _f(payload.get("duration_s"), 30.0),
            "target_low": _f(payload.get("target_low"), 55.0),
            "target_high": _f(payload.get("target_high"), 65.0),
            "round_no": int(payload.get("round_no", 1) or 1),
            "max_rounds": int(payload.get("max_rounds", 2) or 2),
        }


def _load_samples(task_no: str) -> list[float]:
    task = _load_task(task_no)
    values = _recent_values(task["device_id"], SAMPLE_COUNT)
    return [float(v) for v, _ts in reversed(values)]


def _previous_value(task_no: str) -> Optional[float]:
    task = _load_task(task_no)
    values = _recent_values(task["device_id"], SAMPLE_COUNT + 1)
    if len(values) <= SAMPLE_COUNT:
        return None
    return float(values[SAMPLE_COUNT][0])


def _history_stats(device_id: str) -> tuple[Optional[float], Optional[float]]:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.sensor_data import SensorData

    if not device_id:
        return (None, None)
    since = datetime.now() - HISTORY_WINDOW
    with session_scope() as db:
        rows = db.scalars(
            select(SensorData.value).where(
                SensorData.device_id == device_id,
                SensorData.metric == METRIC,
                SensorData.ts >= since,
            )
        ).all()
    values = [float(v) for v in rows]
    if len(values) < 3:
        return (None, None)
    return (statistics.fmean(values), statistics.pstdev(values))


def _device_online(device_id: str) -> bool:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.devices import Device

    if not device_id:
        return False
    with session_scope() as db:
        online = db.scalar(select(Device.online).where(Device.device_id == device_id))
    return True if online is None else bool(online)


# ─────────────────────────── 落库与后续动作 ───────────────────────────

def _save_verification(task_no: str, result) -> int:
    from app.db import session_scope
    from app.models.verifications import Verification

    run_id = None
    try:
        run_id = _load_task(task_no).get("run_id")
    except LookupError:
        logger.warning("验证落库：任务 {} 已不存在，run_id 记账为空", task_no)

    with session_scope() as db:
        row = Verification(
            run_id=run_id,
            task_no=task_no,
            baseline_value=result.achievement.baseline,
            target_low=result.achievement.target_low,
            target_high=result.achievement.target_high,
            measured_value=result.achievement.measured,
            achievement=result.achievement.value,
            confidence=result.confidence.total,
            conf_detail_json={
                "data_quality": result.confidence.data_quality,
                "rule_cross": result.confidence.rule_cross,
                "consistency": result.confidence.consistency,
                "reasons": result.confidence.reasons,
            },
            conclusion=result.verdict,
        )
        db.add(row)
        db.flush()
        return int(row.id)


def _raise_alert(level: str, message: str, source: str = "agent:verifier") -> Any:
    from app.core.tool_impl import raise_alert

    return raise_alert(level, message, source=source)


def _schedule_correction(task_no: str, payload: dict) -> Any:
    """Self-Loop：把修正指令排成一条新任务（trigger=selfloop），由调度器接走。"""
    from app.db import session_scope
    from app.models.tasks import Task
    from app.core.ids import new_task_no   # 基座的编号生成器（task-YYYYMMDD-NNNN）

    origin = _load_task(task_no)
    with session_scope() as db:
        row = Task(
            task_no=new_task_no(),
            run_id=origin.get("run_id"),
            type="device_cmd",
            payload_json={**payload, "origin_task": task_no,
                          "round_no": int(origin.get("round_no", 1)) + 1},
            priority=9,
            status="pending",
            assigned_agent="executor",
            assigned_device=origin.get("device_id"),
            timeout_s=120,
        )
        db.add(row)
        db.flush()
        logger.info("Self-Loop 修正任务已排入队列：{}（源 {}）", row.task_no, task_no)
        return row.task_no


# ─────────────────────────── 报告 ───────────────────────────

def _load_run(run_id: int) -> dict:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.alerts import Alert
    from app.models.tasks import Task
    from app.models.verifications import Verification
    from app.models.workflow_runs import WorkflowRun
    from app.models.workflows import Workflow

    with session_scope() as db:
        run = db.get(WorkflowRun, run_id)
        if run is None:
            raise LookupError(f"run {run_id} 不存在")
        wf = db.get(Workflow, run.wf_id)
        verifications = db.scalars(
            select(Verification).where(Verification.run_id == run_id).order_by(Verification.id)
        ).all()
        tasks = db.scalars(
            select(Task).where(Task.run_id == run_id).order_by(Task.id)
        ).all()

        rounds = [
            {
                "round_no": index + 1,
                "baseline": _f(v.baseline_value, 0.0),
                "measured": _f(v.measured_value, 0.0),
                "achievement": _f(v.achievement, 0.0),
                "confidence": _f(v.confidence, 0.0),
                "verdict": v.conclusion or "failed",
                "target_low": _f(v.target_low, 55.0),
                "target_high": _f(v.target_high, 65.0),
                "duration_s": 0.0,
            }
            for index, v in enumerate(verifications)
        ]
        timeline = [
            {
                "ts": (t.created_at or run.started_at).isoformat() if (t.created_at or run.started_at) else "",
                "name": t.type,
                "event": t.task_no,
                "status": t.status,
                "duration_ms": int(((t.updated_at - t.created_at).total_seconds() * 1000))
                if t.updated_at and t.created_at else 0,
            }
            for t in tasks
        ]
        alerts = []
        if run.started_at is not None:
            window_end = run.finished_at or datetime.now()
            alerts = [
                {"level": a.level, "message": a.message, "source": a.source}
                for a in db.scalars(
                    select(Alert).where(Alert.created_at >= run.started_at, Alert.created_at <= window_end)
                    .order_by(Alert.id)
                ).all()
            ]
        last = verifications[-1] if verifications else None
        detail = dict(last.conf_detail_json or {}) if last else {}

        return {
            "run_id": run_id,
            "wf_name": wf.name if wf else "巡园浇水工作流",
            "trigger": run.trigger or "manual",
            "started_at": run.started_at.isoformat(timespec="seconds") if run.started_at else "",
            "finished_at": run.finished_at.isoformat(timespec="seconds") if run.finished_at else "",
            "outcome": (last.conclusion if last else run.status),
            "rounds": rounds,
            "timeline": timeline,
            "alerts": alerts,
            "confidence_reasons": detail.get("reasons") or [],
            "achievement_detail": {
                "target_low": _f(last.target_low, 55.0) if last else 55.0,
                "target_high": _f(last.target_high, 65.0) if last else 65.0,
            },
        }


def _save_report(run_id: int, markdown: str) -> int:
    from app.db import session_scope
    from app.models.reports import Report

    with session_scope() as db:
        row = Report(run_id=run_id, report_type="run", content_md=markdown, stats_json={})
        db.add(row)
        db.flush()
        return int(row.id)


# ─────────────────────────── 安装 ───────────────────────────

def build_deps() -> VerificationDeps:
    return VerificationDeps(
        load_task=_load_task,
        load_samples=_load_samples,
        save_verification=_save_verification,
        device_online=_device_online,
        previous_value=_previous_value,
        history_stats=_history_stats,
        raise_alert=_raise_alert,
        schedule_correction=_schedule_correction,
        load_run=_load_run,
        save_report=_save_report,
    )


def install() -> bool:
    if is_ready():
        return True
    try:
        configure(build_deps())
        logger.info("验证引擎已接线（取数 / 落库 / 报警 / 修正任务 / 报告）")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("验证引擎接线失败，verify_task 将返回 503：{}", exc)
        return False
