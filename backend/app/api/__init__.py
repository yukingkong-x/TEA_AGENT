"""REST 路由聚合（PRD 7.4，前缀 /api）。

WebSocket 不带 /api 前缀，在 main.py 里单独挂载。
"""
from __future__ import annotations

from fastapi import APIRouter

from .agents import router as agents_router
from .alerts import router as alerts_router
from .devices import router as devices_router
from .health import router as health_router
from .knowledge import router as knowledge_router
from .reports import router as reports_router
from .sensor import router as sensor_router
from .settings import router as settings_router
from .tasks import router as tasks_router
from .verify import router as verify_router
from .workflows import router as workflows_router

api_router = APIRouter(prefix="/api")
for _router in (
    health_router,
    agents_router,
    workflows_router,
    tasks_router,
    devices_router,
    sensor_router,
    knowledge_router,
    verify_router,
    reports_router,
    settings_router,
    alerts_router,
):
    api_router.include_router(_router)

__all__ = ["api_router"]
