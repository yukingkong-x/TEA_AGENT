"""验证（PRD 7.4 / 6.9）：手动触发验证 + 验证记录列表（报告页数据源）。

公式与三路置信度在队长的 verification/；这里只做触发与查询。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import seams
from ..core import task_trail
from ..db import get_db
from ..models.tasks import Task
from ..models.verifications import Verification
from ._common import page_payload

router = APIRouter(prefix="/verify", tags=["verify"])


def to_dict(v: Verification) -> dict[str, Any]:
    def num(x):
        return float(x) if isinstance(x, Decimal) else x

    return {
        "id": v.id,
        "run_id": v.run_id,
        "task_no": v.task_no,
        "baseline_value": num(v.baseline_value),
        "target_low": num(v.target_low),
        "target_high": num(v.target_high),
        "measured_value": num(v.measured_value),
        "achievement": num(v.achievement),
        "confidence": num(v.confidence),
        "conf_detail": v.conf_detail_json,
        "conclusion": v.conclusion,
        "created_at": v.created_at.isoformat(timespec="seconds") if v.created_at else None,
    }


# 验证结论 → 任务终态。needs_human 是终态（PRD 10.2），不进调度器的扫描集，不会被自动重试。
_VERDICT_TO_STATUS = {"success": "success", "failed": "failed", "needs_human": "needs_human"}


def _apply_verdict(db: Session, task_no: str, result: dict[str, Any] | None) -> str | None:
    """把验证结论落成任务终态。

    为什么由这里写：验证引擎是依赖注入式的、不碰 ORM（队长那条线刻意不 import 基座的
    models），所以「任务状态谁改」只能落在基座这一层。不写的话任务会一直停在 running，
    60s 后调度器判超时 → 重试 → 再次超时，形成一轮假的自我重试，大屏上看起来像在反复失败。
    """
    verdict = str((result or {}).get("verdict") or "").strip().lower()
    status = _VERDICT_TO_STATUS.get(verdict)
    if status is None:
        return None

    task = db.scalar(select(Task).where(Task.task_no == task_no))
    if task is None:
        return None

    prev_status = task.status
    task.status = status
    # 合并而非覆盖：result_json 里可能已有 ack 明细（指令结果），验证结论是增量信息
    merged = dict(task.result_json or {})
    merged.update(
        {
            "verdict": verdict,
            "verification_id": (result or {}).get("verification_id"),
            "achievement": (result or {}).get("achievement"),
            "confidence": (result or {}).get("confidence"),
            "note": (result or {}).get("note"),
        }
    )
    task.result_json = merged
    # 轨迹：这是「验证官改了任务终态」这一跳的落点。event 用 verify 而不是 task_status，
    # 因为抽屉要一眼看出「这条是判出来的，不是调度器派发的」；reason 存 verdict，
    # 前端仍按 from/to 画边（见契约第 11 节）。
    task_trail.record(
        db,
        task_no=task.task_no,
        event="verify",
        from_status=prev_status,
        to_status=status,
        reason=verdict,
        actor="verifier",
        run_id=task.run_id,
        payload={
            "verification_id": merged.get("verification_id"),
            "achievement": merged.get("achievement"),
            "confidence": merged.get("confidence"),
            "note": merged.get("note"),
        },
    )
    db.commit()
    return status


@router.post("/{task_no}", summary="对某任务执行验证（调队长验证引擎）并回写任务终态")
def verify(task_no: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = seams.verify_task(task_no)
    applied = _apply_verdict(db, task_no, result)
    if applied:
        logger.info("验证 {} → 任务终态 {}", task_no, applied)
    return {"task_no": task_no, "result": result, "task_status": applied}


@router.get("", summary="验证记录列表（红/黄/绿圆环的数据源）")
def list_verifications(
    task_no: str | None = None,
    run_id: int | None = Query(None, description="只取某次执行下的验证记录（报告页按轮次渲染）"),
    conclusion: str | None = Query(None, description="success / failed / needs_human"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Verification)
    count_stmt = select(func.count(Verification.id))
    conditions = []
    if task_no:
        conditions.append(Verification.task_no == task_no)
    if run_id is not None:
        conditions.append(Verification.run_id == run_id)
    if conclusion:
        conditions.append(Verification.conclusion == conclusion)
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Verification.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return page_payload([to_dict(r) for r in rows], total, page, page_size)
