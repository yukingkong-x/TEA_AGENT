"""REQ-F-003 补充:工具执行期的 agent 身份上下文(PRD 6.11 报警 source)。

断点清单(这些断言挂了 = 报警来源会悄悄退化成 "agent",报警列表看不出是谁提的):
1. raise_alert 的 schema 里没有 source → LLM 传不进来,只能落默认值;
2. AgentRunner._execute_tool 没 set 身份 → 工具里读不到 agent_key;
3. set 之后没 reset → 同一个上下文里后续调用被上一个 Agent 污染。
"""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agents.base import AgentRunner
from app.agents.context import current_agent_key, current_agent_source
from app.agents.prompts import AGENTS
from app.agents.tools import ToolRegistry, build_default_registry


def test_source_defaults_to_agent_outside_runner():
    # 断点:不在 AgentRunner 工具循环内时,source 必须退回 "agent"(兼容旧数据)
    assert current_agent_key() == ""
    assert current_agent_source() == "agent"


def test_source_shape_is_agent_prefixed():
    # 断点:PRD 6.11 要求 agent:verifier 形态,不是裸 verifier
    from app.agents.context import CURRENT_AGENT_KEY

    token = CURRENT_AGENT_KEY.set("verifier")
    try:
        assert current_agent_source() == "agent:verifier"
    finally:
        CURRENT_AGENT_KEY.reset(token)
    assert current_agent_source() == "agent"


def test_raise_alert_schema_exposes_source():
    # 断点:schema 少了 source,LLM 永远只能落默认值(这条是 B 报的断点)
    spec = build_default_registry().get("raise_alert")
    assert spec is not None
    props = spec.parameters["properties"]
    assert "source" in props
    assert props["source"]["enum"] == [
        "scout", "weather", "soil", "pest", "decision", "executor", "verifier", "system",
    ]
    assert set(spec.parameters["required"]) == {"level", "message"}  # source 非必填


def test_execute_tool_carries_identity_and_resets():
    # 断点:工具执行期读不到 agent_key / 结束后 contextvar 残留
    seen: dict[str, str] = {}

    def probe(**_kwargs):
        seen["key"] = current_agent_key()
        seen["source"] = current_agent_source()
        return {"ok": True}

    spec = replace(AGENTS["verifier"], tools=["probe_tool"])
    registry = ToolRegistry({"verifier": spec})
    registry.register("probe_tool", "身份探针", {"type": "object", "properties": {}}, probe)
    runner = AgentRunner("verifier", llm=None, registry=registry, spec=spec)

    tc = SimpleNamespace(id="call_1", name="probe_tool", arguments={})
    record, payload = asyncio.run(runner._execute_tool(tc))

    assert record["status"] == "executed"
    assert seen == {"key": "verifier", "source": "agent:verifier"}
    assert current_agent_key() == ""  # finally 里 reset 了


def test_execute_tool_still_denies_unauthorized():
    # 断点:加身份上下文时把权限检查的顺序改坏了
    spec = replace(AGENTS["decision"], tools=["probe_tool"])
    registry = ToolRegistry({"decision": spec})
    registry.register("probe_tool", "身份探针", {"type": "object", "properties": {}}, lambda **_: {})

    runner = AgentRunner("decision", llm=None, registry=registry, spec=spec)
    tc = SimpleNamespace(id="call_2", name="send_device_cmd", arguments={})
    record, _ = asyncio.run(runner._execute_tool(tc))
    assert record["status"] == "denied"


def test_contextvar_is_shared_with_backend():
    """接缝铁律:合并后必须和基座是**同一个 ContextVar 对象**。

    两边各建一个 ContextVar 的话,runner set 的是 A、tool_impl 读的是 B,
    读到空值 → source 静默退化成 "agent",而且完全不报错,现场只能靠肉眼发现。
    """
    try:
        from app.core.tool_impl import CURRENT_AGENT_KEY as backend_var
    except ModuleNotFoundError:
        pytest.skip("基座 core/tool_impl.py 未合入(队长分支独立开发期),合并后此用例自动生效")

    from app.agents.context import CURRENT_AGENT_KEY as agent_var

    assert agent_var is backend_var
