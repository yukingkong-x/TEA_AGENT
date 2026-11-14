"""任务队列（PRD 7.4 / 13.4）：分页 + 状态过滤，任务中心页的数据源。"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.task_events import TaskEvent
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
        "deadline_at": t.deadline_at.isoformat(timespec="seconds") if t.deadline_at else None,
        "result": t.result_json,
        "created_at": t.created_at.isoformat(timespec="seconds") if t.created_at else None,
        "updated_at": t.updated_at.isoformat(timespec="seconds") if t.updated_at else None,
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


def event_to_dict(e: TaskEvent) -> dict[str, Any]:
    """轨迹事件 → 契约第 11 节字段。

    `at` 必须 `isoformat()` 带 T：`isoformat(sep=" ")` 产出的
    `2026-11-14 10:31:02` 在 Safari / iPad 上是 `Invalid Date`，
    演示机就是 Safari，别改回去。
    """
    return {
        "id": e.id,
        "event": e.event,
        "from": e.from_status,
        "to": e.to_status,
        "reason": e.reason,
        "actor": e.actor,
        "at": e.created_at.isoformat(timespec="seconds") if e.created_at else None,
        "payload": e.payload_json,
    }


@router.get("/{task_no}/events", summary="任务轨迹事件（轨迹抽屉，按时间正序）")
def list_task_events(
    task_no: str,
    limit: int = Query(100, ge=1, le=500, description="最多返回条数，从最早的事件开始"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """PRD 986「点任务行展开轨迹抽屉」。

    - **按 `id` 升序**（轨迹从旧到新），不要改成 `created_at` 排序：
      同一秒内可能连落多行（ack + 状态变更），按时间排会乱序；
    - `total` 是该任务的事件**总数**，不受 `limit` 影响 —— 前端据此判断是否被截断；
    - 任务不存在时 404，任务存在但还没事件时返回空数组：
      这两种情况要分清，否则前端分不出「任务号打错了」和「任务刚建还没跑」。
    """
    from ._common import ensure_found

    exists = db.scalar(select(Task.id).where(Task.task_no == task_no))
    ensure_found(exists, f"任务 {task_no}")

    total = db.scalar(select(func.count(TaskEvent.id)).where(TaskEvent.task_no == task_no)) or 0
    rows = db.scalars(
        select(TaskEvent)
        .where(TaskEvent.task_no == task_no)
        .order_by(TaskEvent.id.asc())
        .limit(limit)
    ).all()
    return {"items": [event_to_dict(r) for r in rows], "total": total}
