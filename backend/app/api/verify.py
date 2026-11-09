"""验证（PRD 7.4 / 6.9）：手动触发验证 + 验证记录列表（报告页数据源）。

公式与三路置信度在队长的 verification/；这里只做触发与查询。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.verifications import Verification
from ._common import delegate, page_payload

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
        "created_at": v.created_at.isoformat(sep=" ", timespec="seconds") if v.created_at else None,
    }


@router.post("/{task_no}", summary="对某任务执行验证（调队长验证引擎）")
def verify(task_no: str) -> dict[str, Any]:
    verify_fn = delegate("app.verification.service", "verify_task", owner="队长")
    try:
        result = verify_fn(task_no)
    except TypeError:
        result = verify_fn(task_no=task_no)
    return {"task_no": task_no, "result": result}


@router.get("", summary="验证记录列表（红/黄/绿圆环的数据源）")
def list_verifications(
    task_no: str | None = None,
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
    if conclusion:
        conditions.append(Verification.conclusion == conclusion)
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Verification.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return page_payload([to_dict(r) for r in rows], total, page, page_size)
