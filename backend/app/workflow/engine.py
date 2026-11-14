"""REQ-F-005 / REQ-F-013:工作流执行引擎(PRD 9.2 节点语义、9.3 上下文)。

设计边界:本模块是**纯执行核心**,不 import ORM、不碰数据库、不直接推 WS。
持久化与推送通过注入的三件套完成,给不同宿主用:

- `agent_runner_factory(agent_key) -> runner` runner 需有 `async run(task, upstream=...)`
- `tool_invoke(name, params) -> Any` 可同步可异步(工作流 tool 节点)
- `emit(event: dict) -> None` 事件出口(WS 广播 / 测试里收集)

这样做的原因:队长分支只有 `agents/`,没有 B 的 `models/` 与 `db.py`,
引擎不能反过来依赖基座;等基座合进来,由 `start_run` 的 deps 适配层接真库。

事件契约(前端画布动画 REQ-F-013 依赖,详见 docs/contracts/agent-data-contract.md 第 7 节):
run_started / node_started / node_finished / run_finished,四类。
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from app.workflow.dag import validate_dag
from app.workflow.expression import ExpressionError, evaluate_bool

DECISION_RE = re.compile(r"本轮决策[：:]\s*(irrigate|none|escalate)")
VERDICT_RE = re.compile(r"\b(success|failed|needs_human)\b")


class WorkflowError(RuntimeError):
    """工作流执行期错误(节点失败、表达式非法、超出步数保护)。"""


class WorkflowNotReady(RuntimeError):
    """引擎未接线(缺 deps):由 seams 层翻译成 503 SEAM_NOT_READY,不许造假数据。"""


@dataclass
class NodeRecord:
    node_id: str
    type: str
    name: str
    status: str = "pending"          # running / done / failed / skipped
    agent_key: Optional[str] = None
    output: str = ""
    error: str = ""
    degraded: bool = False
    duration_ms: int = 0


@dataclass
class RunResult:
    run_id: Optional[int]
    wf_key: str
    status: str = "running"           # running / success / failed
    context: dict[str, Any] = field(default_factory=dict)
    nodes: list[NodeRecord] = field(default_factory=list)
    error: str = ""
    duration_ms: int = 0

    def record_of(self, node_id: str) -> Optional[NodeRecord]:
        return next((r for r in self.nodes if r.node_id == node_id), None)


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value


class WorkflowEngine:
    """按 DAG 顺序驱动节点;parallel 扇出、loop 循环、condition 分流。"""

    def __init__(
        self,
        *,
        agent_runner_factory: Callable[[str], Any],
        tool_invoke: Callable[[str, dict], Any],
        emit: Optional[Callable[[dict], Any]] = None,
        known_agents: Optional[Iterable[str]] = None,
        known_tools: Optional[Iterable[str]] = None,
        max_steps: int = 200,
    ):
        self.agent_runner_factory = agent_runner_factory
        self.tool_invoke = tool_invoke
        self.emit = emit
        self.known_agents = known_agents
        self.known_tools = known_tools
        self.max_steps = max_steps

    # ── 事件 ──
    def _fire(self, event: dict) -> None:
        if self.emit is not None:
            event.setdefault("ts", int(time.time() * 1000))
            try:
                result = self.emit(event)
                if asyncio.iscoroutine(result):
                    asyncio.get_running_loop().create_task(result)
            except Exception:  # noqa: BLE001 推送失败不能拖垮执行
                pass

    # ── 主入口 ──
    async def run(
        self,
        dag: dict[str, Any],
        *,
        run_id: Optional[int] = None,
        trigger: str = "manual",
        init_context: Optional[dict] = None,
    ) -> RunResult:
        started = time.monotonic()
        errors = validate_dag(dag, self.known_agents or (), self.known_tools or ())
        if errors:
            raise WorkflowError("DAG 校验未通过:" + ";".join(errors))

        result = RunResult(run_id=run_id, wf_key=dag.get("wf_key") or dag.get("name", ""))
        context: dict[str, Any] = dict(init_context or {})
        context.setdefault("round", 0)
        context["trigger"] = trigger
        nodes = {node["id"]: node for node in dag["nodes"]}
        result.nodes = [
            NodeRecord(node_id=n["id"], type=n.get("type", ""), name=n.get("name", ""))
            for n in dag["nodes"]
        ]
        by_id = {record.node_id: record for record in result.nodes}

        self._fire({
            "type": "run_started", "run_id": run_id, "wf_key": result.wf_key,
            "trigger": trigger, "node_count": len(nodes),
        })

        start_id = next(n["id"] for n in dag["nodes"] if n.get("type") == "start")
        try:
            await self._walk(start_id, nodes, by_id, context, result, stop_at=None, steps=[0])
            result.status = "success"
        except Exception as exc:  # noqa: BLE001 节点失败要把 run 标 failed,但不能吞掉原因
            result.status = "failed"
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            result.context = context
            result.duration_ms = int((time.monotonic() - started) * 1000)
            self._fire({
                "type": "run_finished", "run_id": run_id, "status": result.status,
                "rounds": context.get("round", 0), "duration_ms": result.duration_ms,
                "error": result.error,
            })
        return result

    # ── 节点链遍历 ──
    async def _walk(
        self,
        node_id: Optional[str],
        nodes: dict[str, dict],
        by_id: dict[str, NodeRecord],
        context: dict[str, Any],
        result: RunResult,
        *,
        stop_at: Optional[str],
        steps: list[int],
    ) -> None:
        while node_id:
            if node_id == stop_at:
                return
            steps[0] += 1
            if steps[0] > self.max_steps:
                raise WorkflowError(f"执行步数超过 {self.max_steps},疑似 DAG 成环")
            node = nodes.get(node_id)
            if node is None:
                raise WorkflowError(f"节点 {node_id} 不存在")
            record = by_id[node_id]
            node_type = node.get("type")

            if node_type == "end":
                record.status = "running"
                self._fire({"type": "node_started", "run_id": result.run_id,
                            "node_id": node_id, "node_type": "end",
                            "name": record.name, "agent_key": None})
                record.status = "done"
                self._fire({"type": "node_finished", "run_id": result.run_id,
                            "node_id": node_id, "node_type": "end",
                            "name": record.name, "status": "done"})
                return

            node_id = await self._exec(node, record, nodes, by_id, context, result, steps)

    async def _exec(
        self,
        node: dict,
        record: NodeRecord,
        nodes: dict[str, dict],
        by_id: dict[str, NodeRecord],
        context: dict[str, Any],
        result: RunResult,
        steps: list[int],
    ) -> Optional[str]:
        node_id, node_type = node["id"], node.get("type")
        record.status = "running"
        begun = time.monotonic()
        self._fire({
            "type": "node_started", "run_id": result.run_id, "node_id": node_id,
            "node_type": node_type, "name": record.name, "agent_key": node.get("agent_key"),
        })
        try:
            if node_type == "start":
                record.status = "done"
                return self._first(node.get("next"))

            if node_type == "agent":
                agent_key = node["agent_key"]
                record.agent_key = agent_key
                runner = self.agent_runner_factory(agent_key)
                turn = await runner.run(node.get("input", ""), upstream=self._upstream(context, agent_key))
                record.output = getattr(turn, "content", "") or ""
                record.degraded = bool(getattr(turn, "degraded", False))
                context[agent_key] = record.output
                self._extract(context, agent_key, record.output)
                record.status = "done"
                return self._first(node.get("next"))

            if node_type == "tool":
                value = await _maybe_await(self.tool_invoke(node["tool"], dict(node.get("params") or {})))
                record.output = value if isinstance(value, str) else repr(value)
                context.setdefault("tools", {})[node["tool"]] = value
                record.status = "done"
                return self._first(node.get("next"))

            if node_type == "condition":
                try:
                    branch = "true" if evaluate_bool(node.get("expression", ""), context) else "false"
                except ExpressionError as exc:
                    raise WorkflowError(f"节点 {node_id} 表达式求值失败:{exc}") from exc
                record.output = f"branch={branch}"
                record.status = "done"
                targets = node.get("branches", {}).get(branch) or []
                if len(targets) <= 1:
                    return targets[0] if targets else None
                for target in targets:
                    await self._walk(target, nodes, by_id, context, result, stop_at=None, steps=steps)
                return None

            if node_type == "parallel":
                branches = list(node.get("branches") or [])
                snapshots = [dict(context) for _ in branches]
                outcomes = await asyncio.gather(*[
                    self._walk(branch, nodes, by_id, snapshot, result, stop_at=None, steps=steps)
                    for branch, snapshot in zip(branches, snapshots)
                ], return_exceptions=False)
                del outcomes
                for snapshot in snapshots:  # join:分支产出合并回主上下文
                    for key, value in snapshot.items():
                        if key not in {"trigger", "round"}:
                            context[key] = value
                record.status = "done"
                return self._first(node.get("next"))

            if node_type == "loop":
                max_iter = int(node.get("max_iterations", 1))
                body = node.get("body_next")
                exit_expr = node.get("exit_expression", "")
                # 进入 loop 时主链刚跑完一轮(如 n11 的验证),这一轮计入 round
                context["round"] = max(1, int(context.get("round", 0)) + 1)
                rounds = 0
                # 先判后循环:主链那次验证已达标就直接走 next,不会白跑一遍 body
                while rounds < max_iter:
                    try:
                        if evaluate_bool(exit_expr, context):
                            break
                    except ExpressionError as exc:
                        raise WorkflowError(f"loop 节点 {node_id} 退出表达式求值失败:{exc}") from exc
                    rounds += 1
                    context["round"] = int(context.get("round", 1)) + 1
                    await self._walk(body, nodes, by_id, context, result, stop_at=node_id, steps=steps)
                record.output = f"rounds={rounds}"
                record.status = "done"
                return self._first(node.get("next"))

            raise WorkflowError(f"未知节点类型 {node_type}")
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record.duration_ms = int((time.monotonic() - begun) * 1000)
            self._fire({
                "type": "node_finished", "run_id": result.run_id, "node_id": record.node_id,
                "node_type": node_type, "name": record.name, "agent_key": record.agent_key,
                "status": record.status, "output": record.output, "error": record.error,
                "degraded": record.degraded, "duration_ms": record.duration_ms,
            })

    # ── 小工具 ──
    @staticmethod
    def _first(target: Any) -> Optional[str]:
        if isinstance(target, str):
            return target
        if isinstance(target, list) and target:
            return target[0] if isinstance(target[0], str) else None
        return None

    @staticmethod
    def _upstream(context: dict[str, Any], agent_key: str) -> list[str]:
        """PRD 8.3:下游 Agent 能看到上游结论,按出现顺序;自己不算上游。"""
        skip = {"trigger", "round", "tools", agent_key}
        return [
            f"{key}:{value}" for key, value in context.items()
            if key not in skip and isinstance(value, str) and value
        ]

    @staticmethod
    def _extract(context: dict[str, Any], agent_key: str, content: str) -> None:
        """把关键结论提到顶层键,供 condition/loop 表达式引用(PRD 9.1 的 context.last_decision)。"""
        if agent_key == "decision":
            found = DECISION_RE.search(content or "")
            if found:
                context["last_decision"] = found.group(1)
        elif agent_key == "verifier":
            found = VERDICT_RE.search(content or "")
            if found:
                context["last_verification"] = found.group(1)


# ─────────────────────────── 接缝:start_run ───────────────────────────

@dataclass
class EngineDeps:
    """宿主注入的依赖集合。repo 需提供 create_run/update_run,细节由基座适配。"""
    load_workflow: Callable[[int], dict]      # wf_id -> {wf_key, name, nodes, ...}
    create_run: Callable[..., int]            # (wf_id, trigger) -> run_id
    update_run: Callable[..., None]           # (run_id, status, context, error)
    agent_runner_factory: Callable[[str], Any]
    tool_invoke: Callable[[str, dict], Any]
    emit: Optional[Callable[[dict], Any]] = None


_deps: Optional[EngineDeps] = None


def configure(deps: EngineDeps) -> None:
    """启动时由基座调用一次(bootstrap 里接真库)。"""
    global _deps
    _deps = deps


def is_ready() -> bool:
    return _deps is not None


def _raise_not_ready(reason: str) -> None:
    """优先抛基座的 SeamNotReady(路由统一转 503 + SEAM_NOT_READY);基座未合入时退化为本地异常。"""
    try:
        from app.seams import SeamNotReady  # 公共接缝层
    except Exception:  # noqa: BLE001 基座还没合进这支分支
        raise WorkflowNotReady(f"start_run 尚未就绪:{reason}")
    raise SeamNotReady("start_run", reason)


def start_run(wf_id: int, trigger: str = "manual") -> int:
    """接缝入口(PRD 7.4 / SL-2):同步返回 run_id,执行在后台任务里推进。

    未接线时抛基座的 SeamNotReady —— 由 `seams` 翻译成 503 SEAM_NOT_READY,
    与基座「不造假数据」的约定一致。
    """
    if _deps is None:
        _raise_not_ready("等待基座注入 EngineDeps(bootstrap 里 configure)")
    dag = _deps.load_workflow(wf_id)
    run_id = _deps.create_run(wf_id, trigger)
    engine = WorkflowEngine(
        agent_runner_factory=_deps.agent_runner_factory,
        tool_invoke=_deps.tool_invoke,
        emit=_deps.emit,
    )

    async def _drive() -> None:
        try:
            result = await engine.run(dag, run_id=run_id, trigger=trigger)
            _deps.update_run(run_id, result.status, result.context, result.error)
        except Exception as exc:  # noqa: BLE001 后台任务异常必须落到 run 记录
            _deps.update_run(run_id, "failed", {}, f"{type(exc).__name__}: {exc}")

    try:
        asyncio.get_running_loop().create_task(_drive())
    except RuntimeError:  # 无事件循环(脚本/测试)时同步跑完
        asyncio.run(_drive())
    return run_id
