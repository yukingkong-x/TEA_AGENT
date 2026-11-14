"""REQ-F-002 AgentRunner 运行时行为测试(PRD 8.3)。"""
import json

import pytest

from app.agents.base import AgentRunner, parse_sections
from app.agents.fallback import DEGRADED_PREFIX
from app.agents.prompts import AGENTS, AgentSpec
from app.agents.tools import ToolRegistry, build_default_registry
from app.core.llm import LLMResult, ToolCall


class FakeLLM:
    """double for LLMClient:按脚本出牌,记录每次调用入参。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, tools=None, temperature=0.3, max_tokens=None):
        self.calls.append({"messages": messages, "tools": tools, "temperature": temperature})
        return self.responses.pop(0)


def _runner(agent_key, responses, registry=None, get_context=None):
    return AgentRunner(
        agent_key=agent_key,
        llm=FakeLLM(responses),
        registry=registry or build_default_registry(),
        spec=AGENTS[agent_key],
        get_context=get_context,
    )


@pytest.mark.asyncio
async def test_history_over_ten_is_truncated_and_summarized():
    # 断点:历史超 10 条不截断/不压缩摘要(8.3 第 1 条)→ 本测试失败
    runner = _runner("scout", [LLMResult(content="收到")])
    history = [{"role": "user" if i % 2 else "assistant", "content": f"m{i}"} for i in range(12)]

    await runner.run(task="开始巡园", history=history)

    messages = runner.llm.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": AGENTS["scout"].system_prompt}
    non_system = [m for m in messages if m["role"] != "system"]
    history_msgs = [m for m in non_system if m["content"].startswith("m")]
    assert len(history_msgs) == 10          # 只保留最近 10 条
    assert history_msgs[0]["content"] == "m2"  # 最早的 2 条被压缩
    task_msg = non_system[-1]
    assert "[前文摘要]" in task_msg["content"]
    assert "开始巡园" in task_msg["content"]


@pytest.mark.asyncio
async def test_uses_spec_temperature_and_all_tool_schemas():
    # 断点:temperature 不按 8.1 分档 / 工具 schema 没传给 LLM → 本测试失败
    runner = _runner("scout", [LLMResult(content="ok")])
    await runner.run(task="t")
    call = runner.llm.calls[0]
    assert call["temperature"] == 0.3
    assert len(call["tools"]) == 11  # 全部工具 schema 下发,权限在执行时把关(PRD 7.3 拒绝留痕)


@pytest.mark.asyncio
async def test_unauthorized_tool_call_is_denied_and_recorded():
    # 断点:权限铁律被破坏(未授权工具被执行 / 拒绝不留痕)→ 本测试失败
    calls = []
    registry = ToolRegistry(bindings=AGENTS)
    registry.register("send_device_cmd", "下发指令", {"type": "object", "properties": {}},
                      lambda device_id, action, params: calls.append(action))
    runner = _runner("decision", [
        LLMResult(tool_calls=[ToolCall(id="call-1", name="send_device_cmd",
                                       arguments={"device_id": "k10-act-03", "action": "pump",
                                                  "params": {"duration_s": 30}},
                                       arguments_raw='{"device_id": "k10-act-03", "action": "pump", "params": {"duration_s": 30}}')]),
        LLMResult(content="【决策】无法执行,权限不足。"),
    ], registry=registry)

    turn = await runner.run(task="浇水")

    assert calls == []  # 工具从未真正执行
    assert turn.tool_calls == [{
        "id": "call-1", "name": "send_device_cmd",
        "arguments": {"device_id": "k10-act-03", "action": "pump", "params": {"duration_s": 30}},
        "status": "denied", "reason": "permission",
    }]
    assert turn.content == "【决策】无法执行,权限不足。"


@pytest.mark.asyncio
async def test_allowed_tool_call_is_executed_and_result_fed_back():
    # 断点:已授权工具不执行 / 工具结果不回填给 LLM → 本测试失败
    seen = []
    spec = AgentSpec(agent_key="tester", name="测试员", avatar="🧪",
                     system_prompt="你是测试员。", tools=["echo"])
    registry = ToolRegistry(bindings={"tester": spec})
    registry.register("echo", "回显", {"type": "object",
                                       "properties": {"text": {"type": "string"}}},
                      lambda text: seen.append(text) or {"echoed": text})
    runner = AgentRunner(agent_key="tester", llm=FakeLLM([
        LLMResult(tool_calls=[ToolCall(id="call-1", name="echo", arguments={"text": "hi"},
                                       arguments_raw='{"text": "hi"}')]),
        LLMResult(content="收到"),
    ]), registry=registry, spec=spec)

    turn = await runner.run(task="测试")

    assert seen == ["hi"]
    assert turn.tool_calls[0]["status"] == "executed"
    second_call_messages = runner.llm.calls[1]["messages"]
    tool_msg = [m for m in second_call_messages if m["role"] == "tool"][0]
    assert tool_msg["tool_call_id"] == "call-1"
    assert json.loads(tool_msg["content"]) == {"echoed": "hi"}
    assert turn.content == "收到"


@pytest.mark.asyncio
async def test_tool_loop_is_forced_after_six_rounds():
    # 断点:6 轮工具调用上限失效(死循环 / 提前强制输出)→ 本测试失败
    spec = AgentSpec(agent_key="tester", name="测试员", avatar="🧪",
                     system_prompt="你是测试员。", tools=["echo"])
    registry = ToolRegistry(bindings={"tester": spec})
    registry.register("echo", "回显", {"type": "object",
                                       "properties": {"text": {"type": "string"}}},
                      lambda text: text)
    responses = [LLMResult(tool_calls=[ToolCall(id=f"c{i}", name="echo",
                                                arguments={"text": f"t{i}"},
                                                arguments_raw='{}')])
                 for i in range(6)]
    runner = AgentRunner(agent_key="tester", llm=FakeLLM(responses),
                         registry=registry, spec=spec)

    turn = await runner.run(task="测试")

    assert len(runner.llm.calls) == 6  # 没有第 7 次调用
    assert "强制输出" in turn.content


@pytest.mark.asyncio
async def test_degraded_result_uses_rule_template_with_visible_marker():
    # 断点:降级时不走规则模板 / 不带"模型降级中"标记(20.2 + 7.2 徽章)→ 本测试失败
    runner = _runner("scout", [LLMResult(degraded=True, error="断网")],
                     get_context=lambda: {
                         "env_status": {"temperature_c": 24.6, "humidity_air": 63.2, "lux": 1250},
                         "soil_status": {"soil_moisture": 38.5, "trend": "平"},
                     })

    turn = await runner.run(task="开始巡园")

    assert turn.degraded is True
    assert turn.content.startswith(DEGRADED_PREFIX)
    assert "【巡园播报】" in turn.content
    assert "24.6" in turn.content
    assert "38.5" in turn.content


@pytest.mark.asyncio
async def test_output_parsing_extracts_named_sections():
    # 断点:【】格式提取被破坏(工作流依赖 sections 做路由)→ 本测试失败
    runner = _runner("scout", [LLMResult(content="【巡园播报】天气晴。\n【预警】霜冻。")])
    turn = await runner.run(task="t")
    assert turn.sections == {"巡园播报": "天气晴。", "预警": "霜冻。"}


def test_parse_sections_handles_plain_text():
    # 断点:无【】的内容解析崩溃 → 本测试失败
    assert parse_sections("没有格式的普通回复") == {}


# ── 降级路径:规则模板判了 irrigate,就真的要把任务建出来 ──────────────

class _AsyncRegistry:
    """只实现 Runner 用到的那两个方法;invoke 必须是 async(生产实现也是)。"""

    def __init__(self, soil=38.5):
        self.calls: list[tuple[str, dict]] = []
        self.soil = soil

    def can_use(self, agent_key, tool_name):
        return True

    def to_openai_schemas(self):
        return []

    async def invoke(self, name, params=None):
        self.calls.append((name, dict(params or {})))
        if name == "get_soil_status":
            return {"moisture": self.soil, "trend": "flat"}
        if name == "get_env_status":
            return {"temperature_c": 15, "humidity_air": 60, "lux": 500}
        if name == "get_weather":
            return {"rain_prob": 5, "frost_risk": "无"}
        if name == "create_task":
            return {"task_no": "task-degraded-0001"}
        return {}

    def names(self):
        return [n for n, _ in self.calls]


@pytest.mark.asyncio
async def test_degraded_decision_creates_task_with_baseline():
    """降级不是「只播报」:模板说浇 30 秒,就必须有一行任务落库。

    现场教训(run #9 之后):降级时决策官只输出文案不建单 → 执行管家/验证官全没单可做
    → 工作流显示 success,闭环却是断的。降级恰恰是赛题要看的能力。
    """
    registry = _AsyncRegistry(soil=38.5)
    runner = _runner("decision", [LLMResult(degraded=True)], registry=registry)

    turn = await runner.run(task="决定这轮要不要浇水")

    assert turn.degraded is True
    assert "create_task" in registry.names()
    created = [p for n, p in registry.calls if n == "create_task"][0]
    assert created["type"] == "device_cmd"
    assert created["payload"]["params"]["duration_s"] == 30
    assert created["payload"]["baseline"] == pytest.approx(38.5)   # 用真墒情,不用占位
    assert turn.tool_calls and turn.tool_calls[0]["status"] == "executed"


@pytest.mark.asyncio
async def test_degraded_decision_skips_task_when_soil_is_fine():
    registry = _AsyncRegistry(soil=62.0)     # 模板会判 none
    runner = _runner("decision", [LLMResult(degraded=True)], registry=registry)

    await runner.run(task="决定这轮要不要浇水")

    assert "create_task" not in registry.names()


def test_irrigate_regex_does_not_fire_on_negative_wording():
    from app.agents.base import IRRIGATE_RE
    from app.agents.fallback import decision_fallback

    assert IRRIGATE_RE.search(decision_fallback(soil_moisture=38.5))
    assert not IRRIGATE_RE.search(decision_fallback(soil_moisture=62.0))
    assert not IRRIGATE_RE.search("本轮无需灌溉,墒情适宜")
