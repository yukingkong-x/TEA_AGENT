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

# 决策口径从正文里提。真模型(run #26)写的是「本轮决策**为**irrigate」而不是
# 「本轮决策:irrigate」—— 只认冒号会把一次浇水决策读成「没决策」,分流走 false
# 分支去「无需作业归档」,画面显示一切正常、实际一滴水没浇。所以「为/是/冒号/直接跟」
# 都要吃;真正的确定性证据仍是 create_task 工具调用(见 _extract)。
DECISION_RE = re.compile(r"本轮决策\s*(?:[：:]\s*|为\s*|是\s*)?(irrigate|none|escalate)",
                         re.IGNORECASE)
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
    # 这条记录发生在第几轮(主链首验=1,Self-Loop 回跳的 body=2)。
    # 节点耗时表按它分组:不写的话,除 loop 节点外全是 0,前端只能显示「第 0 轮」。
    # 注意 by_id 按 node_id 去重,重跑的节点只留最后一轮的耗时(见 core/node_records 文档)。
    round_no: int = 0


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


def _final_status(context: dict[str, Any]) -> str:
    """跑完 ≠ 成功:Self-Loop 耗尽而仍未达标,必须落 needs_human(PRD 11.4.3)。

    run #28 现场:三轮验证全是 failed(达成率恒为 40.41%),loop 靠 `round > 2` 退出,
    run 却标 success —— 画布全绿、报告写「闭环成功」,而茶垄一次都没浇够。
    这是整个平台最危险的一种失败:数字都在,结论反了。
    """
    verdict = str(context.get("last_verification") or "")
    if verdict in {"failed", "needs_human"}:
        return "needs_human"
    return "success"


def _achievement_text(context: dict[str, Any]) -> str:
    detail = context.get("last_verification_detail") or {}
    achievement = detail.get("achievement")
    if achievement is None:
        return "无验证结论"
    return f"达成率 {achievement}%"


def _duration_in(payload: dict[str, Any]) -> float:
    """从任务载荷里取浇水时长:params.duration_s / 顶层 duration_s / params.seconds。

    决策官建单时把时长放在 params 里,修正单(引擎建)也是;老数据有写顶层的。
    取不到返回 0(调用方据此不覆盖设备层参数)。
    """
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    for value in (params.get("duration_s"), payload.get("duration_s"), params.get("seconds")):
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0.0


def _bind_executor_device(device_id: Any):
    """把本轮执行终端放进 ContextVar,供 AgentRunner 建单时补 payload.device_id。

    引擎不直接依赖 agents 包(它要能单测、也能在没有 Agent 层的环境跑),
    所以导入失败就静默跳过 —— 补不上时行为退回旧样(任务可能派不出去)。
    """
    if not device_id:
        return None
    try:
        from app.agents.context import set_executor_device

        return set_executor_device(str(device_id))
    except Exception:  # noqa: BLE001
        return None


def _release_executor_device(token) -> None:
    if token is None:
        return
    try:
        from app.agents.context import reset_executor_device

        reset_executor_device(token)
    except Exception:  # noqa: BLE001
        pass


def _bind_current_task(task_no: Any) -> None:
    """把本轮任务号放进 ContextVar,执行管家调 send_device_cmd 时带上。

    `send_device_cmd` 的 schema 里 `task_no` 是可选参数(agents/tools.py),
    模型时灵时不灵:run #19 没填 → 基座的认领逻辑不成立(那张单已有 assigned_device)
    → 又建一张新单,决策单超时变 dead、真执行的单与 run 脱钩。任务号是引擎已知事实,
    由这里给(agents/base._with_executor_device 在模型没填时用它补参)。
    """
    if not task_no:
        return
    try:
        from app.agents.context import set_current_task_no

        set_current_task_no(str(task_no))
    except Exception:  # noqa: BLE001
        pass


def _clear_current_task(token) -> None:
    if token is None:
        return
    try:
        from app.agents.context import reset_current_task_no

        reset_current_task_no(token)
    except Exception:  # noqa: BLE001
        pass


def _open_task_scope():
    """起跑时把任务号清空并拿一个 token,run 结束统一还原(不把上一条 run 的单带过来)。"""
    try:
        from app.agents.context import set_current_task_no

        return set_current_task_no("")
    except Exception:  # noqa: BLE001
        return None


