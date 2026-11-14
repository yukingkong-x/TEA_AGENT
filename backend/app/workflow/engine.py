"""REQ-F-005 / REQ-F-013:工作流执行引擎(PRD 9.2 节点语义、9.3 上下文)。

设计边界:本模块是**纯执行核心**,不 import ORM、不碰数据库、不直接推 WS。
持久化与推送通过注入的三件套完成,给不同宿主用:

- `agent_runner_factory(agent_key) -> runner` runner 需有 `async run(task, upstream=...)`
- `tool_invoke(name, params) -> Any` 可同步可异步(工作流 tool 节点)
- `emit(event: dict) -> None` 事件出口(WS 广播 / 测试里收集)

这样做的原因:队长分支只有 `agents/`,没有 B 的 `models/` 与 `db.py`,
引擎不能反过来依赖基座;等基座合进来,由 `start_run` 的 deps 适配层接真库。

事件契约(前端画布动画 REQ-F-013 依赖,详见 docs/contracts/agent-data-contract.md 第 7 节):
对外只有**两类** WS 消息,与基座 `core/ws_manager.WS_TYPES`(PRD 7.4 白名单)对齐:

- `node_state`:`state` 取 `started` / `finished`,节点高亮与动画;
- `run_status`:`status` 取 `running` / `success` / `failed`,执行进度。

引擎内部仍用四个语义化名字(`run_started` / `node_started` / `node_finished` / `run_finished`)
书写,由 `_fire` 集中翻译一次。这样两条好处:调用点读起来仍是「开始/结束」的原意;
白名单只有基座一处权威,本模块不擅自扩 WS 类型(扩了会让每条事件刷一条未知类型告警)。
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from loguru import logger

from app.workflow.dag import validate_dag
from app.workflow.expression import ExpressionError, evaluate_bool

DECISION_RE = re.compile(r"本轮决策[：:]\s*(irrigate|none|escalate)")
VERDICT_RE = re.compile(r"\b(success|failed|needs_human)\b")
# 决策正文里的时长:「对A区执行浇水45秒」/「浇水 30 s」都吃
DURATION_RE = re.compile(r"(?:浇水|灌溉)\s*(\d{1,3})\s*(?:秒|s\b)")

# 引擎内部事件名 → 基座 WS_TYPES 白名单里的消息类型（PRD 7.4）。
# 集中在这里翻译，6 个 _fire 调用点保持语义化写法。
WS_TYPE_OF = {
    "run_started": "run_status",
    "run_finished": "run_status",
    "node_started": "node_state",
    "node_finished": "node_state",
}

# 需要额外补的「阶段」字段：前端靠 (type, state|status) 两元组分辨开始/结束。
_WS_STAGE_OF = {
    "run_started": ("status", "running"),
    "node_started": ("state", "started"),
    "node_finished": ("state", "finished"),
}


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
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
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
        """内部事件 → 基座 WS 形态（type 换成白名单类型 + 补阶段字段），再交给 emit。

        翻译只在这一处做，调用点保持 `run_started` / `node_finished` 这类语义名。
        注意这里是**扁平**结构：字段与 `type` 同级，没有再包一层 `data`——基座
        `_envelope` 会包 `{type, data, ts}`，多包一层会让前端拿到 `data.data`。
        """
        if self.emit is None:
            return
        internal = event.get("type")
        stage = _WS_STAGE_OF.get(internal)
        if WS_TYPE_OF.get(internal):
            event = dict(event)
            event["type"] = WS_TYPE_OF[internal]
            if stage is not None:
                key, value = stage
                event.setdefault(key, value)
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
        # 表达式引用的键先占位:第一轮还没验证时 last_verification 不该是「字段不存在」,
        # 而是「还没有结论」。否则 loop 的退出表达式直接判成工程错误。
        context.setdefault("last_decision", "")
        context.setdefault("last_verification", "")
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
                # 对话剧场要折叠展示的明细：工具调用与 token 用量都从 turn 透传出来，
                # 引擎不解读内容，只负责搬运（解析归 wiring，落库归基座）。
                record.tool_calls = list(getattr(turn, "tool_calls", None) or [])
                record.tokens_in = int(getattr(turn, "tokens_in", 0) or 0)
                record.tokens_out = int(getattr(turn, "tokens_out", 0) or 0)
                context[agent_key] = record.output
                self._extract(context, agent_key, record.output, record.tool_calls)
                if agent_key == "decision":
                    await self._ensure_task(node_id, record, context)
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
                        # 循环的退出条件天然会「暂时不成立」:上游节点这次没产出该字段
                        # (如本轮根本没建任务,自然没有 last_verification)。
                        # 这不是工程错误,按「未达标」继续走 body;max_iterations 兜底。
                        if rounds == 0:
                            logger.warning(
                                "loop 节点 {} 退出表达式字段缺失({}),按未达标处理", node_id, exc
                            )
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
                "tool_calls": record.tool_calls,
                "tokens_in": record.tokens_in, "tokens_out": record.tokens_out,
            })

    # ── 小工具 ──
    @staticmethod
    def _first(target: Any) -> Optional[str]:
        if isinstance(target, str):
            return target
        if isinstance(target, list) and target:
            return target[0] if isinstance(target[0], str) else None
        return None

    async def _ensure_task(self, node_id: str, record: NodeRecord, context: dict[str, Any]) -> None:
        """决策=irrigate 但没落任务时,由引擎把这单补出来。

        为什么不让 Agent 自己保证:实测 glm-4-flash 会把「本轮决策:irrigate（任务 task-xxx）」
        写得像模像样,但**根本没调用 create_task** —— 任务号是编的,库里一行没有,
        执行管家没单可下、验证官没单可验,闭环却显示 success。换更大的模型也不稳,
        这类「必须发生」的副作用不该交给概率。引擎按决策正文的时长补建,
        是确定性行为,且可单测。

        已经落过单(LLM 真的调用了 / 降级兜底建过)就跳过,不会重复浇水。
        """
        if str(context.get("last_decision") or "") != "irrigate":
            return
        if context.get("last_task_no"):
            return
        found = DURATION_RE.search(record.output or "")
        duration = int(found.group(1)) if found else 30
        duration = max(5, min(120, duration))
        payload: dict[str, Any] = {
            "action": "pump",
            "params": {"duration_s": duration},
            "target_range": [55, 65],
            "created_by": "workflow-engine",   # 留痕:这单不是 Agent 建的
        }
        # 没有 device_id,create_task 只能落一张没有归属的空单(实测 assigned_device=NULL,
        # 调度器派不出去)。id 由基座按当前 mock/真机批次解析后放进起跑上下文。
        executor_device = context.get("executor_device")
        if executor_device:
            payload["device_id"] = executor_device
        try:
            value = await _maybe_await(
                self.tool_invoke("create_task", {"type": "device_cmd", "payload": payload, "priority": 9})
            )
        except Exception as exc:  # noqa: BLE001 建单失败要冒泡成节点失败,不许假装成功
            raise WorkflowError(f"节点 {node_id} 决策为 irrigate 但补建任务失败:{exc}") from exc
        task_no = ""
        if isinstance(value, dict):
            task_no = str(value.get("task_no") or "")
        if not task_no:
            raise WorkflowError(f"节点 {node_id} 补建任务未返回 task_no:{value!r}")
        context["last_task_no"] = task_no
        record.tool_calls = list(record.tool_calls) + [{
            "id": "engine-create_task", "name": "create_task",
            "arguments": {"type": "device_cmd", "payload": payload, "priority": 9},
            "status": "executed", "result": value,
        }]
        logger.warning("决策为 irrigate 但未落单,引擎已补建 {}（{}s）", task_no, duration)

    @staticmethod
    def _upstream(context: dict[str, Any], agent_key: str) -> list[str]:
        """PRD 8.3:下游 Agent 能看到上游结论,按出现顺序;自己不算上游。"""
        skip = {"trigger", "round", "tools", agent_key}
        items = [
            f"{key}:{value}" for key, value in context.items()
            if key not in skip and isinstance(value, str) and value
        ]
        # 任务号是字符串键里唯一没人写进正文的东西,单独递给执行管家:
        # 它没有 create_task 权限(PRD 8.1),必须知道该下发哪一单。
        task_no = context.get("last_task_no")
        if task_no and agent_key == "executor":
            items.append(f"task_no:{task_no}(本轮要下发的任务号,直接下发,不要新建)")
        return items

    @staticmethod
    def _extract(context: dict[str, Any], agent_key: str, content: str,
                 tool_calls: Optional[list[dict]] = None) -> None:
        """把关键结论提到顶层键,供 condition/loop 表达式引用(PRD 9.1 的 context.last_decision)。

        光靠正文正则不够:verifier 的结论往往在 `verify_result` 工具的返回里(结构化字段),
        正文只写「基线 38.5 → 复测 48.1」这种话,VERDICT_RE 匹配不到,于是 loop 的
        `last_verification == 'success'` 永远不成立,白跑修正轮。所以先看工具结果,再看正文。
        """
        if agent_key == "decision":
            found = DECISION_RE.search(content or "")
            if found:
                context["last_decision"] = found.group(1)
            for call in tool_calls or []:
                result = call.get("result")
                if call.get("name") == "create_task" and isinstance(result, dict) and result.get("task_no"):
                    context["last_task_no"] = result["task_no"]
        elif agent_key == "verifier":
            verdict = ""
            for call in tool_calls or []:
                result = call.get("result")
                if call.get("name") == "verify_result" and isinstance(result, dict):
                    verdict = str(result.get("verdict") or "")
                    if verdict:
                        break
            if not verdict:
                found = VERDICT_RE.search(content or "")
                verdict = found.group(1) if found else ""
            if verdict:
                context["last_verification"] = verdict


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
    # 起跑时的上下文事实(如本轮的下发终端/复测探头 id),由基座按当前模式解析。
    # 引擎自己不碰数据库,但要靠这些 id 把决策补建的任务落到正确的设备上。
    context_provider: Optional[Callable[[], dict]] = None


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
    init_context: dict = {}
    if _deps.context_provider is not None:
        try:
            init_context = dict(_deps.context_provider() or {})
        except Exception as exc:  # noqa: BLE001 取不到就空着跑,不能因此起不了跑
            logger.warning("起跑上下文解析失败(按空上下文跑):{}", exc)
    engine = WorkflowEngine(
        agent_runner_factory=_deps.agent_runner_factory,
        tool_invoke=_deps.tool_invoke,
        emit=_deps.emit,
    )

    async def _drive() -> None:
        try:
            result = await engine.run(dag, run_id=run_id, trigger=trigger,
                                      init_context=init_context)
            _deps.update_run(run_id, result.status, result.context, result.error)
        except Exception as exc:  # noqa: BLE001 后台任务异常必须落到 run 记录
            _deps.update_run(run_id, "failed", {}, f"{type(exc).__name__}: {exc}")

    try:
        asyncio.get_running_loop().create_task(_drive())
    except RuntimeError:  # 无事件循环(脚本/测试)时同步跑完
        asyncio.run(_drive())
    return run_id
