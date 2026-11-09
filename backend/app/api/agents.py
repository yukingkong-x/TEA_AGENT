"""Agent 配置 CRUD（PRD 7.4，REQ-F-002）。

提示词正文由队长写入；这里只做配置的读写，改完下一轮立即生效（AgentRunner 每轮读表）。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.agents import Agent
from ._common import ensure_found

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentIn(BaseModel):
    agent_key: str = Field(..., max_length=32)
    name: str = Field(..., max_length=32)
    avatar: str | None = Field(None, max_length=8)
    system_prompt: str | None = None
    tools_json: list[str] | None = None
    model: str | None = Field(None, max_length=64)
    temperature: float = 0.3
    enabled: bool = True


class AgentPatch(BaseModel):
    name: str | None = Field(None, max_length=32)
    avatar: str | None = Field(None, max_length=8)
    system_prompt: str | None = None
    tools_json: list[str] | None = None
    model: str | None = Field(None, max_length=64)
    temperature: float | None = None
    enabled: bool | None = None


def to_dict(a: Agent) -> dict[str, Any]:
    return {
        "id": a.id,
        "agent_key": a.agent_key,
        "name": a.name,
        "avatar": a.avatar,
        "system_prompt": a.system_prompt,
        "tools_json": a.tools_json or [],
        "model": a.model,
        "temperature": float(a.temperature) if isinstance(a.temperature, Decimal) else a.temperature,
        "enabled": a.enabled,
        "updated_at": a.updated_at.isoformat(sep=" ", timespec="seconds") if a.updated_at else None,
    }


@router.get("", summary="Agent 列表")
def list_agents(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(Agent).order_by(Agent.id)).all()
    return [to_dict(r) for r in rows]


@router.get("/{agent_key}", summary="单个 Agent")
def get_agent(agent_key: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.scalar(select(Agent).where(Agent.agent_key == agent_key))
    return to_dict(ensure_found(row, f"Agent {agent_key}"))


@router.post("", status_code=201, summary="新增 Agent")
def create_agent(body: AgentIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    exists = db.scalar(select(Agent).where(Agent.agent_key == body.agent_key))
    if exists is not None:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail=f"agent_key={body.agent_key} 已存在")
    row = Agent(
        agent_key=body.agent_key,
        name=body.name,
        avatar=body.avatar,
        system_prompt=body.system_prompt,
        tools_json=body.tools_json,
        model=body.model,
        temperature=Decimal(str(body.temperature)),
        enabled=body.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return to_dict(row)


@router.put("/{agent_key}", summary="修改 Agent（改提示词即时生效）")
def update_agent(agent_key: str, body: AgentPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.scalar(select(Agent).where(Agent.agent_key == agent_key))
    ensure_found(row, f"Agent {agent_key}")
    data = body.model_dump(exclude_unset=True)
    if "temperature" in data and data["temperature"] is not None:
        data["temperature"] = Decimal(str(data["temperature"]))
    for key, value in data.items():
        if value is not None:
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return to_dict(row)


@router.delete("/{agent_key}", summary="删除 Agent")
def delete_agent(agent_key: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.scalar(select(Agent).where(Agent.agent_key == agent_key))
    ensure_found(row, f"Agent {agent_key}")
    db.delete(row)
    db.commit()
    return {"deleted": agent_key}
