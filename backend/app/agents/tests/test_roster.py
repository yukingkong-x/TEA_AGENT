"""平台事实注入:设备清单进 system prompt。

为什么要有这一层(2026-11-14 真模型 run #8 实测):
    scout → get_env_status({"device_id": "A区茶垄"}) → 「设备 A区茶垄 不存在」
    soil / pest 同错 → 三方都说「设备信息缺失」→ decision 判 none → 零任务。
工具是对的,LLM 只是不知道 id 长什么样;把清单摆到它眼前就不必猜。
"""
from __future__ import annotations

import asyncio

import pytest

from app.agents import roster
from app.agents.context import CURRENT_CONTEXT_NOTE, current_context_note, set_context_note

SIX = [
    ("k10-field-01", "巡园员一号", "field", "A 区茶园", False),
    ("esp32-soil-02", "墒情二号", "soil", "A 区茶垄", False),
    ("k10-act-03", "执行终端", "actuator", "A 区泵房", False),
    ("mock-k10-field-01", "模拟巡园", "field", "A 区茶园", True),
    ("mock-esp32-soil-02", "模拟墒情", "soil", "A 区茶垄", True),
    ("mock-k10-act-03", "模拟执行", "actuator", "A 区泵房", True),
]


def test_format_lists_ids_roles_and_warns_against_location_names():
    text = roster.format_roster(SIX, mode="mock")

    assert "mock-esp32-soil-02" in text and "土壤探头" in text
    assert "mock-k10-act-03" in text and "执行终端" in text
    assert "不要填「A区茶垄」" in text
    assert "当前模式：mock" in text


def test_format_marks_offline_and_missing_location():
    text = roster.format_roster([("d-1", "某设备", "soil", None, False)])

    assert "离线" in text and "未知位置" in text


def test_format_empty_rows_returns_empty_string():
    assert roster.format_roster([]) == ""


def test_roster_text_is_empty_without_base_or_table(monkeypatch):
    """没有基座（models / devices 表）时必须静默返回空串,不能让 run 起不来。

    合并后的仓库里表是真的,所以这里显式把取数打瘸,模拟「本分支无基座」;
    直接断言 == "" 在联调环境里会因为真读到 6 台设备而误报。
    """
    roster.reset_cache()
    monkeypatch.setattr(roster, "CACHE_TTL_S", 0.0)

    def _boom():
        raise ModuleNotFoundError("No module named 'app.models.devices'")

    monkeypatch.setattr(roster, "_query_rows", _boom)

    assert roster.device_roster_text(force=True) == ""


def test_roster_text_survives_empty_table(monkeypatch):
    """表在但一条设备都没有:也是空串,不是半截标题。"""
    roster.reset_cache()
    monkeypatch.setattr(roster, "CACHE_TTL_S", 0.0)
    monkeypatch.setattr(roster, "_query_rows", lambda: [])

    assert roster.device_roster_text(force=True) == ""


def test_context_note_reaches_system_prompt():
    from app.agents.base import AgentRunner

    class _Spec:
        system_prompt = "你是土壤师"
        temperature = 0.2

    runner = AgentRunner(agent_key="soil", llm=None, registry=None, spec=_Spec())
    token = set_context_note("【设备事实】mock-esp32-soil-02｜土壤探头")
    try:
        messages = runner._build_messages("看墒情", [], [])
    finally:
        CURRENT_CONTEXT_NOTE.reset(token)

    assert messages[0]["role"] == "system"
    assert "你是土壤师" in messages[0]["content"]
    assert "mock-esp32-soil-02" in messages[0]["content"]

    # 没有事实时 system 保持原样,不能多出空段
    plain = runner._build_messages("看墒情", [], [])
    assert plain[0]["content"] == "你是土壤师"


def test_runner_proxy_sets_and_resets_note_around_run():
    """代理必须在 run 期间让 Agent 看到设备清单,结束后把 ContextVar 还原。"""
    from app.workflow.wiring import _RunnerProxy

    seen: dict[str, str] = {}

    class _Runner:
        async def run(self, task, history=None, upstream=None):
            seen["note"] = current_context_note()
            return "ok"

    proxy = _RunnerProxy(_Runner())
    token = set_context_note("外层事实")
    try:
        out = asyncio.run(proxy.run("task"))
        assert out == "ok"
        assert seen["note"] != "外层事实"          # 代理注入的清单覆盖了外层
        assert current_context_note() == "外层事实"  # 跑完还原
    finally:
        CURRENT_CONTEXT_NOTE.reset(token)


@pytest.mark.parametrize("rows,expect", [
    ([], ""),
    ([("x", "n", "soil", "A 区", True)], "x"),
])
def test_text_presence_follows_rows(rows, expect):
    text = roster.format_roster(rows)
    assert (expect in text) if expect else (text == "")
