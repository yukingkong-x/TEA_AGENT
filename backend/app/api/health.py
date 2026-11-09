"""健康检查（Docker healthcheck 依赖此端点，勿删）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from .. import db
from ..config import get_settings
from ..core import mqtt_client
from ..core.redis_client import ping as redis_ping
from ..core.runtime_settings import get_mode
from ..core.ws_manager import manager
from ..mock.simulator import simulator

router = APIRouter(tags=["system"])
settings = get_settings()


@router.get("/health", summary="健康检查")
def health() -> dict:
    db_ok = db.ping()
    redis_ok = redis_ping()
    mqtt_ok = mqtt_client.is_connected()
    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "db": "up" if db_ok else "down",
        "redis": "up" if redis_ok else "down",
        "mqtt": "up" if mqtt_ok else "down",
        "mode": get_mode(),
        "simulator": simulator.running,
        "ws_clients": manager.client_count,
        "llm_ready": settings.llm_ready,
        "version": settings.app_version,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
