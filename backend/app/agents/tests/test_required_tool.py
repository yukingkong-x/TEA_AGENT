"""「说了要动手」必须变成真 tool_call(PRD 8.3 / 2026-11-14 现场)。

run #9 与 run #13 两次实测:glm-4-flash 把 create_task 的参数连同任务号
「task-xxx」一起写进正文,tool_calls 却是空的 —— 库里一行任务都没有,
执行管家没单可下、验证官拿假号查不到任务,而工作流状态是 success。
提示词强调不管用,客户端把 tool_choice 钉到具体函数才收得住。
"""
import pytest

from app.agents.base import AgentRunner, _supports_tool_choice
from app.agents.fallback import decision_fallback, scout_fallback
from app.agents.prompts import AGENTS
from app.core.llm import LLMResult, ToolCall


class ChoiceLLM:
    """记录 tool_choice 的 LLM 替身;生产的 core/llm.py 打过补丁后也是这个签名。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, messages, tools=None, temperature=0.3,
                       max_tokens=None, tool_choice=None):
        self.calls.append({"messages": messages, "tools": tools,
                           "temperature": temperature, "tool_choice": tool_choice})
        return self.responses.pop(0)


class OldLLM:
    """没打补丁的旧客户端:没有 tool_choice 形参。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, messages, tools=None, temperature=0.3, max_tokens=None):
        self.calls.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


class Registry:
    def __init__(self, task_no="task-20261114-0101", moisture=38.5, env=None):
        self.task_no = task_no
        self.moisture = moisture
        self.env = env or {}
        self.calls: list[tuple[str, dict]] = []

    def can_use(self, agent_key, tool_name):
        return True

    def to_openai_schemas(self):
        def _fn(name, desc):
            return {"type": "function",
                    "function": {"name": name, "description": desc,
                                 "parameters": {"type": "object", "properties": {}}}}
        return [_fn("create_task", "建任务"), _fn("get_soil_status", "查墒情"),
                _fn("get_env_status", "查环控"), _fn("get_weather", "查天气")]

    async def invoke(self, name, params=None):
        self.calls.append((name, dict(params or {})))
        if name == "create_task":
            return {"task_no": self.task_no, "status": "pending"}
        if name == "get_soil_status":
            return {"moisture": self.moisture, "trend_per_min": 0.4}
        if name == "get_env_status":
            return self.env or {"readings": {"temperature_c": {"value": 15.2},
                                             "humidity_air": {"value": 61.0},
                                             "lux": {"value": 820}}}
        if name == "get_weather":
            return {"rain_prob": 5, "frost_risk": "无"}
        return {}

    def names(self):
        return [name for name, _ in self.calls]


def _runner(agent_key, llm, registry):
    return AgentRunner(agent_key=agent_key, llm=llm, registry=registry, spec=AGENTS[agent_key])


@pytest.mark.asyncio
async def test_decision_text_only_is_pinned_to_create_task():
    llm = ChoiceLLM([
        LLMResult(content="【决策】本轮决策:irrigate。\n"
                          "方案:对A区执行浇水45秒,目标湿度55-65%,优先级6。任务 task-xxx。"),
        LLMResult(tool_calls=[ToolCall(
            id="call-9", name="create_task",
            arguments={"type": "device_cmd", "payload": {"params": {"duration_s": 45}}},
            arguments_raw='{"type": "device_cmd"}')]),
    ])
    registry = Registry()

    turn = await _runner("decision", llm, registry).run(task="决定这轮要不要浇水")

    # 第二次调用把 choice 钉在 create_task 上,并且只下发这一个 schema
    assert len(llm.calls) == 2
    assert llm.calls[1]["tool_choice"] == {"type": "function",
                                          "function": {"name": "create_task"}}
    assert [s["function"]["name"] for s in llm.calls[1]["tools"]] == ["create_task"]
    # 真的执行了,不是只记一笔
    assert registry.names().count("create_task") == 1
    assert turn.tool_calls[0]["status"] == "executed"
    assert turn.tool_calls[0]["result"]["task_no"] == "task-20261114-0101"
    # 正文里的占位号换成真号,否则验证官永远查不到任务
    assert "task-20261114-0101" in turn.content
    assert "task-xxx" not in turn.content


@pytest.mark.asyncio
async def test_no_decision_does_not_force_create_task():
    llm = ChoiceLLM([LLMResult(content="【决策】本轮决策:none。墒情适宜。")])
    registry = Registry(moisture=62.0)

    turn = await _runner("decision", llm, registry).run(task="决定")

    assert len(llm.calls) == 1              # 没有补一轮
    assert "create_task" not in registry.names()
    assert turn.content.startswith("【决策】本轮决策:none")


@pytest.mark.asyncio
async def test_agent_that_already_called_create_task_is_not_forced_again():
    llm = ChoiceLLM([
        LLMResult(content="【决策】本轮决策:irrigate。",
                  tool_calls=[ToolCall(id="c1", name="create_task",
                                       arguments={"type": "device_cmd"},
                                       arguments_raw='{"type": "device_cmd"}')]),
        LLMResult(content="【决策】已下单 task-20261114-0101,开始执行。"),
    ])
    registry = Registry()

    await _runner("decision", llm, registry).run(task="决定")

    assert len(llm.calls) == 2              # 建单 + 收尾播报,没有第三个「钉住」调用
    assert all(call["tool_choice"] is None for call in llm.calls)
    assert registry.names().count("create_task") == 1     # 只建一次,不会重复浇水


