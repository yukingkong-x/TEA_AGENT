"""任务队列（PRD 7.4 / 13.4）：分页 + 状态过滤，任务中心页的数据源。"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.tasks import Task
from ._common import page_payload

router = APIRouter(prefix="/tasks", tags=["tasks"])


def to_dict(t: Task) -> dict[str, Any]:
    return {
        "id": t.id,
        "task_no": t.task_no,
        "run_id": t.run_id,
        "type": t.type,
        "payload": t.payload_json,
        "priority": t.priority,
        "score": float(t.score) if isinstance(t.score, Decimal) else t.score,
        "status": t.status,
        "assigned_agent": t.assigned_agent,
        "assigned_device": t.assigned_device,
        "retry_count": t.retry_count,
        "timeout_s": t.timeout_s,
        "deadline_at": t.deadline_at.isoformat(sep=" ", timespec="seconds") if t.deadline_at else None,
        "result": t.result_json,
        "created_at": t.created_at.isoformat(sep=" ", timespec="seconds") if t.created_at else None,
        "updated_at": t.updated_at.isoformat(sep=" ", timespec="seconds") if t.updated_at else None,
    }


@router.get("", summary="任务分页列表（任务中心）")
def list_tasks(
    status: str | None = Query(None, description="pending / dispatched / running / success / failed / timeout / retrying / dead / canceled"),
    type: str | None = Query(None, description="agent_call / device_cmd / verify / report / selfloop"),
    run_id: int | None = None,
    assigned_device: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Task)
    count_stmt = select(func.count(Task.id))
    filters = []
    if status:
        filters.append(Task.status == status)
    if type:
        filters.append(Task.type == type)
    if run_id is not None:
        filters.append(Task.run_id == run_id)
    if assigned_device:
        filters.append(Task.assigned_device == assigned_device)
    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(Task.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return page_payload([to_dict(r) for r in rows], total, page, page_size)


@router.get("/{task_no}", summary="单任务详情")
def get_task(task_no: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ._common import ensure_found

    row = db.scalar(select(Task).where(Task.task_no == task_no))
    return to_dict(ensure_found(row, f"任务 {task_no}"))
