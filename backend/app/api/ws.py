"""WebSocket /ws/dashboard（PRD 7.4）。

注意：这个路由**不带 /api 前缀**，在 main.py 里单独挂载。
前端连上后不需要再轮询：遥测、任务状态、Agent 消息、节点动画、报警、模式切换全走这里。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from ..core.runtime_settings import get_mode
from ..core.security import check_ws_token
from ..core.ws_manager import manager

router = APIRouter(tags=["ws"])


@router.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket, token: str | None = None) -> None:
    if not check_ws_token(token):
        await ws.close(code=4401)
        return

    await manager.connect(ws)
    try:
        # 首帧：把当前模式与客户端数推给新人，前端据此点亮顶部状态条
        await ws.send_json(
            {
                "type": "mode_changed",
                "data": {"mode": get_mode(), "clients": manager.client_count, "hello": True},
                "ts": 0,
            }
        )
        while True:
            # 客户端心跳（前端 20s 发一次 {"type":"ping"}），同时用于探测断线
            raw = await ws.receive_text()
            if raw and "ping" in raw:
                await ws.send_json({"type": "pong", "data": {"clients": manager.client_count}, "ts": 0})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("WS 异常断开：{}", exc)
    finally:
        await manager.disconnect(ws)


@router.get("/ws/stats", include_in_schema=False)
def ws_stats() -> dict[str, Any]:
    return {"clients": manager.client_count}