@pytest.mark.asyncio
async def test_old_llm_without_tool_choice_still_narrows_tools():
    """core/llm.py 没打补丁时也不能白跑:收窄工具集再试一次,并留下告警。"""
    llm = OldLLM([
        LLMResult(content="【决策】本轮决策:irrigate。任务 task-xxx。"),
        LLMResult(tool_calls=[ToolCall(id="c1", name="create_task",
                                       arguments={"type": "device_cmd"},
                                       arguments_raw='{"type": "device_cmd"}')]),
    ])
    registry = Registry()

    turn = await _runner("decision", llm, registry).run(task="决定")

    assert len(llm.calls) == 2
    assert [s["function"]["name"] for s in llm.calls[1]["tools"]] == ["create_task"]
    assert turn.tool_calls[0]["status"] == "executed"


def test_supports_tool_choice_detection():
    assert _supports_tool_choice(ChoiceLLM([])) is True
    assert _supports_tool_choice(OldLLM([])) is False
    assert _supports_tool_choice(object()) is False


@pytest.mark.asyncio
async def test_degraded_decision_without_soil_data_escalates():
    """缺数据不许当 100%:原来缺省 100.0 → 永远 none、一个任务都不建,且看不出缺数据。"""
    registry = Registry(moisture=None)
    turn = await _runner("decision", ChoiceLLM([LLMResult(degraded=True)]), registry).run(task="决定")

    assert turn.degraded is True
    assert "escalate" in turn.content
    assert "create_task" not in registry.names()


def test_decision_fallback_without_data_is_escalate():
    text = decision_fallback(soil_moisture=None)
    assert "escalate" in text
    assert "irrigate" not in text


def test_scout_fallback_reads_nested_readings():
    """基座的 env_status 是 readings[metric].value 嵌套形态,原来直接 KeyError。"""
    text = scout_fallback(
        {"readings": {"temperature_c": {"value": 15.2},
                      "humidity_air": {"value": 61.0},
                      "lux": {"value": 820}}},
        {"moisture": 38.5},
    )
    assert "15.2" in text and "61.0" in text and "820" in text and "38.5" in text


# ── 建单必须带 device_id,否则任务派不出去 ────────────────────────────

@pytest.mark.asyncio
async def test_created_task_is_filled_with_executor_device():
    """模型不会填 device_id;落地后 assigned_device 为空 → 调度器派不出去 → 那张单永不动。"""
    from app.agents.context import reset_executor_device, set_executor_device

    token = set_executor_device("mock-k10-act-03")
    try:
        llm = ChoiceLLM([
            LLMResult(content="【决策】本轮决策:irrigate。方案:浇水45秒。"),
            LLMResult(tool_calls=[ToolCall(
                id="c1", name="create_task",
                arguments={"type": "device_cmd", "priority": 6,
                           "payload": {"action": "pump", "params": {"duration_s": 45}}},
                arguments_raw='{}')]),
        ])
        registry = Registry()
        await _runner("decision", llm, registry).run(task="决定")
    finally:
        reset_executor_device(token)

    arguments = [params for name, params in registry.calls if name == "create_task"][0]
    assert arguments["payload"]["device_id"] == "mock-k10-act-03"
    assert arguments["payload"]["params"]["duration_s"] == 45     # 其余参数不动


@pytest.mark.asyncio
async def test_explicit_device_id_is_not_overwritten():
    from app.agents.context import reset_executor_device, set_executor_device

    token = set_executor_device("mock-k10-act-03")
    try:
        llm = ChoiceLLM([
            LLMResult(content="【决策】本轮决策:irrigate。"),
            LLMResult(tool_calls=[ToolCall(
                id="c1", name="create_task",
                arguments={"type": "device_cmd",
                           "payload": {"action": "pump", "device_id": "k10-act-03"}},
                arguments_raw='{}')]),
        ])
        registry = Registry()
        await _runner("decision", llm, registry).run(task="决定")
    finally:
        reset_executor_device(token)

    arguments = [params for name, params in registry.calls if name == "create_task"][0]
    assert arguments["payload"]["device_id"] == "k10-act-03"       # 模型自己填的优先


