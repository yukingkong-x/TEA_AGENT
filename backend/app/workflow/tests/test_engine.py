"""REQ-F-005 执行引擎单测:节点语义(PRD 9.2)、上下文传递(9.3)、画布事件(REQ-F-013)。

用假的 runner / tool 驱动 PRD 9.1 的默认工作流,不碰 LLM、不碰数据库。
断点落在这里的原因:引擎一旦把 parallel/loop 的组合走错,现场表现是「画布动了两下就不动了」,
没有单测就只能靠彩排发现。
"""
import asyncio
import json

import pytest

from app.agents.base import AgentTurn
from app.workflow.engine import WorkflowEngine, WorkflowError, WorkflowNotReady, start_run
from app.workflow.tests.test_dag import AGENT_KEYS, TOOL_NAMES, prd_default_dag

REPLIES = {
    "scout": "【巡园播报】A区平均湿度 33%,整体偏干。",
    "weather": "【气象评估】未来12小时无雨,可灌溉。",
    "soil": "【墒情报告】A区土壤湿度33%,趋势下降,评级:轻度缺水,建议灌溉。",
    "pest": "【植保核查】知识库检索到1条,无时段冲突。",
    "decision": "【决策】本轮决策:irrigate。方案:对A区执行浇水30秒,目标湿度55-65%,优先级6。",
    "executor": "【执行反馈】任务task-001:已下发。设备状态:在线。",
    "verifier": "【验证报告】达成率 100%,置信度 82%,结论:success,闭环成功。",
}


class FakeRunner:
    def __init__(self, agent_key: str, calls: dict[str, int], replies: dict[str, str]):
        self.agent_key = agent_key
        self.calls = calls
        self.replies = replies

    async def run(self, task: str, upstream=None):
        self.calls[self.agent_key] = self.calls.get(self.agent_key, 0) + 1
        return AgentTurn(agent_key=self.agent_key, content=self.replies[self.agent_key])


class Harness:
    def __init__(self, replies=None, max_steps: int = 200):
        self.calls: dict[str, int] = {}
        self.events: list[dict] = []
        self.tool_calls: list[tuple[str, dict]] = []
        self.replies = dict(REPLIES if replies is None else replies)
        self.engine = WorkflowEngine(
            agent_runner_factory=lambda key: FakeRunner(key, self.calls, self.replies),
            tool_invoke=self._tool,
            emit=self.events.append,
            known_agents=AGENT_KEYS,
            known_tools=TOOL_NAMES,
            max_steps=max_steps,
        )

    def _tool(self, name: str, params: dict):
        self.tool_calls.append((name, params))
        if name == "create_task":     # 真实现返回 task_no;引擎补建依赖它
            return {"task_no": f"task-test-{len(self.tool_calls)}"}
        return {"waited_s": params.get("seconds", 0)}

    def run(self, dag=None):
        return asyncio.run(self.engine.run(dag or prd_default_dag(), run_id=1, trigger="manual"))


def test_prd_workflow_runs_end_to_end():
    harness = Harness()
    result = harness.run()

    assert result.status == "success", result.error
    # 7 个 Agent 各跑了一次(verifier 在 Self-Loop 里只跑 1 轮就达标)
    assert harness.calls == {key: 1 for key in AGENT_KEYS}
    # 决策正文写「浇水30秒」但没真的调 create_task → 引擎补建(见 _ensure_task),
    # 然后才轮到渗透期等待
    assert [name for name, _ in harness.tool_calls] == ["create_task", "wait_penetration"]
    assert harness.tool_calls[0][1]["payload"]["params"]["duration_s"] == 30
    assert harness.tool_calls[1] == ("wait_penetration", {"seconds": 90})
    # 关键结论被提到顶层,供 condition / loop 表达式引用
    assert result.context["last_decision"] == "irrigate"
    assert result.context["last_verification"] == "success"
    assert result.context["round"] == 1
    # 参与本次执行的节点都有终态;未走到的分支保持 pending(画布上也不该点亮)
    assert result.record_of("n9").status == "done"
    assert result.record_of("n13").status == "done"
    assert result.record_of("n12").status == "pending"


