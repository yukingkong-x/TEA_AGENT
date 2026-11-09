"""REQ-F-003:MCP Server(SSE 模式,PRD 7.3)——工具池对外暴露端点,赛题加分项。

- 实现 MCP 协议 2024-11-05 的最小可用子集:initialize / ping / tools/list / tools/call;
- 传输:HTTP + SSE(GET /mcp/sse 建立流,POST /mcp/messages 发 JSON-RPC);
- 由队友 B 在 main.py 挂载:app.include_router(server.build_app())。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from app.agents.tools import ToolRegistry

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "zhiqiu-tool-pool", "version": "0.1.0"}


async def handle_message(registry: ToolRegistry, payload: dict) -> Optional[dict]:
    """处理一条 JSON-RPC 消息;通知(无 id)返回 None,请求返回应答 dict。"""
    method = payload.get("method")
    msg_id = payload.get("id")
    if msg_id is None:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        tools = [
            {"name": t.name, "description": t.description, "inputSchema": t.parameters}
            for name in registry.names()
            for t in [registry.get(name)]
        ]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}
    if method == "tools/call":
        params = payload.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            result = await registry.invoke(name, arguments)
            text = json.dumps(result, ensure_ascii=False, default=str)
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as exc:  # noqa: BLE001 MCP 层必须把错误回给客户端,不能崩连接
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True}}
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}


class McpSession:
    def __init__(self, session_id: str):
        self.id = session_id
        self.queue: asyncio.Queue = asyncio.Queue()


class McpSseServer:
    """SSE 传输:GET 建立事件流,POST 收 JSON-RPC 并把应答推回会话队列。"""

    def __init__(self, registry: ToolRegistry, sse_path: str = "/mcp/sse", messages_path: str = "/mcp/messages"):
        self.registry = registry
        self.sse_path = sse_path
        self.messages_path = messages_path
        self._sessions: dict[str, McpSession] = {}

    def new_session(self) -> McpSession:
        session = McpSession(uuid4().hex)
        self._sessions[session.id] = session
        return session

    async def stream(self, session: McpSession):
        """SSE 事件流:首帧 endpoint(告知客户端消息地址),此后逐条吐队列事件。"""
        yield f"event: endpoint\ndata: {self.messages_path}?session_id={session.id}\n\n"
        while True:
            event = await session.queue.get()
            yield f"event: message\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    def build_app(self):
        """构建 FastAPI 应用(队友 B 在 main.py 里 mount)。"""
        app = FastAPI(title="zhiqiu MCP", docs_url=None, redoc_url=None)

        @app.get(self.sse_path)
        async def sse_endpoint():
            session = self.new_session()
            return StreamingResponse(self.stream(session), media_type="text/event-stream")

        @app.post(self.messages_path)
        async def messages_endpoint(request: Request):
            payload = await request.json()
            response = await handle_message(self.registry, payload)
            if response is not None:
                session_id = request.query_params.get("session_id")
                session = self._sessions.get(session_id) if session_id else None
                if session is not None:
                    session.queue.put_nowait(response)
                return response
            return {}

        return app
