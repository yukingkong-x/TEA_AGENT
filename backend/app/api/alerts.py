"""报警（PRD 7.4 / 6.11）：列表 + 人工确认。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.alerts import Alert
from ._common import ensure_found, page_payload

router = APIRouter(prefix="/alerts", tags=["alerts"])


def to_dict(a: Alert) -> dict[str, Any]:
    return {
        "id": a.id,
        "level": a.level,
        "source": a.source,
        "message": a.message,
        "acknowledged": a.acknowledged,
        "created_at": a.created_at.isoformat(timespec="seconds") if a.created_at else None,
    }


@router.get("", summary="报警列表")
def list_alerts(
    level: str | None = Query(None, description="info / warning / critical"),
    acknowledged: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Alert)
    count_stmt = select(func.count(Alert.id))
    conditions = []
    if level:
        conditions.append(Alert.level == level)
    if acknowledged is not None:
        conditions.append(Alert.acknowledged == acknowledged)
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Alert.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return page_payload([to_dict(r) for r in rows], total, page, page_size)


@router.post("/ack-all", summary="一键确认全部未确认报警")
def ack_all(
    source_prefix: str | None = Query(None, description="只清某类来源，如 device:（缺省清全部）"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """大屏「一键清除」：把当前所有未确认报警置为已确认。

    报警不删只 ack：留痕供复盘（PRD 6.11），确认动作本身也进审计口径。
    """
    stmt = update(Alert).where(Alert.acknowledged.is_(False))
    if source_prefix:
        stmt = stmt.where(Alert.source.like(f"{source_prefix}%"))
    result = db.execute(stmt.values(acknowledged=True))
    db.commit()
    return {"updated": int(result.rowcount or 0)}


@router.post("/{alert_id}/ack", summary="确认报警")
def ack_alert(alert_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(Alert, alert_id)
    ensure_found(row, f"报警 {alert_id}")
    row.acknowledged = True
    db.commit()
    db.refresh(row)
    return to_dict(row)