def test_parallel_branches_merge_into_context():
    harness = Harness()
    result = harness.run()
    for key in ("weather", "soil", "pest"):
        assert result.context[key].startswith("【")
    # 分支节点都记在 run 记录里,前端画布才能逐个点亮
    for node_id in ("n4", "n5", "n6"):
        assert result.record_of(node_id).status == "done"


def test_decision_none_skips_irrigation_branch():
    replies = dict(REPLIES)
    replies["decision"] = "【决策】本轮决策:none。方案:本轮无需作业。依据:土壤适宜,无降雨风险。"
    harness = Harness(replies)
    result = harness.run()

    assert result.status == "success"
    assert result.context["last_decision"] == "none"
    assert "executor" not in harness.calls          # 走了 false 分支
    assert harness.tool_calls == []                  # 没有渗透等待
    assert result.record_of("n12").status == "done"
    assert result.record_of("n9").status == "pending"  # 未参与本次执行的节点保持 pending


def test_self_loop_retries_when_verification_fails():
    replies = dict(REPLIES)
    replies["verifier"] = "【验证报告】达成率 42%,置信度 80%,结论:failed,需修正后重验。"
    harness = Harness(replies)
    result = harness.run()

    # 未达标跑满轮次 → needs_human(PRD 11.4.3),不再「跑完就算成功」
    assert result.status == "needs_human"
    assert "转人工" in result.error
    # max_iterations=2 是总轮次:主链 1 轮 + 修正 1 轮,不是 1+2
    assert harness.calls["verifier"] == 2
    assert result.context["round"] == 2
    assert result.context["last_verification"] == "failed"


def test_run_emits_canvas_events_in_order():
    harness = Harness()
    harness.run()
    types = [event["type"] for event in harness.events]

    # 外发的是基座 WS 白名单里的两类,不是内部的四个语义名
    assert set(types) <= {"run_status", "node_state"}
    assert types[0] == "run_status" and harness.events[0]["status"] == "running"
    assert types[-1] == "run_status" and harness.events[-1]["status"] == "success"

    nodes = [e for e in harness.events if e["type"] == "node_state"]
    assert all(e["state"] in {"started", "finished"} for e in nodes)

    # 每个 started 都有配对的 finished,画布不会卡在「进行中」
    started = [e["node_id"] for e in nodes if e["state"] == "started"]
    finished = [e["node_id"] for e in nodes if e["state"] == "finished"]
    assert sorted(started) == sorted(finished)

    # 事件里的字段够前端画动画:节点 id、类型、名字、agent_key、耗时
    first_node = next(e for e in nodes if e["state"] == "started")
    assert {"run_id", "node_id", "node_type", "name", "ts"} <= set(first_node)
    finished_event = next(e for e in nodes if e["state"] == "finished")
    assert {"status", "duration_ms"} <= set(finished_event)

    # run 结束事件带结算字段
    assert {"rounds", "duration_ms"} <= set(harness.events[-1])


def test_event_names_match_base_ws_whitelist():
    """引擎外发的事件类型必须落在基座 WS_TYPES 里,否则每条事件刷一条未知类型告警。

    这是把「引擎写 node_started、基座白名单写 node_state」这类静默不一致钉住的守卫:
    真跑起来只会打 warning、事件照发,不报错,靠人眼永远发现不了。
    """
    from app.workflow.engine import WS_TYPE_OF

    base_whitelist = {"telemetry", "device_status", "task_status", "agent_message",
                      "node_state", "run_status", "alert", "mode_changed"}
    assert set(WS_TYPE_OF.values()) <= base_whitelist
    # 四个内部事件一个都不能漏翻译
    assert set(WS_TYPE_OF) == {"run_started", "run_finished", "node_started", "node_finished"}


