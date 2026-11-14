"""报警来源（source）的身份传递测试。

守的是 PRD 6.11：alerts.source 必须能区分发起方，否则大屏上「验证不通过自动报的警」
和「LLM 自己报的警」长得一模一样，演示时说不清是谁判的。

三条路径都要覆盖：
1. 缺省 + 无上下文      → "agent"（历史值，兜底不炸）
2. 缺省 + 有上下文      → "agent:{key}"（LLM 走工具调用的主路径）
3. 显式传参             → 原样 / 自动补 agent: 前缀（verification 直连的主路径）
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import tool_impl  # noqa: E402
from app.core.tool_impl import (  # noqa: E402
    CURRENT_AGENT_KEY,
    current_agent_key,
    normalize_alert_source,
)


@pytest.fixture(autouse=True)
def _clean_context():
    """每个用例从干净的上下文开始，避免相互污染。"""
    token = CURRENT_AGENT_KEY.set("")
    yield
    CURRENT_AGENT_KEY.reset(token)


# --------------------------------------------------------------- 与队长模块同一份存储
def test_shares_the_same_contextvar_object_with_agents_module():
    """变量必须是队长的同一个对象，不能各建一份。

    这是本模块最容易被改坏的地方：两边都叫 current_agent_key 也**不是同一份存储**，
    队长在 _execute_tool 里 set 完之后，我这边 get() 拿到的还是空——
    source 会静默退化成 "agent"，而且不报错、不告警，只有演示时看大屏才发现。
    """
    agent_ctx = pytest.importorskip("app.agents.context", reason="没拷 agents/ 的独立环境")

    assert tool_impl.CURRENT_AGENT_KEY is agent_ctx.CURRENT_AGENT_KEY


def test_runner_style_set_is_visible_to_raise_alert(monkeypatch):
    """复现队长的真实调用顺序：base.py set → 工具调用 → raise_alert 读。"""
    captured: dict[str, str] = {}

    def fake_push_alert(db, level, source, message):
        captured["source"] = source
        return {"id": 1, "level": level, "source": source, "message": message}

    import contextlib

    monkeypatch.setattr(tool_impl, "push_alert", fake_push_alert)
    monkeypatch.setattr(tool_impl, "session_scope", lambda: contextlib.nullcontext(None))

    from app.agents.context import CURRENT_AGENT_KEY as runner_var

    token = runner_var.set("verifier")   # ← 队长 base.py 里就是这样写的
    try:
        tool_impl.raise_alert("critical", "实测湿度未达目标区间")
    finally:
        runner_var.reset(token)

    assert captured["source"] == "agent:verifier"


# --------------------------------------------------------------- 纯函数口径
def test_source_falls_back_to_bare_agent_without_context():
    assert normalize_alert_source(None) == "agent"


def test_source_uses_contextvar_key():
    CURRENT_AGENT_KEY.set("scout")
    assert normalize_alert_source(None) == "agent:scout"


def test_explicit_namespaced_source_is_kept_as_is():
    assert normalize_alert_source("agent:verifier") == "agent:verifier"
    assert normalize_alert_source("system:safety") == "system:safety"


def test_bare_key_gets_agent_prefix():
    """调用方写成半截（source="verifier"）也要落成规范形态。"""
    assert normalize_alert_source("verifier") == "agent:verifier"


def test_bare_namespace_is_not_prefixed():
    """LLM 的 schema enum 里含 "system"，它已经是命名空间了，不能补成 agent:system。

    否则系统报警会被冒充成 agent 报警，大屏上分不出「安全阀跳了」和「智能体报的」。
    """
    assert normalize_alert_source("system") == "system"
    assert normalize_alert_source("agent") == "agent"
    assert normalize_alert_source("user") == "user"


def test_explicit_source_wins_over_contextvar():
    """verification 直连调用时显式传参必须压过上下文，否则会落成调用者的身份。"""
    CURRENT_AGENT_KEY.set("executor")
    assert normalize_alert_source("agent:verifier") == "agent:verifier"


def test_blank_source_falls_back_to_context_then_default():
    CURRENT_AGENT_KEY.set("decision")
    assert normalize_alert_source("   ") == "agent:decision"
    CURRENT_AGENT_KEY.set(None)
    assert normalize_alert_source("") == "agent"


def test_contextvar_reset_restores_previous_value():
    """队长 base.py 里 set/reset 的写法要真的能还原，不能把身份泄漏给下一次调用。"""
    token = CURRENT_AGENT_KEY.set("executor")
    assert current_agent_key() == "executor"
    CURRENT_AGENT_KEY.reset(token)
    assert current_agent_key() is None


def test_contextvar_does_not_leak_across_threads():
    """线程池（run_in_executor）不自动继承 ContextVar——这是队长接线时的已知边界。

    本用例把这个行为钉成文档：如果将来 _execute_tool 改成丢线程池执行，
    source 会静默退化成 "agent"，需要显式 copy_context().run(...)。
    工具调用当前跑在 asyncio task 里，同 task 内的 set 可见，没问题。
    """
    CURRENT_AGENT_KEY.set("scout")
    seen: list[str | None] = []

    def read_in_thread() -> None:
        seen.append(current_agent_key())

    t = threading.Thread(target=read_in_thread)
    t.start()
    t.join()
    assert seen == [None]


# --------------------------------------------------------------- 落库口径
def test_raise_alert_passes_normalized_source(monkeypatch):
    """端到端：确认真正的 source 值进了 queries.push_alert，而不只是纯函数对。"""
    captured: dict[str, str] = {}

    def fake_push_alert(db, level, source, message):
        captured.update(level=level, source=source, message=message)
        return {"id": 1, "level": level, "source": source, "message": message}

    import contextlib

    monkeypatch.setattr(tool_impl, "push_alert", fake_push_alert)
    monkeypatch.setattr(tool_impl, "session_scope", lambda: contextlib.nullcontext(None))

    CURRENT_AGENT_KEY.set("decision")
    out = tool_impl.raise_alert("warning", "土壤湿度低于目标区间")
    assert out["source"] == "agent:decision"

    out = tool_impl.raise_alert("critical", "验证不通过", source="agent:verifier")
    assert out["source"] == "agent:verifier"

    CURRENT_AGENT_KEY.set(None)
    out = tool_impl.raise_alert("info", "手动巡检")
    assert out["source"] == "agent"
