"""FastAPI 入口（PRD 7.1 / 7.5）。

启动顺序：日志 → 建表 → 种子 → WS 管理器绑定循环 → MQTT → 模拟器（Mock）→ 巡检线程
           → 关闭时反序收尾
队长的调度循环（orchestrator.scheduler）接在 bootstrap.start_all() 里的一行即可。
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from . import bootstrap, seams
from .api import api_router
from .api.ws import router as ws_router
from .config import get_settings
from .db import init_db, session_scope
from .logging_conf import setup_logging
from .seed import seed_defaults

setup_logging()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 64)
    logger.info("{} v{} 启动中", settings.app_name, settings.app_version)
    logger.info("MySQL {}:{}/{} ｜ Redis {}:{} ｜ MQTT {}:{}",
                settings.mysql_host, settings.mysql_port, settings.mysql_database,
                settings.redis_host, settings.redis_port, settings.mqtt_host, settings.mqtt_port)

    init_db()
    with session_scope() as db:
        stats = seed_defaults(db)
    logger.info("种子检查：devices +{}，settings +{}", stats["devices"], stats["settings"])

    if not settings.llm_ready:
        logger.warning("未配置 LLM API Key —— 平台将进入规则降级模式（PRD 20.2）")

    bootstrap.start_all(asyncio.get_running_loop())
    seams.log_status()
    logger.info("后端就绪：http://127.0.0.1:{}/docs", settings.backend_port)
    logger.info("=" * 64)

    try:
        yield
    finally:
        bootstrap.stop_all()
        logger.info("后端关闭")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="茶园多智能体编排平台 · 后端（队友B 基座线）",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ws_router)  # /ws/dashboard 不带 /api 前缀


@app.exception_handler(seams.SeamNotReady)
async def seam_not_ready_handler(request: Request, exc: seams.SeamNotReady) -> JSONResponse:
    """跨地盘模块没接上 → 503 + 人话，前端据此显示「模块未就绪」而不是白屏 500。"""
    logger.warning("接缝未就绪 {} {} → {}", request.method, request.url.path, exc.detail)
    return JSONResponse(
        status_code=503,
        content={"detail": exc.detail, "seam": exc.seam, "code": "SEAM_NOT_READY"},
    )


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/api/health",
        "ws": "/ws/dashboard",
    }
