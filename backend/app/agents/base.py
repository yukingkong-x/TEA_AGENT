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

from app.agents.fallback import DEGRADED_PREFIX, FALLBACKS, generic_fallback
from app.agents.prompts import AgentSpec
from app.agents.tools import ToolRegistry

SECTION_RE = re.compile(r"【([^】]+)】([^【]*)")


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
        return (
            [{"role": "system", "content": self.spec.system_prompt}]
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

    async def _degraded_turn(self, turn: AgentTurn) -> AgentTurn:
        turn.degraded = True
        context: dict = {}
        if self.get_context is not None:
            maybe = self.get_context()
            if inspect.isawaitable(maybe):
                maybe = await maybe
            context = maybe or {}
        fallback = FALLBACKS.get(self.agent_key)
        text = fallback(context) if fallback else generic_fallback(self.agent_key)
        turn.content = DEGRADED_PREFIX + text
        turn.sections = parse_sections(turn.content)
        return turn
