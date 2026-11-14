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


def _zone_of(location: Optional[str]) -> str:
    """从「A 区茶垄」取「A」。泵房与茶垄本来就不同址,但同属一个园区。"""
    text = (location or "").strip()
    if not text:
        return ""
    head, sep, _rest = text.partition("区")
    return head.strip() if sep else text


def _duration_of(payload: dict) -> float:
    """浇水时长:设备指令下发时嵌在 params 里,老格式才在顶层(纯函数,便于单测)。

    只读顶层会一律退成 30.0,置信度里的速率判定(0.1-1.0 %/s)就按错时长算,
    「6 秒的补灌」会被当成 30 秒判成速率偏低。
    """
    params = payload.get("params")
    if not isinstance(params, dict):
        params = {}
    for value in (params.get("duration_s"), payload.get("duration_s"), params.get("seconds")):
        parsed = _f(value)
        if parsed is not None:
            return parsed
    return 30.0


def _pick_sensor(
    candidates: list[tuple[str, str, Optional[str], bool]],
    device_id: str,
    is_mock: Optional[bool] = None,
) -> str:
    """从设备清单里挑「复测读数来源」(纯函数,便于单测)。

    `soil_moisture` 只在 role=soil 的设备上;任务的 `assigned_device` 是**执行终端**
    (k10-act-03 只有 relay_state / remaining_s),拿它查 soil_moisture 必然 0 条
    → samples=[] → 达成率与置信度恒 0 → 永远转人工。

    优先级:自身就是 soil → 同园区(区前缀相同)且同批次的 soil → 同批次的 soil → 放弃。
    不按 location 整串比:泵房 ≠ 茶垄,比了必然落空。
    不跨批次:mock 任务只读 mock 传感器、真机只读真机,两套量纲不能混;
    同批次一台 soil 都没有时返回空(→ 没数据 → 转人工),宁可认怂也不喂假数据。
    """
    if not candidates:
        return ""
    row = next((c for c in candidates if c[0] == device_id), None)
    if row is not None:
        if row[1] == "soil":
            return row[0]
        if is_mock is None:
            is_mock = row[3]
    if is_mock is None:
        return ""
    zone = _zone_of(row[2]) if row is not None else ""
    soils = [c for c in candidates if c[1] == "soil" and c[3] == is_mock]
    if zone:
        for cand in soils:
            if _zone_of(cand[2]) == zone:
                return cand[0]
    return soils[0][0] if soils else ""


def _sensor_of(device_id: str) -> str:
    """把执行终端映射到复测用的土壤探头(幂等:传 soil 设备返回它自己)。"""
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.devices import Device

    if not device_id:
        return ""
    with session_scope() as db:
        rows = db.execute(
            select(Device.device_id, Device.role, Device.location, Device.is_mock)
        ).all()
    candidates = [(r[0], r[1], r[2], bool(r[3])) for r in rows]
    return _pick_sensor(candidates, device_id) or device_id


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


def _value_before(device_id: str, before: Optional[datetime]) -> Optional[float]:
    """取 `before` 时刻之前最后一条读数。"""
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.sensor_data import SensorData

    if not device_id or before is None:
        return None
    with session_scope() as db:
        value = db.scalar(
            select(SensorData.value)
            .where(
                SensorData.device_id == device_id,
                SensorData.metric == METRIC,
                SensorData.ts <= before,
            )
            .order_by(SensorData.ts.desc())
            .limit(1)
        )
    return _f(value)


def _baseline_before(task_no: str) -> Optional[float]:
    """执行前基线 = 任务创建时刻之前最后一条 soil_moisture 读数。

    PRD 11.1 的基线就是「执行前」的值。task.created_at 一定早于开始浇水,
    所以 ts <= created_at 的最近一条天然就是执行前基线。

    比「从当前往前数第 4 条」稳得多:那个口径把验证时机绑在浇水后 ~90 秒
    (等久了,第 4 条已经是浇水后的读数,基线被抬高 → 明明浇够了却判「未上升」)。
    时间戳口径与「什么时候点验证」无关,演示不必掐表。
    """
    task = _load_task(task_no)
    return _value_before(task.get("sensor_id") or task["device_id"], task.get("created_at"))


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
        # 决策层下发的是 target_range: [55, 65],不是 target_low/target_high
        target_range = payload.get("target_range")
        if isinstance(target_range, (list, tuple)) and len(target_range) == 2:
            default_low, default_high = _f(target_range[0], 55.0), _f(target_range[1], 65.0)
        else:
            default_low, default_high = 55.0, 65.0
        return {
            "task_no": row.task_no,
            "run_id": row.run_id,
            "created_at": row.created_at,
            "device_id": device_id,
            # 复测读数来自土壤探头,不是执行终端(见 _pick_sensor)
            "sensor_id": _sensor_of(device_id),
            # 载荷不带基线(device_cmd 从来不带):引擎会退用 _baseline_before,
            # 再退用「复测前一个点」,两处都没有才判转人工
            "baseline": _f(payload.get("baseline")),
            "duration_s": _duration_of(payload),
            "target_low": _f(payload.get("target_low"), default_low),
            "target_high": _f(payload.get("target_high"), default_high),
            "round_no": int(payload.get("round_no", 1) or 1),
            "max_rounds": int(payload.get("max_rounds", 2) or 2),
        }


def _load_samples(task_no: str) -> list[float]:
    task = _load_task(task_no)
    values = _recent_values(task.get("sensor_id") or task["device_id"], SAMPLE_COUNT)
    return [float(v) for v, _ts in reversed(values)]


def _previous_value(task_no: str) -> Optional[float]:
    task = _load_task(task_no)
    values = _recent_values(task.get("sensor_id") or task["device_id"], SAMPLE_COUNT + 1)
    if len(values) <= SAMPLE_COUNT:
        return None
    return float(values[SAMPLE_COUNT][0])


def _history_stats(device_id: str) -> tuple[Optional[float], Optional[float]]:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.sensor_data import SensorData

    if not device_id:
        return (None, None)
    device_id = _sensor_of(device_id)   # 幂等:本来就是 soil 时原样返回
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
    device_id = _sensor_of(device_id)   # 幂等:本来就是 soil 时原样返回
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
            # 缺基线就写 NULL:0.00 会被报告页当成「实测基线 = 0」,那才是真的假数据
            baseline_value=None if getattr(result, "baseline_missing", False)
            else result.achievement.baseline,
            target_low=result.achievement.target_low,
            target_high=result.achievement.target_high,
            measured_value=result.achievement.measured,
            achievement=result.achievement.value,
            confidence=round(result.confidence.total * 100, 2),   # 表里 0-100
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
                "baseline": _f(v.baseline_value),            # NULL → None → 报告显示「—」
                "measured": _f(v.measured_value, 0.0),
                "achievement": _f(v.achievement, 0.0),
                "confidence": _f(v.confidence, 0.0) / 100.0,   # 渲染器按 0-1
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
        baseline_before=_baseline_before,
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