def _bind_pump_duration(duration: Any) -> None:
    """Self-Loop 修正单的浇水时长放进 ContextVar,执行管家下发时以它为准。

    run #29 现场:修正单载荷写 19.9s,执行管家照着上一轮的「45 秒」下发,
    设备真浇了 45 秒 —— 达成率算得对、物理动作是错的。
    """
    try:
        from app.agents.context import set_pump_duration

        set_pump_duration(float(duration or 0))
    except Exception:  # noqa: BLE001
        pass


def _open_pump_scope():
    """起跑时清零,run 结束统一还原(上一轮的修正时长不能带进下一次)。"""
    try:
        from app.agents.context import set_pump_duration

        return set_pump_duration(0)
    except Exception:  # noqa: BLE001
        return None


def _release_pump_scope(token) -> None:
    if token is None:
        return
    try:
        from app.agents.context import reset_pump_duration

        reset_pump_duration(token)
    except Exception:  # noqa: BLE001
        pass


# ── run_id 的跨层传递(基座 core/run_context)─────────────────────────────
# create_task 落在工具层、send_cmd 落在设备层,两边都拿不到引擎的 run_id,schema 里
# 也不该出现它(LLM 不会填)。所以由引擎起跑时 set,基座在同一个 asyncio 上下文里读,
# tasks.run_id / verifications.run_id 才能落准。
# 以前不 set 时基座只能兜底「唯一 running 的那条才认」——并发跑两条就记 NULL。
def _bind_run_id(run_id: Any):
    if run_id is None:
        return None
    try:
        from app.core.run_context import set_current_run_id

        return set_current_run_id(int(run_id))
    except Exception:  # noqa: BLE001 基座未合入/无该模块:退回基座自己的兜底
        return None


def _release_run_id(token) -> None:
    if token is None:
        return
    try:
        from app.core.run_context import reset_current_run_id

        reset_current_run_id(token)
    except Exception:  # noqa: BLE001
        pass