@pytest.mark.asyncio
async def test_send_device_cmd_is_filled_with_current_task_no():
    """执行管家的 schema 里没有 task_no(PRD 7.3),模型可能不填。

    run #19 实测:没填 → 基座认领失败(那张单已有 assigned_device)→ send_cmd 另建
    一张新单,决策单超时变 dead、真执行的单与 run 脱钩。任务号由引擎给,不指望模型。
    """
    from app.agents.context import reset_current_task_no, set_current_task_no

    class CmdRegistry(Registry):
        def to_openai_schemas(self):
            return [{"type": "function",
                     "function": {"name": "send_device_cmd", "description": "下发",
                                  "parameters": {"type": "object", "properties": {}}}}]

        async def invoke(self, name, params=None):
            self.calls.append((name, dict(params or {})))
            return {"task_no": (params or {}).get("task_no", ""), "published": True}

    token = set_current_task_no("task-20261114-0011")
    try:
        llm = ChoiceLLM([
            LLMResult(content="", tool_calls=[ToolCall(
                id="c1", name="send_device_cmd",
                arguments={"device_id": "mock-k10-act-03",
                           "action": "pump",
                           "params": {"duration_s": 45}},
                arguments_raw='{}')]),
            LLMResult(content="【执行反馈】任务已下发。"),
        ])
        registry = CmdRegistry()
        await _runner("executor", llm, registry).run(task="下发")
    finally:
        reset_current_task_no(token)

    arguments = registry.calls[0][1]
    assert arguments["task_no"] == "task-20261114-0011"      # 补上了
    assert arguments["action"] == "pump"                     # 其余参数不动


def test_engine_binds_task_no_for_downstream_executor():
    """决策节点落地后,执行管家节点的工具调用应带同一张单。"""
    import asyncio

    from app.agents.context import current_task_no
    from app.workflow.engine import WorkflowEngine

    seen: dict[str, str] = {}

    class DecisionRunner:
        async def run(self, task, upstream=None):
            return AgentTurnFactory("decision", "【决策】本轮决策:irrigate。方案:浇水30秒。")

    class ExecutorRunner:
        async def run(self, task, upstream=None):
            seen["task_no_ctx"] = current_task_no()
            return AgentTurnFactory("executor", "【执行反馈】已下发。")

    from app.agents.base import AgentTurn

    def AgentTurnFactory(agent_key, content):
        return AgentTurn(agent_key=agent_key, content=content)

    dag = {
        "wf_key": "task_bind", "name": "任务号绑定",
        "nodes": [
            {"id": "n1", "type": "start", "name": "开始", "next": ["n2"]},
            {"id": "n2", "type": "agent", "agent_key": "decision", "name": "决策",
             "input": "决定", "next": ["n3"]},
            {"id": "n3", "type": "agent", "agent_key": "executor", "name": "执行",
             "input": "下发", "next": ["n4"]},
            {"id": "n4", "type": "end", "name": "结束"},
        ],
        "edges": [],
    }
    engine = WorkflowEngine(
        agent_runner_factory=lambda key: DecisionRunner() if key == "decision" else ExecutorRunner(),
        tool_invoke=lambda name, params: {"task_no": "task-bind-0001"},
        emit=None,
        known_agents=("decision", "executor", "scout", "weather", "soil", "pest", "verifier"),
        known_tools=("create_task", "wait_penetration"),
    )

    result = asyncio.run(engine.run(dag, run_id=1, trigger="manual"))

    assert result.context["last_task_no"] == "task-bind-0001"
    assert seen["task_no_ctx"] == "task-bind-0001"
    assert current_task_no() == ""      # run 结束后要还原,不能漏给下一次


@pytest.mark.asyncio
async def test_executor_text_only_is_pinned_to_send_device_cmd():
    """run #20:执行管家播报「任务 xxx:已下发」,却一个 send_device_cmd 都没调。

    设备没收到指令 → 任务 30s 超时 → retrying → 复测湿度纹丝不动(38.42% < 基线 38.5%)
    → 验证连转三轮 needs_human。执行管家这一步比决策官更容易漏,因为它「说」得最像。
    """
    from app.agents.context import reset_current_task_no, set_current_task_no

    class CmdRegistry(Registry):
        def to_openai_schemas(self):
            return [{"type": "function",
                     "function": {"name": "send_device_cmd", "description": "下发",
                                  "parameters": {"type": "object", "properties": {}}}}]

        async def invoke(self, name, params=None):
            self.calls.append((name, dict(params or {})))
            return {"task_no": (params or {}).get("task_no", ""), "published": True}

    token = set_current_task_no("task-20261114-0013")
    try:
        llm = ChoiceLLM([
            LLMResult(content="【执行反馈】任务task-20261114-0013：已下发。设备状态：在线。"),
            LLMResult(tool_calls=[ToolCall(
                id="c-exec", name="send_device_cmd",
                arguments={"device_id": "mock-k10-act-03", "action": "pump",
                           "params": {"duration_s": 45}},
                arguments_raw='{}')]),
        ])
        registry = CmdRegistry()
        await _runner("executor", llm, registry).run(task="下发")
    finally:
        reset_current_task_no(token)

    assert llm.calls[1]["tool_choice"] == {"type": "function",
                                          "function": {"name": "send_device_cmd"}}
    assert registry.names() == ["send_device_cmd"]
    assert registry.calls[0][1]["task_no"] == "task-20261114-0013"


@pytest.mark.asyncio
async def test_executor_without_task_no_does_not_force_send():
    llm = ChoiceLLM([LLMResult(content="【执行反馈】本轮无待下发任务。")])
    registry = Registry()
    await _runner("executor", llm, registry).run(task="下发")

    assert len(llm.calls) == 1
    assert registry.calls == []