def test_agent_node_carries_tool_calls_and_tokens():
    """对话剧场的折叠块靠这两个字段,引擎必须原样搬运 turn 的明细。"""
    harness = Harness()
    harness.run()
    done = [e for e in harness.events
            if e["type"] == "node_state" and e["state"] == "finished" and e.get("agent_key")]
    assert done, "默认工作流至少要有一次 agent 节点的 finished 事件"
    for event in done:
        assert "tool_calls" in event and isinstance(event["tool_calls"], list)
        assert "tokens_in" in event and "tokens_out" in event


def test_invalid_dag_rejected_before_running():
    dag = prd_default_dag()
    dag["nodes"][0]["next"] = ["n404"]
    with pytest.raises(WorkflowError, match="DAG 校验未通过"):
        asyncio.run(Harness().engine.run(dag))


def test_step_guard_stops_runaway_graph():
    harness = Harness(max_steps=3)
    result = harness.run()
    assert result.status == "failed"
    assert "步数超过" in result.error


def test_agent_failure_marks_run_failed():
    class Boom:
        async def run(self, task, upstream=None):
            raise RuntimeError("LLM 挂了")

    harness = Harness()
    harness.engine.agent_runner_factory = lambda key: Boom()
    result = harness.run()
    assert result.status == "failed"
    assert "LLM 挂了" in result.error
    assert result.record_of("n2").status == "failed"


def test_start_run_seam_raises_when_not_wired():
    # 接缝没接线时必须显式失败,由 seams 翻译成 503,不许假装成功
    # 合入基座后 _raise_not_ready 抛的是 app.seams.SeamNotReady(路由统一转 503),
    # 本分支没有基座时才是 WorkflowNotReady —— 两者都算合格,只要不是静默成功。
    try:
        from app.seams import SeamNotReady
    except Exception:  # noqa: BLE001
        SeamNotReady = WorkflowNotReady
    with pytest.raises((WorkflowNotReady, SeamNotReady)):
        start_run(1, "manual")


def test_start_run_wires_through_deps():
    from app.workflow import engine as engine_mod

    recorded: dict[str, object] = {}
    calls: dict[str, int] = {}

    deps = engine_mod.EngineDeps(
        load_workflow=lambda wf_id: prd_default_dag(),
        create_run=lambda wf_id, trigger: 42,
        update_run=lambda run_id, status, context, error: recorded.update(
            {"run_id": run_id, "status": status, "context": context, "error": error}
        ),
        agent_runner_factory=lambda key: FakeRunner(key, calls, REPLIES),
        tool_invoke=lambda name, params: ({"task_no": "task-42"} if name == "create_task"
                                          else {"waited_s": 90}),
        emit=None,
    )
    engine_mod.configure(deps)
    try:
        run_id = start_run(1, "manual")
        assert run_id == 42
        assert recorded["status"] == "success"
        assert recorded["context"]["last_decision"] == "irrigate"
    finally:
        engine_mod._deps = None  # 复原,避免污染其它用例


