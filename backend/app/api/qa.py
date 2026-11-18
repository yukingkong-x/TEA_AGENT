"""通用问答接口（用户自由提问）。

为什么单独开一个路由而不是复用 /knowledge/search：
检索只返回片段，用户要的是**答案**；也不塞进 /workflows/{id}/run，
那是跑固定 DAG 的，问一句话不该建一次执行实例。

失败一律降级返回（degraded=True + reason），不返回 500：
演示现场模型限流或知识库没起来时，页面应该还能显示「命中了哪些资料」，
而不是一个红色报错。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..qa import answer as answer_question

router = APIRouter(prefix="/qa", tags=["qa"])


class AskIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="用户问题（≤500 字）")
    top_k: int = Field(3, ge=1, le=8, description="检索几条资料作为依据")


@router.post("/ask", summary="自由提问（检索增强，带引用）")
async def ask(body: AskIn) -> dict[str, Any]:
    return await answer_question(body.question, top_k=body.top_k)
