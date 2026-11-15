"""REQ-F-003 MCP Server 测试(PRD 7.3:SSE 模式 /mcp 端点)。

被测契约:JSON-RPC 消息层(initialize / tools/list / tools/call / ping / 通知 / 未知方法)
与 SSE 传输(首帧 endpoint 事件 + POST 消息推送到会话队列)。
"""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.mcp_server import McpSseServer, handle_message
from app.agents.tools import build_default_registry

registry = build_default_registry()

PRD_TOOL_NAMES = {
    "get_weather", "get_soil_status", "get_env_status", "query_knowledge",
    "create_task", "send_device_cmd", "verify_result", "calc_achievement",
    "write_report", "raise_alert", "wait_penetration",
}


@pytest.mark.asyncio
async def test_initialize_returns_capabilities():
    # 断点:initialize 应答缺少协议版本/工具能力声明(MCP 客户端连不上)→ 本测试失败
    resp = await handle_message(registry, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": "2024-11-05",
                                                      "capabilities": {},
                                                      "clientInfo": {"name": "t", "version": "1"}}})
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in resp["result"]["capabilities"]


@pytest.mark.asyncio
async def test_notification_returns_none():
    # 断点:通知(无 id)被错误地当成请求回包 → 本测试失败
    resp = await handle_message(registry, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp is None


@pytest.mark.asyncio
async def test_tools_list_returns_all_tools_with_schemas():
    # 断点:工具清单与 7.3 契约不一致(缺工具/缺 schema)→ 本测试失败
    resp = await handle_message(registry, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = resp["result"]["tools"]
    assert {t["name"] for t in tools} == PRD_TOOL_NAMES
    for t in tools:
        assert t["description"]
        assert t["inputSchema"]["type"] == "object"


@pytest.mark.asyncio
async def test_tools_call_calc_achievement_returns_text_result():
    # 断点:tools/call 不能执行工具/返回结构错误 → 本测试失败
    resp = await handle_message(registry, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "calc_achievement",
                   "arguments": {"baseline": 38.5, "target_low": 55, "target_high": 65, "measured": 45.0}},
    })
    assert resp["result"]["isError"] is False
    assert json.loads(resp["result"]["content"][0]["text"]) == 39.39


@pytest.mark.asyncio
async def test_tools_call_unknown_tool_returns_is_error():
    # 断点:未知工具调用不报错(isError 丢失)→ 本测试失败
    resp = await handle_message(registry, {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "不存在的工具", "arguments": {}},
    })
    assert resp["result"]["isError"] is True


@pytest.mark.asyncio
async def test_tools_call_exception_returns_is_error():
    # 断点:工具抛异常时 MCP 层崩溃而非回 isError → 本测试失败
    resp = await handle_message(registry, {
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "send_device_cmd",
                   "arguments": {"device_id": "k10-act-03", "action": "pump", "params": {}}},
    })
    assert resp["result"]["isError"] is True
    assert "待接入" in resp["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_unknown_method_returns_rpc_error():
    # 断点:未实现方法没有 -32601 应答 → 本测试失败
    resp = await handle_message(registry, {"jsonrpc": "2.0", "id": 6, "method": "resources/list"})
    assert resp["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_ping_returns_empty_result():
    resp = await handle_message(registry, {"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert resp["result"] == {}


@pytest.mark.asyncio
async def test_sse_stream_emits_endpoint_event_first():
    # 断点:SSE 首帧不是 endpoint 事件(MCP 客户端无法发现消息地址)→ 本测试失败
    server = McpSseServer(registry)
    session = server.new_session()
    first = await anext(server.stream(session))
    assert first.startswith("event: endpoint")
    assert session.id in first  # data 里带会话 id


@pytest.mark.asyncio
async def test_post_message_executes_and_pushes_sse_event():
    # 断点:POST 消息不执行/不推送 SSE 事件(实时通道断)→ 本测试失败
    server = McpSseServer(registry)
    session = server.new_session()
    transport = ASGITransport(app=server.build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/mcp/messages?session_id={session.id}", json={
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "calc_achievement",
                       "arguments": {"baseline": 38.5, "target_low": 55, "target_high": 65, "measured": 57.0}},
        })
        assert resp.status_code == 200
        assert resp.json()["result"]["isError"] is False

    stream = server.stream(session)
    first = await anext(stream)   # endpoint 事件
    assert first.startswith("event: endpoint")
    second = await anext(stream)  # POST 触发的响应事件
    assert second.startswith("event: message")
    payload = json.loads(second.split("data: ", 1)[1])  # 事件载荷为 JSON-RPC 响应
    assert payload["result"]["isError"] is False
    assert json.loads(payload["result"]["content"][0]["text"]) == 100.0