async def _persist_node_records(run_id: Optional[int], result: Optional["RunResult"]) -> None:
    """把一次 run 的节点耗时落进 workflow_node_records(PRD 9.1 报告时间线)。

    为什么不能拿 task_events 顶:那条线挂在 task_no 上,决策=none 的巡园 run
    一条都没有;而且 start/condition/loop/tool 这些节点根本不发消息,却正好
    占着时间线的头尾和那 90 秒渗透等待。

    只落状态不是 pending 的节点:`result.nodes` 起跑时按整张 DAG 建齐(13 条),
    没走到的分支(决策=none 时的浇水/渗透)停在 pending。全落进去,报告时间线
    会多出「待执行」的幽灵行,汇总的节点数也和实际跑的对不上。

    记账失败绝不能把一次成功的 run 打成失败,所以整段吞异常(core/node_records 同约定)。
    """
    if not run_id or result is None:
        return
    executed = [r for r in (result.nodes or []) if r.status != "pending"]
    if not executed:
        return
    try:
        from app.core import node_records  # 基座模块;本分支不单独依赖它
    except Exception as exc:  # noqa: BLE001 未合入基座时不该炸
        logger.warning("节点记录模块不可用,run {} 的耗时表未落库:{}", run_id, exc)
        return
    try:
        added = await asyncio.to_thread(node_records.record_run_nodes, run_id, executed)
        logger.debug("run {} 节点记录落库 {} 条", run_id, added)
    except Exception as exc:  # noqa: BLE001
        logger.warning("run {} 节点记录落库失败:{}", run_id, exc)


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
        # 当前停留节点,供外层超时兜底报告「卡在哪」(run 24 卡死时无从下手)
        self.current_node = ""
        # 最后一次 run 的结果。正常路径由 run() 返回,但 wait_for 超时会取消协程、
        # 拿不到返回值 —— 那时节点耗时表只能从这份留底里取(见 start_run 的 _drive)。
        self.last_result: Optional[RunResult] = None

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
        # 本轮执行终端放进上下文:决策官真的调用 create_task 时,AgentRunner 用它补
        # payload.device_id(模型不会自己填,漏了就落一张派不出去的空单)。
        device_token = _bind_executor_device(context.get("executor_device"))
        task_token = _open_task_scope()
        pump_token = _open_pump_scope()
        try:
            await self._walk(start_id, nodes, by_id, context, result, stop_at=None, steps=[0])
            result.status = _final_status(context)
            if result.status == "needs_human":
                result.error = (f"Self-Loop 已用完仍未达标(最后一轮 "
                                f"{_achievement_text(context)}),转人工")
        except Exception as exc:  # noqa: BLE001 节点失败要把 run 标 failed,但不能吞掉原因
            result.status = "failed"
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            _clear_current_task(task_token)
            _release_pump_scope(pump_token)
            _release_executor_device(device_token)
            result.context = context
            result.duration_ms = int((time.monotonic() - started) * 1000)
            self.last_result = result
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
            # 轮次:主链首验算第 1 轮(此时 context.round 还是 0),loop 回跳的
            # body 已经 +1 变成第 2 轮。节点耗时表靠它分组。
            record.round_no = max(1, int(context.get("round") or 0))

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
        # 卡住时得知道停在哪:run 24 停在执行管家之后、验证官之前,日志里一个字都没有,
        # 只能靠猜节点顺序。节点进出各留一行,以后一眼看出是哪个节点没回来。
        self.current_node = f"{node_id}({node_type})"
        logger.info("▶ 节点 {} {} 开始（run {}）", node_id, record.name, result.run_id)
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
                # 进节点先把已知任务号递给 Agent:执行管家调 send_device_cmd 时,
                # schema 的 task_no(可选)由工具层补上,不必指望模型复述。
                _bind_current_task(context.get("last_task_no"))
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
                # 任务号已知(Agent 建的或引擎补的)就告诉下游,执行管家下发时自动带上
                _bind_current_task(context.get("last_task_no"))
                if agent_key == "decision":
                    # 本轮决策定的时长同样递给执行管家:它没有建单权限,却要传 params,
                    # 不告诉它就会照上一轮记的数字报一个(run #30:载荷 45s、实浇 60s)。
                    _bind_pump_duration(context.get("last_duration_s") or 0)
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
                # max_iterations 是**总轮次**上限(PRD 11.4「最多 2 轮」),不是「补跑次数」:
                # 主链刚跑完的那次验证已经算第 1 轮。按「补跑次数」算会变成 1+2=3 轮,
                # 而且最后一轮跑完再没人验证 —— 修正单建了却没执行,库里多一张会真
                # 浇水的孤儿单(跑满上限时尤其危险)。
                max_rounds = max(1, int(node.get("max_iterations", 1)))
                body = node.get("body_next")
                exit_expr = node.get("exit_expression", "")
                # 主链刚跑完的那次验证已经算第 1 轮;上游没产出验证结论的场合
                # (手工 DAG / 本轮压根没建任务)从 0 起算,否则 max_iterations=1
                # 会把 body 直接跳过 —— 那种情况下 body 本身就是「补一次」的机会。
                if context.get("last_verification"):
                    context["round"] = max(1, int(context.get("round", 0)))
                else:
                    context["round"] = int(context.get("round", 0))
                rounds = 0
                while True:
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
                    if context["round"] >= max_rounds:
                        break
                    context["round"] = int(context.get("round", 1)) + 1
                    rounds += 1
                    # 未达标才回到 body:先按验证层算好的修正方案落一张新单,
                    # 否则回跳只是拿同一批数据重复验证(run #28 三轮实测:
                    # 达成率恒为 40.41%,因为根本没人再浇一次水)。
                    await self._apply_correction(node_id, record, context)
                    await self._walk(body, nodes, by_id, context, result, stop_at=node_id, steps=steps)
                record.output = f"rounds={rounds}"
                # loop 节点的耗时是**包住整个 body 的聚合**(实测 run #33:99.7s),
                # 它本身只做一次表达式求值。轮次按结束时的轮次记,否则这条最慢记录
                # 会顶着一个「第 1 轮」的徽章,而它覆盖的其实是两轮。
                record.round_no = max(1, int(context.get("round") or 1))
                record.status = "done"
                return self._first(node.get("next"))

            raise WorkflowError(f"未知节点类型 {node_type}")
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record.duration_ms = int((time.monotonic() - begun) * 1000)
            logger.info("■ 节点 {} {} {}（{}ms）", node_id, record.name,
                        record.status, record.duration_ms)
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
        context["last_duration_s"] = float(duration)
        record.tool_calls = list(record.tool_calls) + [{
            "id": "engine-create_task", "name": "create_task",
            "arguments": {"type": "device_cmd", "payload": payload, "priority": 9},
            "status": "executed", "result": value,
        }]
        logger.warning("决策为 irrigate 但未落单,引擎已补建 {}（{}s）", task_no, duration)

    async def _apply_correction(self, node_id: str, record: NodeRecord,
                                context: dict[str, Any]) -> None:
        """Self-Loop 的「修正」这一步:按验证引擎给的方案建新任务(PRD 11.4.2)。

        为什么必须由引擎做:验证层已经按 11.4.1 的规则算出 correction
        (缺口>15→split / ≤15→topup / 浇了没升→suspect_data),但**没有人执行它**。
        run #28 实测三轮验证全是 40.41%:body 只回到验证官,既没建修正单也没再浇水,
        同一批传感器数据被反复验了三遍 —— 画布上循环转了,物理世界一动不动。

        suspect_data(数据可疑)不建单:先补测,不盲目再浇(PRD 11.4.1 第三条)。
        """
        correction = context.get("last_correction")
        if not isinstance(correction, dict) or not correction:
            return
        detail = context.get("last_verification_detail") or {}
        strategy = str(correction.get("strategy") or "")
        try:
            duration = float(correction.get("duration_s") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        feedback = {
            "round": context.get("round"),
            "strategy": strategy,
            "times": int(correction.get("times") or 1),
            "interval_s": correction.get("interval_s") or 0,
            "duration_s": duration,
            "gap": correction.get("gap", detail.get("gap")),
            "reason": correction.get("reason") or "",
            "from_task_no": detail.get("task_no"),
            "verification_round": detail.get("round_no"),
        }
        if strategy == "suspect_data" or duration <= 0:
            logger.warning("Self-Loop 修正策略 {} 无需建单(先复测):{}",
                           strategy or "?", feedback["reason"])
            feedback["to_task_no"] = ""
            context.setdefault("feedbacks", []).append(feedback)
            return

        duration = max(5.0, min(120.0, duration))
        payload: dict[str, Any] = {
            "action": "pump",
            "params": {"duration_s": duration},
            "target_range": [55, 65],
            "created_by": "workflow-engine",
            "trigger": "selfloop",           # PRD 11.4.2 的修正任务标记
        }
        executor_device = context.get("executor_device")
        if executor_device:
            payload["device_id"] = executor_device
        try:
            value = await _maybe_await(
                self.tool_invoke("create_task",
                                 {"type": "device_cmd", "payload": payload, "priority": 8})
            )
        except Exception as exc:  # noqa: BLE001 修正建单失败要冒泡,不能假装修过了
            raise WorkflowError(f"节点 {node_id} Self-Loop 修正建单失败:{exc}") from exc
        task_no = str((value or {}).get("task_no") or "") if isinstance(value, dict) else ""
        if not task_no:
            raise WorkflowError(f"节点 {node_id} Self-Loop 修正建单未返回 task_no:{value!r}")

        context["last_task_no"] = task_no
        context["last_duration_s"] = duration
        # 新单还没验过:清掉上一轮的结论,否则 loop 的退出表达式会拿旧值判
        context["last_verification"] = ""
        _bind_pump_duration(duration)
        record.tool_calls = list(record.tool_calls) + [{
            "id": "engine-self-loop", "name": "create_task",
            "arguments": {"type": "device_cmd", "payload": payload, "priority": 8},
            "status": "executed", "result": value,
        }]
        feedback["to_task_no"] = task_no
        context.setdefault("feedbacks", []).append(feedback)
        logger.warning("Self-Loop 第 {} 轮未达标({}),已按 {} 建修正单 {} {}s",
                       feedback["round"], f"{detail.get('achievement')}%",
                       strategy, task_no, duration)

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
                # 归一成小写:DAG 的表达式写的是 == 'irrigate',模型偶尔写成 Irrigate
                context["last_decision"] = found.group(1).lower()
            for call in tool_calls or []:
                result = call.get("result")
                if call.get("name") == "create_task" and isinstance(result, dict) and result.get("task_no"):
                    context["last_task_no"] = result["task_no"]
                    # 真的建了单就不可能是否决:工具事实优先于正文措辞。
                    # (run #26 正文写「本轮决策为irrigate」没被旧正则抓到,分流走了
                    # 「无需作业归档」——有单却没执行,比判错更难看。)
                    context["last_decision"] = "irrigate"
                    # 建单时定的时长也要记下来:执行管家下发时会照自己记的数字报一遍,
                    # run #30 实测载荷 45s、设备真浇 60s(模型传了 60)。时长和任务号一样,
                    # 是引擎给的事实,不能两处各说一套。
                    args = call.get("arguments") or {}
                    payload = args.get("payload") if isinstance(args, dict) else None
                    if isinstance(payload, dict):
                        dur = _duration_in(payload)
                        if dur:
                            context["last_duration_s"] = dur
        elif agent_key == "verifier":
            verdict = ""
            detail: dict = {}
            for call in tool_calls or []:
                result = call.get("result")
                if call.get("name") == "verify_result" and isinstance(result, dict):
                    verdict = str(result.get("verdict") or "")
                    if verdict:
                        detail = result
                        break
            if not verdict:
                found = VERDICT_RE.search(content or "")
                verdict = found.group(1) if found else ""
            if verdict:
                context["last_verification"] = verdict
            # 验证层已经按 PRD 11.4.1 算好修正方案(topup/split/suspect_data),
            # 引擎直接拿来建单,不重复实现规则、也不指望模型自己算。
            if detail:
                context["last_verification_detail"] = {
                    "task_no": detail.get("task_no"),
                    "baseline": detail.get("baseline"),
                    "measured": detail.get("measured"),
                    "achievement": detail.get("achievement"),
                    "confidence": detail.get("confidence"),
                    "gap": detail.get("gap"),
                    "round_no": detail.get("round_no"),
                    "correction": detail.get("correction") or {},
                }
                correction = detail.get("correction")
                if isinstance(correction, dict) and correction:
                    context["last_correction"] = correction


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

# 单次 run 的硬上限:正常一轮 90-180s(含 90s 渗透等待 + 7 个 Agent),给到 8 分钟。
# 超过就认定卡死,宁可报 failed 也不能让 run 永远 running。
RUN_TIMEOUT_S = 480.0


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
        # run_id 跟着上下文走:create_task / send_cmd 在工具层与设备层落库时读它,
        # 不靠基座「唯一 running 才认」的兜底(并发跑两条就记 NULL)。
        run_token = _bind_run_id(run_id)
        run_result: Optional[RunResult] = None
        try:
            # 兜底超时:节点里任何一次 await 不回来(限流退避、工具卡死、MQTT 失联),
            # run 就会永远挂在 running,前端只能一直转圈,演示当场死掉。
            # 超时后标记 failed 并写明最后节点,至少是「明确失败」而不是「假装进行中」。
            run_result = await asyncio.wait_for(
                engine.run(dag, run_id=run_id, trigger=trigger, init_context=init_context),
                timeout=RUN_TIMEOUT_S,
            )
            _deps.update_run(run_id, run_result.status, run_result.context, run_result.error)
        except asyncio.TimeoutError:
            logger.error("run {} 超过 {}s 未结束,最后停留节点 {}", run_id, RUN_TIMEOUT_S,
                         engine.current_node or "未知")
            _deps.update_run(run_id, "failed", {},
                             f"运行超时(>{RUN_TIMEOUT_S:.0f}s),最后节点 {engine.current_node or '未知'}")
        except Exception as exc:  # noqa: BLE001 后台任务异常必须落到 run 记录
            _deps.update_run(run_id, "failed", {}, f"{type(exc).__name__}: {exc}")
        finally:
            # 节点耗时表(PRD 9.1)。放 finally:失败的 run 也要有耗时 —— 「熔断」
            # 那条演示线正是靠它说明「停在哪个节点、卡了多久」。
            # 超时/异常时 wait_for 没交付 result,退回引擎自己留住的那份(见 run 的 finally)。
            await _persist_node_records(run_id, run_result or engine.last_result)
            _release_run_id(run_token)

    try:
        asyncio.get_running_loop().create_task(_drive())
    except RuntimeError:  # 无事件循环(脚本/测试)时同步跑完
        asyncio.run(_drive())
    return run_id
