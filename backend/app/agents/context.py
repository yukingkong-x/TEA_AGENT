"""Agent 身份上下文(REQ-F-003 补充):让工具在 LLM 调用链里知道自己是谁。

背景:PRD 6.11 要求报警 source 形如 ``agent:verifier``,但 raise_alert 是走过去
LLM 工具调用的,schema 里没有 source 时 LLM 传不进来,只能永远落默认值。
本模块用 ContextVar 在工具执行期携带当前 agent_key:

- AgentRunner._execute_tool 进入工具调用前 set 当前 agent_key,结束 finally reset;
- core/tool_impl.raise_alert 的缺省 source 从这里取(队友 B 接入,见 docs/contracts);
- 只依赖标准库,避免 core ↔ agents 循环导入(agents/tools.py 会 import core.tool_impl)。

约定:source 的落库形态统一 ``agent:<key>``;取不到 key 时退回 ``"agent"``(兼容旧数据)。
"""
from __future__ import annotations

from contextvars import ContextVar

DEFAULT_SOURCE = "agent"

CURRENT_AGENT_KEY: ContextVar[str] = ContextVar("current_agent_key", default="")


def current_agent_key() -> str:
    """当前工具调用所属的 agent_key,不在 AgentRunner 工具循环内时返回空串。"""
    return CURRENT_AGENT_KEY.get() or ""


def current_agent_source() -> str:
    """PRD 6.11 的 source 形态:``agent:<key>``;拿不到 key 时退回 ``"agent"``。"""
    key = current_agent_key()
    if not key or key == DEFAULT_SOURCE:
        return DEFAULT_SOURCE
    if key == "system" or key.startswith("agent:"):
        return key
    return f"agent:{key}"