def test_start_run_times_out_instead_of_hanging_forever(monkeypatch):
    """节点里一次 await 不回来,run 不能永远 running(run 24 真实卡死)。

    现场(2026-11-14 run #24):执行管家下发后,验证官节点再没回来,run 挂在
    running 十几分钟,前端一直转圈、接口也不报错。正确行为是超时兜底:
    标记 failed 并写明最后停留的节点,让「卡住」变成「明确失败」。
    """
    import asyncio

    from app.workflow import engine as engine_mod

    recorded: dict[str, object] = {}

    async def _never(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(engine_mod.WorkflowEngine, "run", _never)
    monkeypatch.setattr(engine_mod, "RUN_TIMEOUT_S", 0.05)

    deps = engine_mod.EngineDeps(
        load_workflow=lambda wf_id: prd_default_dag(),
        create_run=lambda wf_id, trigger: 77,
        update_run=lambda run_id, status, context, error: recorded.update(
            {"run_id": run_id, "status": status, "error": error}
        ),
        agent_runner_factory=lambda key: FakeRunner(key, {}, REPLIES),
        tool_invoke=lambda name, params: {},
        emit=None,
    )
    engine_mod.configure(deps)

    async def _scenario():
        engine_mod.start_run(1, "manual")
        for _ in range(50):        # 等后台任务把 failed 写回去
            if recorded:
                break
            await asyncio.sleep(0.02)

    try:
        asyncio.run(_scenario())
    finally:
        engine_mod._deps = None

    assert recorded["status"] == "failed"
    assert "超时" in str(recorded["error"])


# ── 2026-11-14 真实 run #9 的两个现场故障 ──────────────────────────────

def test_loop_missing_exit_field_does_not_kill_the_run():
    """上游这轮没验证 → `last_verification` 空缺。这不该让整条 run failed。

    现场(run #9):执行管家建任务被拒 → 没有任务 → 没有验证 → loop 的退出表达式
    抛「context 缺少字段 last_verification」→ 整条 run failed、画布停在 Self-Loop。
    正确语义是「退出条件暂不成立」,由 max_iterations 兜底。
    """
    dag = {
        "wf_key": "loop_gap", "name": "循环缺字段",
        "nodes": [
            {"id": "n1", "type": "start", "name": "开始", "next": ["n2"]},
            {"id": "n2", "type": "loop", "name": "Self-Loop", "max_iterations": 1,
             "exit_expression": "context.last_verification == 'success'",
             "body_next": "n3", "next": ["n4"]},
            {"id": "n3", "type": "tool", "name": "补测", "tool": "wait_penetration", "params": {},
             "next": []},
            {"id": "n4", "type": "end", "name": "结束"},
        ],
        "edges": [],
    }
    harness = Harness()
    result = harness.run(dag)

    assert result.status == "success"
    assert result.context["last_verification"] == ""      # 占位而不是缺键
    assert harness.tool_calls                            # body 确实跑了一轮


def test_verdict_is_taken_from_tool_result_not_prose():
    """verifier 的结论在 verify_result 的返回里,正文常常没写 success 这个词。"""
    from app.workflow.engine import WorkflowEngine

    class ToolCallRunner:
        async def run(self, task, upstream=None):
            return AgentTurn(
                agent_key="verifier",
                content="【验证报告】基线 38.5 → 复测 48.9,达成率 63.02%,置信度 92%。",
                tool_calls=[{"name": "verify_result", "status": "executed",
                             "result": {"verdict": "success", "achievement": 63.02}}],
            )

    engine = WorkflowEngine(
        agent_runner_factory=lambda key: ToolCallRunner(),
        tool_invoke=lambda name, params: {},
        emit=None,
        known_agents=AGENT_KEYS,
        known_tools=TOOL_NAMES,
    )
    dag = {
        "wf_key": "verdict_from_tool", "name": "结论取工具结果",
        "nodes": [
            {"id": "n1", "type": "start", "name": "开始", "next": ["n2"]},
            {"id": "n2", "type": "agent", "agent_key": "verifier", "name": "验证",
             "input": "复测", "next": ["n3"]},
            {"id": "n3", "type": "loop", "name": "Self-Loop", "max_iterations": 1,
             "exit_expression": "context.last_verification == 'success'",
             "body_next": "n4", "next": ["n5"]},
            {"id": "n4", "type": "tool", "name": "补测", "tool": "wait_penetration", "params": {},
             "next": []},
            {"id": "n5", "type": "end", "name": "结束"},
        ],
        "edges": [],
    }
    result = asyncio.run(engine.run(dag, run_id=1, trigger="manual"))

    assert result.context["last_verification"] == "success"
    assert result.nodes[2].output == "rounds=0"          # 已经达标,不进 body


def _decision_dag(agent_key="decision"):
    return {
        "wf_key": "ensure_task", "name": "决策落单",
        "nodes": [
            {"id": "n1", "type": "start", "name": "开始", "next": ["n2"]},
            {"id": "n2", "type": "agent", "agent_key": agent_key, "name": "决策",
             "input": "决定", "next": ["n3"]},
            {"id": "n3", "type": "end", "name": "结束"},
        ],
        "edges": [],
    }


def test_irrigate_without_create_task_is_backfilled_by_engine():
    """现场(run #13):模型写「本轮决策:irrigate（任务 task-xxx）」但没调用工具。

    任务号是编的,库里一行没有 → 执行管家没单可下。引擎必须按正文时长补建。
    """
    class Runner:
        async def run(self, task, upstream=None):
            return AgentTurn(
                agent_key="decision",
                content="【决策】本轮决策:irrigate（任务 task-xxx）。\n方案:对A区执行浇水45秒，目标湿度55-65%，优先级6。",
            )

    created: list[dict] = []

    def _tool(name, params):
        created.append({"name": name, "params": params})
        return {"task_no": "task-20261114-9001", "status": "pending"}

    engine = WorkflowEngine(
        agent_runner_factory=lambda key: Runner(),
        tool_invoke=_tool,
        emit=None,
        known_agents=AGENT_KEYS,
        known_tools=TOOL_NAMES,
    )
    result = asyncio.run(engine.run(_decision_dag(), run_id=1, trigger="manual"))

    assert [c["name"] for c in created] == ["create_task"]
    body = created[0]["params"]["payload"]
    assert body["params"]["duration_s"] == 45          # 取自正文,不是默认 30
    assert body["target_range"] == [55, 65]
    assert result.context["last_task_no"] == "task-20261114-9001"
    # 留痕:工具调用里能看出这单是引擎补的
    assert result.nodes[1].tool_calls[-1]["id"] == "engine-create_task"


def test_create_task_from_agent_is_not_duplicated():
    class Runner:
        async def run(self, task, upstream=None):
            return AgentTurn(
                agent_key="decision",
                content="【决策】本轮决策:irrigate（任务 task-20261114-8888）。方案:浇水30秒。",
                tool_calls=[{"name": "create_task", "status": "executed",
                             "result": {"task_no": "task-20261114-8888"}}],
            )

    created: list[str] = []

    def _tool(name, params):
        created.append(name)
        return {"task_no": "should-not-happen"}

    engine = WorkflowEngine(
        agent_runner_factory=lambda key: Runner(),
        tool_invoke=_tool,
        emit=None,
        known_agents=AGENT_KEYS,
        known_tools=TOOL_NAMES,
    )
    result = asyncio.run(engine.run(_decision_dag(), run_id=1, trigger="manual"))

    assert created == []                                  # Agent 建过就不再补
    assert result.context["last_task_no"] == "task-20261114-8888"


def test_none_decision_creates_no_task():
    class Runner:
        async def run(self, task, upstream=None):
            return AgentTurn(agent_key="decision", content="【决策】本轮决策:none。墒情适宜。")

    created: list[str] = []
    engine = WorkflowEngine(
        agent_runner_factory=lambda key: Runner(),
        tool_invoke=lambda name, params: created.append(name) or {"task_no": "x"},
        emit=None,
        known_agents=AGENT_KEYS,
        known_tools=TOOL_NAMES,
    )
    asyncio.run(engine.run(_decision_dag(), run_id=1, trigger="manual"))

    assert created == []


def test_executor_sees_task_no_in_upstream():
    seen: dict[str, str] = {}

    class Runner:
        async def run(self, task, upstream=None):
            seen["upstream"] = "\n".join(upstream or [])
            return AgentTurn(agent_key="executor", content="【执行反馈】已下发。")

    dag = {
        "wf_key": "taskno_passthrough", "name": "任务号透传",
        "nodes": [
            {"id": "n1", "type": "start", "name": "开始", "next": ["n2"]},
            {"id": "n2", "type": "agent", "agent_key": "executor", "name": "执行",
             "input": "下发", "next": ["n3"]},
            {"id": "n3", "type": "end", "name": "结束"},
        ],
        "edges": [],
    }
    engine = WorkflowEngine(
        agent_runner_factory=lambda key: Runner(),
        tool_invoke=lambda name, params: {},
        emit=None,
        known_agents=AGENT_KEYS,
        known_tools=TOOL_NAMES,
    )
    asyncio.run(engine.run(dag, run_id=1, trigger="manual", init_context={"last_task_no": "task-77"}))

    assert "task-77" in seen["upstream"]


def test_backfilled_task_carries_executor_device():
    """补建的任务必须自带 device_id,否则落库后 assigned_device 为空、派不出去。"""
    class Runner:
        async def run(self, task, upstream=None):
            return AgentTurn(agent_key="decision", content="【决策】本轮决策:irrigate。方案:浇水20秒。")

    created: list[dict] = []
    engine = WorkflowEngine(
        agent_runner_factory=lambda key: Runner(),
        tool_invoke=lambda name, params: (created.append(params) or {"task_no": "task-1"}),
        emit=None,
        known_agents=AGENT_KEYS,
        known_tools=TOOL_NAMES,
    )
    asyncio.run(engine.run(_decision_dag(), run_id=1, trigger="manual",
                           init_context={"executor_device": "mock-k10-act-03"}))

    assert created[0]["payload"]["device_id"] == "mock-k10-act-03"


def test_start_run_passes_context_provider_into_run():
    from app.workflow import engine as engine_mod

    recorded: dict[str, object] = {}
    deps = engine_mod.EngineDeps(
        load_workflow=lambda wf_id: _decision_dag(),
        create_run=lambda wf_id, trigger: 7,
        update_run=lambda run_id, status, context, error: recorded.update(status=status, context=context),
        agent_runner_factory=lambda key: _NoopRunner(),
        tool_invoke=lambda name, params: {"task_no": "task-7"},
        emit=None,
        context_provider=lambda: {"executor_device": "mock-k10-act-03"},
    )
    engine_mod.configure(deps)
    try:
        engine_mod.start_run(1, "manual")
    finally:
        engine_mod._deps = None

    assert recorded["context"]["executor_device"] == "mock-k10-act-03"


class _NoopRunner:
    async def run(self, task, upstream=None):
        return AgentTurn(agent_key="decision", content="【决策】本轮决策:none。")


def test_start_run_binds_run_id_for_tool_layer(monkeypatch):
    """run_id 跟着上下文走到工具层,不再依赖基座「唯一 running 才认」的兜底。

    2026-11-14 队友B:create_task 落在工具层、send_cmd 落在设备层,两边都读
    core/run_context 的 ContextVar;引擎不 set 时,同时跑两条 run 就分不清谁是谁,
    tasks.run_id / verifications.run_id 只能记 NULL(报告页按 run 聚合全空)。
    """
    import asyncio
    import sys
    import types

    from app.workflow import engine as engine_mod

    calls: list[tuple[str, object]] = []
    fake = types.ModuleType("app.core.run_context")
    fake.set_current_run_id = lambda value: calls.append(("set", value)) or "run-token"
    fake.reset_current_run_id = lambda token: calls.append(("reset", token))
    monkeypatch.setitem(sys.modules, "app.core.run_context", fake)

    observed: dict[str, object] = {}
    recorded: dict[str, object] = {}

    async def _fast_run(self, dag=None, run_id=None, trigger="manual", init_context=None):
        observed["during"] = list(calls)
        return engine_mod.RunResult(run_id=run_id, wf_key="k", status="success")

    monkeypatch.setattr(engine_mod.WorkflowEngine, "run", _fast_run)
    engine_mod.configure(engine_mod.EngineDeps(
        load_workflow=lambda wf_id: prd_default_dag(),
        create_run=lambda wf_id, trigger: 77,
        update_run=lambda run_id, status, context, error: recorded.update({"run_id": run_id}),
        agent_runner_factory=lambda key: FakeRunner(key, {}, REPLIES),
        tool_invoke=lambda name, params: {},
        emit=None,
    ))

    async def _scenario():
        engine_mod.start_run(1, "manual")
        for _ in range(50):
            if recorded:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)   # 让 _drive 的 finally 跑完(reset 才算数)

    try:
        asyncio.run(_scenario())
    finally:
        engine_mod._deps = None

    # run 执行期间 run_id 已经在上下文里,结束后复位(不把本轮带进下一次)
    assert observed["during"] == [("set", 77)]
    assert calls == [("set", 77), ("reset", "run-token")]


