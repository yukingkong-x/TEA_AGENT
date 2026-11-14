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
        return {"waited_s": params.get("seconds", 0)}

    def run(self, dag=None):
        return asyncio.run(self.engine.run(dag or prd_default_dag(), run_id=1, trigger="manual"))


def test_prd_workflow_runs_end_to_end():
    harness = Harness()
    result = harness.run()

    assert result.status == "success", result.error
    # 7 个 Agent 各跑了一次(verifier 在 Self-Loop 里只跑 1 轮就达标)
    assert harness.calls == {key: 1 for key in AGENT_KEYS}
    assert harness.tool_calls == [("wait_penetration", {"seconds": 90})]
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

    assert result.status == "success"
    # 主链验证 1 次 + max_iterations=2 的修正轮 2 次 = 3 次;退出表达式 round>2 兜底生效
    assert harness.calls["verifier"] == 3
    assert result.context["round"] == 3
    assert result.context["last_verification"] == "failed"


def test_run_emits_canvas_events_in_order():
    harness = Harness()
    harness.run()
    types = [event["type"] for event in harness.events]

    assert types[0] == "run_started"
    assert types[-1] == "run_finished"
    assert types.count("run_started") == 1
    assert types.count("run_finished") == 1
    assert "node_started" in types and "node_finished" in types

    # 每个 node_started 都有配对的 node_finished,画布不会卡在「进行中」
    started = [e["node_id"] for e in harness.events if e["type"] == "node_started"]
    finished = [e["node_id"] for e in harness.events if e["type"] == "node_finished"]
    assert sorted(started) == sorted(finished)

    # 事件里的字段够前端画动画:节点 id、类型、名字、agent_key、耗时
    first_node = next(e for e in harness.events if e["type"] == "node_started")
    assert {"run_id", "node_id", "node_type", "name", "ts"} <= set(first_node)
    finished_event = next(e for e in harness.events if e["type"] == "node_finished")
    assert {"status", "duration_ms"} <= set(finished_event)


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
    with pytest.raises(WorkflowNotReady):
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
        tool_invoke=lambda name, params: {"waited_s": 90},
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
