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

from app.agents.context import CURRENT_AGENT_KEY, current_context_note
from app.agents.fallback import DEGRADED_PREFIX, FALLBACKS, generic_fallback
from app.agents.prompts import AgentSpec
from app.agents.tools import ToolRegistry

SECTION_RE = re.compile(r"【([^】]+)】([^【]*)")
# 降级时规则模板判「要浇水」的标志词(decision_fallback 固定输出 irrigate/none)。
# 只认 irrigate:模板里「无需灌溉」这类否定句不会误触发建单。
IRRIGATE_RE = re.compile(r"irrigate", re.IGNORECASE)


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
        for _ in range(self.max_tool_rounds):
            result = await self.llm.complete(
                messages,
                tools=self.registry.to_openai_schemas(),  # 全量下发,权限在执行时把关(拒绝留痕即证据)
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
        # 工具执行期携带当前 agent 身份:raise_alert 的 source 缺省值靠它(PRD 6.11)
        token = CURRENT_AGENT_KEY.set(self.agent_key)
        try:
            value = await self.registry.invoke(tc.name, tc.arguments or {})
            return (
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments,
                 "status": "executed", "result": value},
                json.dumps(value, ensure_ascii=False, default=str),
            )
        except Exception as exc:  # noqa: BLE001 工具异常必须回填给 LLM,不许崩掉整轮
            return (
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments,
                 "status": "error", "error": str(exc)},
                json.dumps({"error": str(exc)}, ensure_ascii=False),
            )
        finally:
            CURRENT_AGENT_KEY.reset(token)

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
        - 决策模板取 soil_moisture 的缺省值 100.0 → 永远「墒情不缺水」→ 永远 none；
        - 巡园模板播报成「气温-℃ 空气湿度-% 光照-lux」。
        降级是赛题要演示的能力，演示时全是「-」和假 none 等于当场翻车。
        工具层已接真实现，直接读就行（这是平台侧的规则兜底，不是 LLM 越权）。
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
                    value = soil.get("moisture")
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