# ── 2026-11-14 run #26:决策措辞换个说法就判错 ──────────────────────────

def test_decision_worded_with_wei_still_irrigates():
    """真模型写「本轮决策**为**irrigate」,旧正则只认冒号 → 分流走了「无需作业归档」。

    现场(run #26):决策官正文明确说 irrigate、墒情 38% 也确实缺水,但 context
    .last_decision 没提出来 → condition 判 false → 归档节点报「本轮无需作业」。
    画布全绿、一滴水没浇,这是最难被发现的一种失败。
    """
    replies = dict(REPLIES)
    replies["decision"] = "【决策】本轮决策为irrigate。方案:对A区执行浇水30秒，目标湿度55-65%。"
    harness = Harness(replies)
    result = harness.run()

    assert result.context["last_decision"] == "irrigate"
    assert result.record_of("n9").status == "done"        # 真的进灌溉分支
    assert result.record_of("n12").status == "pending"    # 没误走归档


@pytest.mark.parametrize("text,expected", [
    ("本轮决策:irrigate", "irrigate"),
    ("本轮决策：irrigate", "irrigate"),
    ("本轮决策为irrigate", "irrigate"),
    ("本轮决策是 None", "None"),        # group 原样,大小写由调用方归一
    ("本轮决策  irrigate", "irrigate"),
])
def test_decision_regex_accepts_natural_wording(text, expected):
    from app.workflow.engine import DECISION_RE

    found = DECISION_RE.search(f"【决策】{text}。方案:浇水30秒。")
    assert found is not None
    assert found.group(1).lower() == expected.lower()


