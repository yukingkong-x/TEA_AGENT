"""REQ-F-002:AgentRunner(PRD 8.3 运行时行为)。

职责:构造消息 → 调 LLM → 解析工具调用 → 权限检查 → 执行 → 回填,
最多 6 轮工具循环;降级时走 20.2 规则模板并打「模型降级中」标记。
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from loguru import logger

from app.agents.context import (
    CURRENT_AGENT_KEY,
    current_context_note,
    current_executor_device,
    current_pump_duration,
    current_task_no,
)
from app.agents.fallback import DEGRADED_PREFIX, FALLBACKS, generic_fallback
from app.agents.prompts import AgentSpec
from app.agents.tools import ToolRegistry

SECTION_RE = re.compile(r"【([^】]+)】([^【]*)")
# 降级时规则模板判「要浇水」的标志词(decision_fallback 固定输出 irrigate/none)。
# 只认 irrigate:模板里「无需灌溉」这类否定句不会误触发建单。
IRRIGATE_RE = re.compile(r"irrigate", re.IGNORECASE)
# 「说了要动手」必须变成真 tool_call 的 Agent:agent_key → 必调工具名。
# 为什么不能只靠提示词:run #9 与 run #13 两次实测,glm-4-flash 都把 create_task 的参数
# 写进了正文(连任务号「task-xxx」都编好了),tool_calls 却是空的 —— 平台侧一行任务都没有。
# 小模型对「必须调用工具」这句话不可靠,把 choice 钉到具体函数才收得住。
# executor 同理(run #20):它播报「任务 xxx:已下发」,但一个 send_device_cmd 都没调,
# 设备根本没收到指令 → 任务超时重试 → 复测湿度不升 → 验证连转三轮人工。
REQUIRED_TOOL: dict[str, str] = {
    "decision": "create_task",
    "executor": "send_device_cmd",
}
# 正文里的占位任务号(模型编的):task-xxx / task-2026xxxx 这类。真号形如 task-20261114-0009。
PLACEHOLDER_TASK_NO_RE = re.compile(r"task-[0-9A-Za-z_-]*[xX][0-9A-Za-z_-]*")


@dataclass
class AgentTurn:
    agent_key: str
    content: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    degraded: bool = False


def parse_sections(text: str) -> dict[str, str]:
    """提取【xxx】yyy 格式的命名段落(PRD 8.2 输出格式)。"""
    return {name: body.strip() for name, body in SECTION_RE.findall(text)}


def _supports_tool_choice(llm: Any) -> bool:
    """LLM 客户端是否接受 tool_choice 形参。

    生产的 `core/llm.py` 打了透传补丁后支持;测试替身/旧实现没有。
    不做 try/except TypeError 试探 —— TypeError 也可能来自 provider 内部,
    那会把「真错误」当成「不支持」吞掉。签名检查是确定的。
    """
    complete = getattr(llm, "complete", None)
    if complete is None:
        return False
    try:
        params = inspect.signature(complete).parameters
    except (TypeError, ValueError):
        return False
    if "tool_choice" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _with_executor_device(tool_name: str, arguments: dict) -> dict:
    """补上模型没填、但平台必须有的两个字段。

    1. `create_task` 的 device_cmd 任务:模型的参数里只有 action/params/target_range,
       没有 device_id;基座落库后 assigned_device 为空 → 调度器派不出去 → 那张单永远不动。
    2. `send_device_cmd` 的 task_no:schema 里它是可选字段(2026-11-14 按队友 B 的要求
       补上,基座 core/tool_impl.send_device_cmd 早就支持),但模型仍然时灵时不灵 ——
       run #19 没填 → `_pending_device_cmd` 认领失败 → send_cmd 另建一张新单:
       决策单超时变 dead、真执行的单与 run 脱钩、验证官去验那张没下发的。
    两者都由接线层在起跑/决策落地时给出(agents/context),这里只做填充,模型填了就不覆盖。
    """
    if not isinstance(arguments, dict):
        return arguments

    if tool_name == "send_device_cmd":
        patched = dict(arguments)
        changed = False
        if not patched.get("task_no"):
            task_no = current_task_no()
            if task_no:
                patched["task_no"] = task_no
                changed = True
                logger.debug("下发指令缺少 task_no,按本轮任务补成 {}", task_no)
        # 修正单的时长以引擎算出的为准:模型手里还留着上一轮的「45 秒」
        duration = current_pump_duration()
        if duration > 0 and patched.get("action") in (None, "", "pump"):
            params = patched.get("params") if isinstance(patched.get("params"), dict) else {}
            if float(params.get("duration_s") or 0) != duration:
                patched["params"] = {**params, "duration_s": duration}
                changed = True
                logger.debug("下发指令沿用旧时长,按修正单改成 {}s", duration)
        return patched if changed else arguments

    if tool_name != "create_task" or arguments.get("type") != "device_cmd":
        return arguments
    device = current_executor_device()
    if not device:
        return arguments
    payload = arguments.get("payload")
    if not isinstance(payload, dict) or payload.get("device_id"):
        return arguments
    patched = json.loads(json.dumps(arguments, default=str))
    patched["payload"]["device_id"] = device
    logger.debug("建单缺少 device_id,按本轮执行终端补成 {}", device)
    return patched


def _soil_moisture_of(soil: dict) -> Optional[float]:
    """从 get_soil_status 的返回里挑出湿度数值。

    基座实现给的是扁平 `moisture`;老实现给 `soil_moisture`;也有 `readings` 嵌套形态。
    取不到(含 moisture=None,即「还没采到数」)一律返回 None —— 由模板判 escalate。
    """
    for key in ("moisture", "soil_moisture"):
        value = soil.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    readings = soil.get("readings")
    if isinstance(readings, dict):
        for key in ("soil_moisture", "moisture"):
            item = readings.get(key)
            if isinstance(item, dict):
                value = item.get("value")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
    return None


class AgentRunner:
    def __init__(
        self,
        agent_key: str,
        llm: Any,
        registry: ToolRegistry,
        spec: AgentSpec,
        history_limit: int = 10,
        max_tool_rounds: int = 6,
        get_context: Optional[Callable[[], Any]] = None,
    ):
        self.agent_key = agent_key
        self.llm = llm
        self.registry = registry
        self.spec = spec
        self.history_limit = history_limit
        self.max_tool_rounds = max_tool_rounds
        self.get_context = get_context

    async def run(self, task: str, history: Optional[list[dict]] = None,
                  upstream: Optional[list[str]] = None) -> AgentTurn:
        turn = AgentTurn(agent_key=self.agent_key)
        messages = self._build_messages(task, history or [], upstream or [])
        # 全量下发,权限在执行时把关(拒绝留痕即证据)
        schemas = self.registry.to_openai_schemas()
        for _ in range(self.max_tool_rounds):
            result = await self.llm.complete(
                messages,
                tools=schemas,
                temperature=self.spec.temperature,
            )
            turn.tokens_in += result.tokens_in
            turn.tokens_out += result.tokens_out
            turn.latency_ms += result.latency_ms
            if result.degraded:
                return await self._degraded_turn(turn)
            if result.tool_calls:
                messages.append({
                    "role": "assistant", "content": result.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": tc.arguments_raw}}
                        for tc in result.tool_calls
                    ],
                })
                for tc in result.tool_calls:
                    record, feedback = await self._execute_tool(tc)
                    turn.tool_calls.append(record)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": feedback})
                continue
            turn.content = result.content or ""
            break
        else:  # 6 轮全部是工具调用 → 强制输出(PRD 8.3 第 2 条)
            turn.content = turn.content or f"[已到工具调用上限({self.max_tool_rounds} 轮),强制输出]"
        await self._enforce_required_tool(turn, messages, schemas)
        self._patch_task_no(turn)
        turn.sections = parse_sections(turn.content)
        return turn

    def _build_messages(self, task: str, history: list[dict], upstream: list[str]) -> list[dict]:
        note = ""
        truncated = history
        if len(history) > self.history_limit:
            note = f"[前文摘要] 已省略最早的 {len(history) - self.history_limit} 条历史消息。"
            truncated = history[-self.history_limit:]
        parts = []
        if note:
            parts.append(note)
        parts.append(task)
        if upstream:
            parts.append("上游结论:\n" + "\n".join(f"- {u}" for u in upstream))
        # 平台事实(设备清单):没有它 Agent 只能瞎猜 device_id,工具必然报「设备不存在」
        system = self.spec.system_prompt
        facts = current_context_note()
        if facts:
            system = f"{system}\n\n{facts}"
        # 本轮任务号同理:它是引擎给的事实,不该让模型从上游正文里摘(上游写的是
        # 「任务 task-xxx」占位时,摘下来只会更错)。写进 system 后模型能自己填
        # send_device_cmd / verify_result 的 task_no;没填的由工具层用同一个值兜底。
        task_no = current_task_no()
        if task_no:
            system = (f"{system}\n\n[本轮任务号] {task_no}"
                      f"(send_device_cmd 与 verify_result 的 task_no 都填它,不要自己编号)")
        return (
            [{"role": "system", "content": system}]
            + truncated
            + [{"role": "user", "content": "\n".join(parts)}]
        )

    async def _execute_tool(self, tc) -> tuple[dict, str]:
        if not self.registry.can_use(self.agent_key, tc.name):
            return (
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments,
                 "status": "denied", "reason": "permission"},
                json.dumps({"error": "工具调用被拒绝:权限不足"}, ensure_ascii=False),
            )
        arguments = _with_executor_device(tc.name, tc.arguments or {})
        # 工具执行期携带当前 agent 身份:raise_alert 的 source 缺省值靠它(PRD 6.11)
        token = CURRENT_AGENT_KEY.set(self.agent_key)
        try:
            value = await self.registry.invoke(tc.name, arguments)
            return (
                {"id": tc.id, "name": tc.name, "arguments": arguments,
                 "status": "executed", "result": value},
                json.dumps(value, ensure_ascii=False, default=str),
            )
        except Exception as exc:  # noqa: BLE001 工具异常必须回填给 LLM,不许崩掉整轮
            return (
                {"id": tc.id, "name": tc.name, "arguments": arguments,
                 "status": "error", "error": str(exc)},
                json.dumps({"error": str(exc)}, ensure_ascii=False),
            )
        finally:
            CURRENT_AGENT_KEY.reset(token)

    async def _enforce_required_tool(self, turn: AgentTurn, messages: list[dict],
                                    schemas: list[dict]) -> None:
        """把「正文里说了要动手」钉成真 tool_call。

        现场(run #9 / #13,两次都是 glm-4-flash):决策官输出
        「【决策】本轮决策:irrigate(任务 task-xxx)」,参数齐全、任务号编好了,
        但 `tool_calls` 为空 —— 库里一行任务都没有。提示词写「必须先调用工具」不管用,
        这类「必须发生」的副作用要在客户端把 choice 钉到具体函数(`tool_choice`)。
        同样的病 run #20 出在执行管家身上:播报「任务 xxx:已下发」,send_device_cmd
        一次都没调,设备没收到指令、任务超时重试、复测湿度为零、验证连转三轮人工。
        只补一次,且只在「本轮确实要动手」时补:none 的轮次硬建单会变成无故浇水,
        没有待下发任务时硬发指令会打到空气上。
        """
        want = REQUIRED_TOOL.get(self.agent_key)
        if not want or turn.degraded:
            return
        if any(r.get("name") == want and r.get("status") == "executed" for r in turn.tool_calls):
            return
        if self.agent_key == "decision" and not IRRIGATE_RE.search(turn.content or ""):
            return
        # 执行管家:没有待下发的单就不用硬发(比如决策 none 的轮次)
        if self.agent_key == "executor" and not current_task_no():
            logger.warning("executor 本轮没有待下发任务号，跳过强制 send_device_cmd")
            return
        if want not in self.spec.tools:      # 没被授权的工具不能硬塞(PRD 8.1)
            logger.warning("{} 需要 {} 但未获授权，跳过强制调用", self.agent_key, want)
            return
        narrowed = [s for s in schemas if (s.get("function") or {}).get("name") == want]
        if not narrowed:                     # 工具没注册时无从下手,交给引擎兜底
            return

        kwargs: dict[str, Any] = {"tools": narrowed, "temperature": self.spec.temperature}
        if _supports_tool_choice(self.llm):
            # 标准写法,不用 "required":部分 OpenAI 兼容实现不认这个枚举值会直接 400
            kwargs["tool_choice"] = {"type": "function", "function": {"name": want}}
        else:
            logger.warning("LLM 客户端不支持 tool_choice(core/llm.py 未打补丁),"
                           "{} 只能靠收窄工具集再试一次", self.agent_key)

        nudge = (
            f"你刚才只在正文里描述了 {want} 的调用,但没有真正发出 tool_call,"
            f"平台侧没有产生任何任务。请立刻调用 {want} 完成下单。"
            f"(任务号以工具返回为准,不要在正文里自己编)"
        )
        try:
            result = await self.llm.complete(
                messages + [
                    {"role": "assistant", "content": turn.content or ""},
                    {"role": "user", "content": nudge},
                ],
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 强制补救失败不该炸掉整轮 Agent
            logger.warning("{} 强制调用 {} 失败:{}", self.agent_key, want, exc)
            return

        turn.tokens_in += result.tokens_in
        turn.tokens_out += result.tokens_out
        turn.latency_ms += result.latency_ms
        if result.degraded:
            logger.warning("{} 强制调用时模型降级,留给引擎兜底", self.agent_key)
            return
        if not result.tool_calls:
            logger.warning("{} 钉了 tool_choice 仍未发出 {} 调用,留给引擎兜底", self.agent_key, want)
            return
        for tc in result.tool_calls:
            record, _feedback = await self._execute_tool(tc)
            turn.tool_calls.append(record)
        if any(r.get("name") == want and r.get("status") == "executed" for r in turn.tool_calls):
            logger.info("{} 经 tool_choice 补出 {} 调用", self.agent_key, want)

    @staticmethod
    def _patch_task_no(turn: AgentTurn) -> None:
        """正文里模型自己编的占位任务号(task-xxx)换成工具返回的真号。

        否则验证官拿 `task-xxx` 去查,永远「任务不存在」,一段闭环卡在验证;
        前端对话剧场也会把假号显示给评委。
        """
        real = ""
        for record in reversed(turn.tool_calls):
            result = record.get("result")
            if isinstance(result, dict) and result.get("task_no"):
                real = str(result["task_no"])
                break
        if not real:
            return
        content = turn.content or ""
        patched = PLACEHOLDER_TASK_NO_RE.sub(real, content)
        if patched != content:
            logger.warning("{} 正文里的占位任务号已换成真号 {}", turn.agent_key, real)
            turn.content = patched

        # 提示词模板里的「对A区执行浇水X秒」,模型会原样抄进正文 —— 演示页面直接显示这句
        duration = ""
        for record in reversed(turn.tool_calls):
            arguments = record.get("arguments")
            if record.get("name") != "create_task" or not isinstance(arguments, dict):
                continue
            params = (arguments.get("payload") or {}).get("params") or {}
            value = params.get("duration_s") if isinstance(params, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                duration = str(int(value))
                break
        if duration:
            patched = re.sub(r"[Xx×]\s*秒", f"{duration}秒", turn.content or "")
            if patched != turn.content:
                logger.info("{} 正文里的时长占位已换成 {}秒", turn.agent_key, duration)
                turn.content = patched

    async def _degraded_turn(self, turn: AgentTurn) -> AgentTurn:
        turn.degraded = True
        context = await self._collect_context()
        fallback = FALLBACKS.get(self.agent_key)
        text = fallback(context) if fallback else generic_fallback(self.agent_key)
        turn.content = DEGRADED_PREFIX + text
        await self._degraded_act(turn, context)
        turn.sections = parse_sections(turn.content)
        return turn

    async def _collect_context(self) -> dict:
        """降级模板要用的实况：能拿到真数据就别用占位符。

        原来这里只读 get_context()，而 get_context 在生产链路上从没被注入过
        （workflow/wiring 只传 llm 与 registry），于是 context 恒为 {}：
        - 决策模板取不到 soil_moisture 就退 100.0 → 永远「墒情不缺水」→ 永远 none；
        - 巡园模板播报成「气温-℃ 空气湿度-% 光照-lux」。
        降级是赛题要演示的能力，演示时全是「-」和假 none 等于当场翻车。
        工具层已接真实现，直接读就行（这是平台侧的规则兜底，不是 LLM 越权）。
        注意：`get_soil_status` 的 moisture 可以是 None（还没采到数据），
        这时**不写入** soil_moisture，让模板走 escalate，而不是编一个 100%。
        """
        context: dict = {}
        if self.get_context is not None:
            maybe = self.get_context()
            if inspect.isawaitable(maybe):
                maybe = await maybe
            context = dict(maybe or {})

        if "soil_status" not in context or "soil_moisture" not in context:
            try:
                soil = await self.registry.invoke("get_soil_status", {})
                if isinstance(soil, dict) and soil:
                    context.setdefault("soil_status", soil)
                    value = _soil_moisture_of(soil)
                    if isinstance(value, (int, float)):
                        context.setdefault("soil_moisture", float(value))
            except Exception as exc:  # noqa: BLE001 取不到就让它缺失，模板会按缺失处理
                logger.warning("降级取墒情失败：{}", exc)

        if "env_status" not in context:
            try:
                env = await self.registry.invoke("get_env_status", {})
                if isinstance(env, dict) and env:
                    context.setdefault("env_status", env)
            except Exception as exc:  # noqa: BLE001
                logger.warning("降级取环控失败：{}", exc)

        if "has_rain_alert" not in context or "has_frost_alert" not in context:
            try:
                weather = await self.registry.invoke("get_weather", {})
                if isinstance(weather, dict):
                    rain = weather.get("rain_prob")
                    frost = weather.get("frost_risk")
                    context.setdefault("has_rain_alert",
                                       isinstance(rain, (int, float)) and rain >= 60)
                    context.setdefault("has_frost_alert",
                                       bool(frost) and str(frost).lower() not in {"none", "no", "无"})
            except Exception as exc:  # noqa: BLE001
                logger.warning("降级取天气失败：{}", exc)
        return context

    async def _degraded_act(self, turn: AgentTurn, context: dict) -> None:
        """降级不等于可以不动手：规则模板判了 irrigate，就必须真的把任务建出来。

        原来降级直接 return，规则模板说「对A区执行浇水30秒」，但 tasks 表一行没有，
        执行管家/验证官全部拿不到单，工作流却显示 success。演示时一按「模型降级」
        故障注入，闭环必断——而降级恰恰是赛题要看的能力。
        """
        if self.agent_key != "decision" or not IRRIGATE_RE.search(turn.content or ""):
            return
        if "create_task" not in self.spec.tools:
            return
        payload: dict = {
            "action": "pump",
            "params": {"duration_s": 30},
            "target_range": [55, 65],
            "degraded": True,
        }
        baseline = context.get("soil_moisture")
        if isinstance(baseline, (int, float)):
            payload["baseline"] = float(baseline)
        arguments = {"type": "device_cmd", "payload": payload, "priority": 9}
        token = CURRENT_AGENT_KEY.set(self.agent_key)
        try:
            value = await self.registry.invoke("create_task", arguments)
            turn.tool_calls.append(
                {"id": "degraded-create_task", "name": "create_task",
                 "arguments": arguments, "status": "executed", "result": value}
            )
            logger.warning("决策官降级仍建单：{}（规则模板 30s）", value.get("task_no"))
        except Exception as exc:  # noqa: BLE001 建单失败要留痕，不能假装下过单
            turn.tool_calls.append(
                {"id": "degraded-create_task", "name": "create_task",
                 "arguments": arguments, "status": "error", "error": str(exc)}
            )
            logger.error("决策官降级建单失败：{}", exc)
        finally:
            CURRENT_AGENT_KEY.reset(token)
