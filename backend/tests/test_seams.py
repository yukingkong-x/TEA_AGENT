"""跨地盘接缝（app/seams.py）的纯逻辑单测：不连库、不起服务。"""
from __future__ import annotations

import sys
import types

import pytest

from app import seams


def _fake_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


@pytest.fixture(autouse=True)
def _clean_sys_modules():
    """每个用例结束后清掉伪造模块，避免污染其他用例。"""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.startswith("app.workflow") or name.startswith("app.verification") or name.startswith("app.knowledge"):
            sys.modules.pop(name, None)


def test_not_ready_is_503_kind_error(monkeypatch):
    """「对面还没落地」这条路径必须显式构造，不能靠「本分支恰好没有那个模块」。

    两支合并后模块就在，靠环境缺席的用例会突然变红，然后被人「修」成 skip——
    降级逻辑反而没人守了。这里直接把候选指到一个不存在的模块。
    """
    seam = "search"
    monkeypatch.setitem(seams._CANDIDATES, seam, (("app.__absent_kb__.retriever", "search"),))
    with pytest.raises(seams.SeamNotReady) as ei:
        seams.search("土壤湿度趋势", 3)
    assert ei.value.seam == seam
    assert "尚未就绪" in ei.value.detail
    assert "search(question" in ei.value.detail  # 把约定签名写进错误里，队长照着接


def test_status_never_raises_and_marks_all_six():
    st = seams.status(refresh=True)
    assert set(st) == {"start_run", "validate_dag", "verify_task", "generate_report", "ingest", "search"}
    assert all(v == "ready" or "尚未就绪" in v or "未找到" in v for v in st.values())


def test_status_cached_between_calls():
    seams.status(refresh=True)
    ts, _ = seams._status_cache
    seams.status()
    assert seams._status_cache[0] == ts  # 没刷新就复用缓存


def test_invoke_prefers_keywords():
    seen = {}

    def fn(wf_id: int, trigger: str = "manual"):
        seen.update({"wf_id": wf_id, "trigger": trigger})
        return {"run_id": 7}

    assert seams._invoke(fn, (3, "cron"), {"wf_id": 3, "trigger": "cron"}) == {"run_id": 7}
    assert seen == {"wf_id": 3, "trigger": "cron"}


def test_invoke_falls_back_to_positional_without_double_call():
    """对面参数名不叫 wf_id 时，不能调两次 —— 否则会建两条 run。"""
    calls = []

    def fn(a: int, b: str = "manual"):  # 名字完全不同
        calls.append((a, b))
        return {"run_id": len(calls)}

    result = seams._invoke(fn, (5, "manual"), {"wf_id": 5, "trigger": "manual"})
    assert len(calls) == 1
    assert result == {"run_id": 1}


def test_start_run_adapts_to_captain_signature():
    _fake_module("app.workflow.service", start_run=lambda wf_id, trigger: {"run_id": 11})
    seams._status_cache = (0.0, {})
    assert seams.start_run(1, "manual") == {"run_id": 11}


def test_generate_report_accepts_plain_int():
    _fake_module("app.verification.report", generate_report=lambda run_id: 42)
    seams._status_cache = (0.0, {})
    assert seams.generate_report(3) == 42


def test_validate_dag_returns_none_when_absent(monkeypatch):
    """没有引擎校验时返回 None，让调用方用自己的闸门（不能返回 []，否则等于放行一切）。"""
    monkeypatch.setitem(seams._CANDIDATES, "validate_dag", (("app.__absent_wf__.engine", "validate_dag"),))
    assert seams.validate_dag({"nodes": []}) is None


def test_validate_dag_degrades_when_engine_raises(monkeypatch):
    """引擎校验器自己崩了也要回退到 None——画布保存不能因为对面一个异常就 500。"""

    def boom(_dag):
        raise RuntimeError("引擎校验炸了")

    _fake_module("app.workflow.engine", validate_dag=boom)
    monkeypatch.setitem(seams._CANDIDATES, "validate_dag", (("app.workflow.engine", "validate_dag"),))
    assert seams.validate_dag({"nodes": []}) is None