def test_tool_fact_beats_wording_when_decision_conflicts():
    """真建了单就不可能是否决:create_task 的成功调用优先于正文措辞。"""
    context: dict = {}
    WorkflowEngine._extract(
        context, "decision", "【决策】本轮决策:none。",
        [{"name": "create_task", "status": "executed",
          "result": {"task_no": "task-20261114-7777"}}],
    )
    assert context["last_task_no"] == "task-20261114-7777"
    assert context["last_decision"] == "irrigate"


def test_self_loop_creates_correction_task_from_verification_plan():
    """验证层算出的 correction 必须被执行:建修正单 → 回去浇水,而不是原地重验。

    现场(run #28):loop body 只回验证官,三轮拿到同一批传感器数据(恒为 40.41%),
    feedback_logs 一行没有 —— 循环在画布上转了,物理世界一动不动,run 还标了 success。
    PRD 11.4.2 要求「写 feedback_logs、生成新任务(trigger=selfloop),回到执行-验证循环」。
    """
    harness = Harness()

    class VerifierRunner:
        def __init__(self):
            self.round = 0

        async def run(self, task, upstream=None):
            self.round += 1
            verdict = "failed" if self.round <= 2 else "success"
            return AgentTurn(
                agent_key="verifier",
                content=f"【验证报告】结论:{verdict}，达成率 40.41%。",
                tool_calls=[{"name": "verify_result", "status": "executed", "result": {
                    "verdict": verdict, "achievement": 40.41, "baseline": 38.47,
                    "measured": 45.15, "gap": 9.85, "task_no": "task-20261114-0019",
                    "confidence": 100.0, "round_no": self.round,
                    "correction": {"strategy": "topup", "duration_s": 19.9, "times": 1,
                                   "interval_s": 0, "gap": 9.85,
                                   "reason": "缺口 9.85% 在 15.0 以内,单次补灌 19.9s"},
                }}],
            )

    factory = harness.engine.agent_runner_factory
    verifier = VerifierRunner()
    harness.engine.agent_runner_factory = (
        lambda key: verifier if key == "verifier" else factory(key)
    )
    import asyncio
    result = asyncio.run(harness.engine.run(
        prd_default_dag(), run_id=1, trigger="manual",
        init_context={"executor_device": "mock-k10-act-03"},
    ))

    created = [params["payload"] for name, params in harness.tool_calls if name == "create_task"]
    assert len(created) >= 2, created                 # 决策 1 张 + 修正至少 1 张
    assert created[-1]["trigger"] == "selfloop"       # PRD 11.4.2 的修正任务标记
    assert created[-1]["params"]["duration_s"] == 19.9   # 用验证层算出的补灌时长
    assert created[-1]["device_id"]                    # 修正单也要有归属终端

    feedbacks = result.context.get("feedbacks") or []
    assert feedbacks, "修正动作必须留下证据链(context.feedbacks → feedback_logs)"
    assert feedbacks[0]["strategy"] == "topup"
    assert feedbacks[0]["from_task_no"] == "task-20261114-0019"
    assert feedbacks[0]["to_task_no"]

    # 修正轮重跑的节点要带第 2 轮标记(节点耗时表按它分组,否则前端只能显示「第 0 轮」)
    records = {r.node_id: r for r in result.nodes}
    assert records["n9"].round_no == 2
    assert records["n11"].round_no == 2
    assert records["n2"].round_no == 1          # 巡园只跑过一次,仍是第 1 轮
    # loop 节点的耗时是包住整个 body 的聚合,轮次按结束时记(它覆盖到了第 2 轮)
    assert records["n11b"].round_no == 2


