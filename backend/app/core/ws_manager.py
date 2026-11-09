"""WebSocket 连接管理与广播（PRD 7.4：/ws/dashboard）。

两类调用者：
- 事件循环内（路由、调度循环）：`await manager.broadcast(payload)`
- 线程内（paho MQTT 回调、模拟器线程）：`manager.publish_threadsafe(payload)`
  → 内部用 asyncio.run_coroutine_threadsafe 丢回主循环，绝不跨线程 await。

统一消息格式：{"type": "...", "data": {...}, "ts": 1730700000}
type 全集：telemetry / device_status / task_status / agent_message /
          node_state / run_status / alert / mode_changed
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

from fastapi import WebSocket
from loguru import logger

WS_TYPES = {
    "telemetry",
    "device_status",
    "task_status",
    "agent_message",
    "node_state",
    "run_status",
    "alert",
    "mode_changed",
}


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ 生命周期
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """FastAPI 启动时把主事件循环交给管理器，线程侧广播全靠它。"""
        self._loop = loop
        logger.info("WS 管理器已绑定事件循环")

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("WS 连接建立，当前 {} 个客户端", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("WS 连接断开，剩余 {} 个客户端", len(self._connections))

    @property
    def client_count(self) -> int:
        return len(self._connections)

    # ------------------------------------------------------------ 广播
    @staticmethod
    def _envelope(msg_type: str, data: Any) -> str:
        if msg_type not in WS_TYPES:
            logger.warning("未知 WS 消息类型 {}（仍会广播，请检查 PRD 7.4）", msg_type)
        return json.dumps(
            {"type": msg_type, "data": data, "ts": int(time.time())},
            ensure_ascii=False,
            default=str,
        )

    async def broadcast(self, msg_type: str, data: Any) -> None:
        if not self._connections:
            return
        text = self._envelope(msg_type, data)
        async with self._lock:
            targets = list(self._connections)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
            logger.debug("清理 {} 个失效 WS 连接", len(dead))

    def publish_threadsafe(self, msg_type: str, data: Any) -> None:
        """线程安全广播：paho 回调线程 / 模拟器线程调用。"""
        if not self._connections:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(msg_type, data), loop)
        except Exception as exc:  # pragma: no cover
            logger.warning("WS 线程广播失败：{}", exc)


manager = ConnectionManager()
