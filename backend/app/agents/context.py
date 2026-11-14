"""Agent 身份上下文(REQ-F-003 补充):让工具在 LLM 调用链里知道自己是谁。

背景:PRD 6.11 要求报警 source 形如 ``agent:verifier``,但 raise_alert 是走过去
LLM 工具调用的,schema 里没有 source 时 LLM 传不进来,只能永远落默认值。
本模块用 ContextVar 在工具执行期携带当前 agent_key:

- AgentRunner._execute_tool 进入工具调用前 set 当前 agent_key,结束 finally reset;
- core/tool_impl.raise_alert 的缺省 source 从这里取(队友 B 接入,见 docs/contracts);
- 只依赖标准库,避免 core ↔ agents 循环导入(agents/tools.py 会 import core.tool_impl)。

⚠️ 唯一权威的 ContextVar 在 **基座** `core/tool_impl.py`(队友 B 定义):工具实现读的是它,
set 必须 set 同一个对象,否则两边各持一个 ContextVar,读到空值、source 静默退化成 "agent"。
队长分支只有 agents/、没有 core/tool_impl.py,所以这里做了一层「有则复用、无则自建」的兼容;
`test_context.py::test_contextvar_is_shared_with_backend` 守住「合并后必须是同一个对象」。

约定:source 的落库形态统一 ``agent:<key>``;取不到 key 时退回 ``"agent"``(兼容旧数据)。
"""
from __future__ import annotations

from contextvars import ContextVar

DEFAULT_SOURCE = "agent"

try:  # 基座存在时以它为权威(合并后走这条分支)
    from app.core.tool_impl import CURRENT_AGENT_KEY  # type: ignore[attr-defined]
except ModuleNotFoundError as exc:
    # 只吞「基座还没合进来」这一种情况;其它导入错误必须原样抛出,别把真问题藏起来
    if exc.name not in {"app.core.tool_impl", "app.core"}:
        raise
    CURRENT_AGENT_KEY = ContextVar("current_agent_key", default="")


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


# ── 平台事实(设备清单)────────────────────────────────────────────────
# 背景(2026-11-14 真实 run 实测):LLM 不知道平台里设备 id 叫什么,把地点名
# 「A区茶垄」当成 device_id 传进 get_soil_status → 工具报「设备不存在」→ 六个
# Agent 全说「设备信息缺失」→ 决策 none → 一个任务都不创建。工具没错,是上下文缺了事实。
# 由接线层(workflow/wiring)在每次 run 里 set,AgentRunner._build_messages 拼进 system。
CURRENT_CONTEXT_NOTE = ContextVar("current_context_note", default="")


def current_context_note() -> str:
    return CURRENT_CONTEXT_NOTE.get() or ""


def set_context_note(note: str):
    """返回 token,调用方负责 reset(和 agent_key 一样的用法)。"""
    return CURRENT_CONTEXT_NOTE.set(note or "")


# ── 本轮执行终端 ──────────────────────────────────────────────────────
# 决策官真的（经 tool_choice 钉住）调用 create_task 时，它只会填动作与时长，
# payload 里没有 device_id。基座落库后 assigned_device 为空，调度器派不出去，
# 任务只能躺在队列里超时变 dead —— 比「没建单」更难看：画面上有一张单，却永远不动。
# 所以由接线层在 run 起跑时给出本批次的执行终端，AgentRunner 在建单前补进 payload，
# 不依赖模型是否记得填。
CURRENT_EXECUTOR_DEVICE = ContextVar("current_executor_device", default="")


def current_executor_device() -> str:
    return CURRENT_EXECUTOR_DEVICE.get() or ""


def set_executor_device(device_id: str):
    return CURRENT_EXECUTOR_DEVICE.set(device_id or "")


def reset_executor_device(token) -> None:
    CURRENT_EXECUTOR_DEVICE.reset(token)


# ── 本轮任务号 ────────────────────────────────────────────────────────
# 执行管家调 send_device_cmd 时,schema 里没有 task_no(PRD 7.3 只给了 device/action/params),
# 模型又时灵时不灵:run #17/#18 它照着上游提示填了,run #19 就没填 —— 于是 B 的
# `_pending_device_cmd` 认领失败(那张单已经有 assigned_device 了),send_cmd 另建一张新单:
# 决策单 0011 超时变 dead,真执行的 0012 与 run 脱钩,验证官还去验了那张没下发的 0011。
# 任务号是引擎已知的确定性事实,不该指望模型复述。
CURRENT_TASK_NO = ContextVar("current_task_no", default="")


def current_task_no() -> str:
    return CURRENT_TASK_NO.get() or ""


def set_current_task_no(task_no: str):
    return CURRENT_TASK_NO.set(task_no or "")


def reset_current_task_no(token) -> None:
    CURRENT_TASK_NO.reset(token)