def test_node_records_skip_branches_that_never_ran():
    """节点耗时表只落真跑过的节点:`result.nodes` 起跑就按整张 DAG 建齐。

    全落进去的话,决策=irrigate 的 run 时间线里会多一条「待执行」的「无需作业归档」,
    汇总的节点数也会比画布上动过的多一个。这条单测盯的就是那个 pending 过滤器。
    """
    harness = Harness()                          # 默认回复 success → 只跑一轮
    result = harness.run()

    records = {r.node_id: r for r in result.nodes}
    assert records["n12"].status == "pending"    # 归档分支没走到
    assert records["n9"].status == "done"
    assert all(r.round_no == 1 for r in result.nodes if r.status != "pending")


def test_executor_sends_the_duration_the_decision_created():
    """执行管家不能自己报一个时长:run #30 实测载荷 45s、设备真浇 60s。

    决策官建单时定了 45 秒,执行管家(没有建单权限)从历史里记得一个 60,
    照自己的数字下发。任务号已经由引擎递过去了,时长必须同样处理 ——
    否则报告写「第 1 轮 45.00s」而物理上浇了 60 秒。
    """
    harness = Harness()

    class DecisionRunner:
        async def run(self, task, upstream=None):
            return AgentTurn(
                agent_key="decision",
                content="【决策】本轮决策:irrigate。方案:浇水45秒，目标湿度55-65%。",
                tool_calls=[{"name": "create_task", "status": "executed",
                             "result": {"task_no": "task-20261114-0101"},
                             "arguments": {"type": "device_cmd", "priority": 6,
                                           "payload": {"action": "pump",
                                                       "params": {"duration_s": 45}}}}],
            )

    class ExecutorRunner:
        async def run(self, task, upstream=None):
            from app.agents.context import current_pump_duration

            return AgentTurn(
                agent_key="executor",
                content="【执行反馈】已下发。",
                tool_calls=[{"name": "send_device_cmd", "status": "executed",
                             "result": {"published": True},
                             # 模型自己记的是 60 秒(上一轮的旧数字)
                             "arguments": {"device_id": "mock-k10-act-03", "action": "pump",
                                           "params": {"duration_s": 60}},
                             "seen_duration": current_pump_duration()}],
            )

    factory = harness.engine.agent_runner_factory
    decision, executor = DecisionRunner(), ExecutorRunner()
    harness.engine.agent_runner_factory = lambda key: (
        decision if key == "decision" else executor if key == "executor" else factory(key)
    )
    import asyncio
    result = asyncio.run(harness.engine.run(
        prd_default_dag(), run_id=1, trigger="manual",
        init_context={"executor_device": "mock-k10-act-03"},
    ))

    assert result.context["last_duration_s"] == 45.0
