"""工作流 CRUD + 手动触发 + 执行实例查询（PRD 7.4 / 6.4 / 6.5）。

引擎执行归队长：`POST /workflows/{id}/run` 会调用他提供的 start_run，
接口约定见 docs/contracts/api_seams.md（他没落地前返回 503，前端可以照常开发画布）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import seams
from ..core import node_records
from ..db import get_db, session_scope
from ..models.agent_messages import AgentMessage
from ..models.agents import Agent
from ..models.tasks import Task
from ..models.workflow_runs import WorkflowRun
from ..models.workflows import Workflow
from ._common import ensure_found, page_payload
from ._dag import validate_dag
from .tasks import to_dict as task_to_dict

router = APIRouter(tags=["workflows"])


class WorkflowIn(BaseModel):
    wf_key: str = Field(..., max_length=32)
    name: str = Field(..., max_length=64)
    dag_json: dict[str, Any]
    enabled: bool = True


class WorkflowPatch(BaseModel):
    name: str | None = Field(None, max_length=64)
    dag_json: dict[str, Any] | None = None
    enabled: bool | None = None


def _known_agents(db: Session) -> set[str]:
    return set(db.scalars(select(Agent.agent_key)).all())


def _validate_or_400(db: Session, dag: dict[str, Any]) -> None:
    """优先用队长引擎的校验（将来加了业务规则就以他为准），没有就用本地闸门。"""
    errors = seams.validate_dag(dag)  # 对面没提供时返回 None
    if errors is None:
        errors = validate_dag(dag, _known_agents(db))
    if errors:
        raise HTTPException(status_code=400, detail={"message": "dag_json 校验失败", "errors": errors})


def to_dict(w: Workflow) -> dict[str, Any]:
    return {
        "id": w.id,
        "wf_key": w.wf_key,
        "name": w.name,
        "version": w.version,
        "enabled": w.enabled,
        "dag_json": w.dag_json,
        "updated_at": w.updated_at.isoformat(timespec="seconds") if w.updated_at else None,
    }


def run_to_dict(r: WorkflowRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "wf_id": r.wf_id,
        "status": r.status,
        "trigger": r.trigger,
        "context": r.context_json,
        "started_at": r.started_at.isoformat(timespec="seconds") if r.started_at else None,
        "finished_at": r.finished_at.isoformat(timespec="seconds") if r.finished_at else None,
        "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else None,
    }


# ---------------------------------------------------------------- workflows
@router.get("/workflows", summary="工作流列表")
def list_workflows(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(Workflow).order_by(Workflow.id)).all()
    return [to_dict(r) for r in rows]


@router.get("/workflows/{wf_id}", summary="工作流详情")
def get_workflow(wf_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(Workflow, wf_id)
    return to_dict(ensure_found(row, f"工作流 {wf_id}"))


@router.post("/workflows", status_code=201, summary="新建工作流（保存前校验 DAG）")
def create_workflow(body: WorkflowIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if db.scalar(select(Workflow).where(Workflow.wf_key == body.wf_key)):
        raise HTTPException(status_code=409, detail=f"wf_key={body.wf_key} 已存在")
    _validate_or_400(db, body.dag_json)
    row = Workflow(wf_key=body.wf_key, name=body.name, dag_json=body.dag_json, version=1, enabled=body.enabled)
    db.add(row)
    db.commit()
    db.refresh(row)
    return to_dict(row)


@router.put("/workflows/{wf_id}", summary="修改工作流（version 自增）")
def update_workflow(wf_id: int, body: WorkflowPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(Workflow, wf_id)
    ensure_found(row, f"工作流 {wf_id}")
    if body.dag_json is not None:
        _validate_or_400(db, body.dag_json)
        row.dag_json = body.dag_json
        row.version = (row.version or 1) + 1
    if body.name is not None:
        row.name = body.name
    if body.enabled is not None:
        row.enabled = body.enabled
    db.commit()
    db.refresh(row)
    return to_dict(row)


@router.delete("/workflows/{wf_id}", summary="删除工作流")
def delete_workflow(wf_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(Workflow, wf_id)
    ensure_found(row, f"工作流 {wf_id}")
    db.delete(row)
    db.commit()
    return {"deleted": wf_id}


@router.post("/workflows/{wf_id}/run", summary="手动触发执行（调用队长的引擎，立即返回 run_id）")
async def run_workflow(wf_id: int, trigger: str = Query("manual")) -> dict[str, Any]:
    """必须是 async def。

    队长的 `start_run` 靠 `asyncio.get_running_loop().create_task()` 把执行放到后台，
    拿不到运行中的事件循环就退化成 `asyncio.run()`——**在请求线程里同步跑完整条工作流**。
    没配 LLM key 时是 0.1 秒的规则降级，看不出问题；一旦配上 key，14 个节点要跑一两分钟，
    前端点「运行」就是一个挂死的请求（还容易撞网关超时），画布也不会动。
    所以这里改成 async：预检（两次查库）丢线程池，`start_run` 回到事件循环里调度，接口立即返回。
    """

    def _precheck() -> None:
        with session_scope() as db:
            row = db.get(Workflow, wf_id)
            ensure_found(row, f"工作流 {wf_id}")
            if not row.enabled:
                raise HTTPException(status_code=400, detail="该工作流已停用")

    await asyncio.to_thread(_precheck)

    result = seams.start_run(wf_id, trigger)
    run_id = result.get("run_id") if isinstance(result, dict) else result
    return {"run_id": run_id, "wf_id": wf_id, "trigger": trigger, "raw": result}


# ---------------------------------------------------------------- runs
@router.get("/runs", summary="执行实例列表")
def list_runs(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(WorkflowRun)
    count_stmt = select(func.count(WorkflowRun.id))
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
        count_stmt = count_stmt.where(WorkflowRun.status == status)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(WorkflowRun.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return page_payload([run_to_dict(r) for r in rows], total, page, page_size)


@router.get("/runs/{run_id}", summary="执行详情（含任务轨迹、Agent 消息与节点耗时）")
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(WorkflowRun, run_id)
    ensure_found(run, f"执行实例 {run_id}")
    tasks = db.scalars(select(Task).where(Task.run_id == run_id).order_by(Task.id)).all()
    messages = db.scalars(
        select(AgentMessage).where(AgentMessage.run_id == run_id).order_by(AgentMessage.id)
    ).all()
    # 节点耗时表：表还没被引擎写过时是空数组，前端按「无节点数据」降级即可，
    # 不给 404——run 本身是存在的，只是没有节点级明细（历史 run 补不出来）。
    nodes = node_records.load_run_nodes(run_id)
    return {
        "run": run_to_dict(run),
        "tasks": [task_to_dict(t) for t in tasks],
        "messages": [
            {
                "id": m.id,
                "agent_key": m.agent_key,
                "role": m.role,
                "content": m.content,
                "tool_calls": m.tool_calls_json,
                "citations": m.citations_json,
                "tokens_in": m.tokens_in,
                "tokens_out": m.tokens_out,
                "latency_ms": m.latency_ms,
                "created_at": m.created_at.isoformat(timespec="seconds") if m.created_at else None,
            }
            for m in messages
        ],
        "nodes": nodes,
        "node_summary": node_records.summarize(nodes),
    }


@router.get("/runs/{run_id}/nodes", summary="节点级耗时（PRD 9.1 报告时间线）")
def get_run_nodes(run_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(WorkflowRun, run_id)
    ensure_found(run, f"执行实例 {run_id}")
    nodes = node_records.load_run_nodes(run_id)
    return {"run_id": run_id, "items": nodes, "summary": node_records.summarize(nodes)}
