"""报告（PRD 7.4 / 6.12）：列表、详情、生成。

Markdown 生成本体在队长手里（F-022 报告生成后端半），约定接口：
    app.verification.report.generate_report(run_id: int) -> int   # 返回 report_id
兼容备选：app.reports.generator.generate_report
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import seams
from ..db import get_db
from ..models.reports import Report
from ._common import ensure_found, page_payload

router = APIRouter(prefix="/reports", tags=["reports"])


def to_summary(r: Report) -> dict[str, Any]:
    return {
        "id": r.id,
        "run_id": r.run_id,
        "report_type": r.report_type,
        "stats": r.stats_json,
        "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else None,
    }


@router.get("", summary="报告列表")
def list_reports(
    run_id: int | None = None,
    report_type: str | None = Query(None, description="daily / run"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Report)
    count_stmt = select(func.count(Report.id))
    conditions = []
    if run_id is not None:
        conditions.append(Report.run_id == run_id)
    if report_type:
        conditions.append(Report.report_type == report_type)
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Report.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return page_payload([to_summary(r) for r in rows], total, page, page_size)


@router.get("/{report_id}", summary="报告详情（Markdown 全文）")
def get_report(report_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(Report, report_id)
    ensure_found(row, f"报告 {report_id}")
    return {**to_summary(row), "content_md": row.content_md}


@router.post("/generate", summary="为某次执行生成报告（调队长生成器）")
def generate_report(run_id: int = Query(..., description="执行实例 id"), db: Session = Depends(get_db)) -> dict[str, Any]:
    result = seams.generate_report(run_id)
    report_id = result.get("report_id") if isinstance(result, dict) else result
    return {"run_id": run_id, "report_id": report_id}
