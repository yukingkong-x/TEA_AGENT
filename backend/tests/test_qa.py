"""通用问答（/api/qa/ask）的用例。

重点是三条「不能崩」的底线：
1. 知识库没就绪 → 仍然回答（用通用知识），只是标记 degraded，不能 500；
2. 模型没 key / 被限流 → 返回命中资料 + 一句说明，不能白屏；
3. 提示词里资料编号必须和 citations 的 index 对得上，否则页面上的 [1] 指不到东西。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import seams  # noqa: E402
from app.qa import answering  # noqa: E402


HITS = [
    {"title": "茶园灌溉决策与土壤水分", "chunk_text": "土壤湿度低于 70% 时应及时灌溉。", "score": 0.91, "doc_id": 3},
    {"title": "茶园主要病害诊断与防治", "chunk_text": "土壤含水率高于 80% 时继续灌溉会造成根系缺氧。", "score": 0.83, "doc_id": 4},
]


class _FakeLLM:
    """只关心两件事：给了什么 messages、返回什么。"""

    def __init__(self, content: str | None = "结论：该浇了。", degraded: bool = False, error: str | None = None, boom: bool = False):
        self.content = content
        self._degraded = degraded
        self._error = error
        self._boom = boom
        self.calls: list[list[dict]] = []

    async def complete(self, messages, **_kwargs):
        self.calls.append(messages)
        if self._boom:
            raise TimeoutError("模型超时")
        return SimpleNamespace(content=self.content, degraded=self._degraded, error=self._error, provider="glm")


def _patch_search(monkeypatch, hits):
    monkeypatch.setattr(seams, "search", lambda question, top_k=5: hits)


def _patch_search_fail(monkeypatch):
    def boom(question, top_k=5):
        raise RuntimeError("Chroma 连不上")

    monkeypatch.setattr(seams, "search", boom)


def test_citations_numbering_matches_prompt(monkeypatch):
    """资料编号和引用 index 必须一致 —— 页面上点 [2] 要能指到第二条。"""
    _patch_search(monkeypatch, HITS)
    llm = _FakeLLM()
    out = asyncio.run(answering.answer("今天该浇水吗？", top_k=2, llm=llm))

    assert [c["index"] for c in out["citations"]] == [1, 2]
    assert out["citations"][0]["title"] == "茶园灌溉决策与土壤水分"
    assert out["retrieved"] == 2

    prompt = llm.calls[0][-1]["content"]
    assert "[1]《茶园灌溉决策与土壤水分》" in prompt
    assert "[2]《茶园主要病害诊断与防治》" in prompt
    assert out["question"] in prompt


def test_answer_passes_through_when_model_ok(monkeypatch):
    _patch_search(monkeypatch, HITS)
    out = asyncio.run(answering.answer("土壤湿度 45% 要不要浇水？", llm=_FakeLLM()))

    assert out["answer"] == "结论：该浇了。"
    assert out["degraded"] is False
    assert out["provider"] == "glm"
    assert out["reason"] is None


def test_knowledge_base_down_still_answers(monkeypatch):
    """知识库挂了不是错误：用通用知识答，reason 里说清原因。"""
    _patch_search_fail(monkeypatch)
    out = asyncio.run(answering.answer("茶树叶子上有白点是什么病？", llm=_FakeLLM("可能是茶饼病。")))

    assert out["answer"] == "可能是茶饼病。"
    assert out["degraded"] is False
    assert out["retrieved"] == 0
    assert "知识库检索不可用" in out["reason"]


def test_model_degraded_returns_hits_instead_of_blank(monkeypatch):
    """模型降级时必须给用户看到东西，不能 answer=None + 空引用。"""
    _patch_search(monkeypatch, HITS)
    out = asyncio.run(answering.answer("什么时候施肥？", llm=_FakeLLM(degraded=True, error="未配置 Key")))

    assert out["degraded"] is True
    assert out["answer"] == answering.DEGRADED_ANSWER
    assert len(out["citations"]) == 2
    assert out["reason"] == "未配置 Key"


def test_model_exception_is_swallowed(monkeypatch):
    """模型超时/网络异常不能冒到 HTTP 层变成 500。"""
    _patch_search(monkeypatch, HITS)
    out = asyncio.run(answering.answer("要不要遮阳？", llm=_FakeLLM(boom=True)))

    assert out["degraded"] is True
    assert "TimeoutError" in out["reason"]
    assert out["answer"] == answering.DEGRADED_ANSWER


def test_both_sides_down_still_returns_sentence(monkeypatch):
    _patch_search_fail(monkeypatch)
    out = asyncio.run(answering.answer("今天天气怎么样？", llm=_FakeLLM(degraded=True)))

    assert out["degraded"] is True
    assert out["citations"] == []
    assert out["answer"]  # 一句人话，不是空串


def test_blank_question_short_circuits(monkeypatch):
    """空格/换行不算问题，且不该去打模型（花钱）。"""
    llm = _FakeLLM()
    out = asyncio.run(answering.answer("   \n  ", llm=llm))

    assert out["degraded"] is True
    assert out["answer"] is None
    assert out["reason"] == "问题为空"
    assert llm.calls == []


def test_question_is_collapsed_and_trimmed(monkeypatch):
    """多行输入压成一行：提示词里换行会让模型把后半句当新指令。"""
    _patch_search(monkeypatch, HITS)
    out = asyncio.run(answering.answer("  今天\n该浇水吗？  ", llm=_FakeLLM()))

    assert out["question"] == "今天 该浇水吗？"


def test_snippet_truncated_for_ui(monkeypatch):
    """超长片段要截断，否则整段文档糊在引用卡里。"""
    long_hit = [{"title": "长文", "chunk_text": "茶" * 400, "score": 0.5, "doc_id": 1}]
    _patch_search(monkeypatch, long_hit)
    out = asyncio.run(answering.answer("茶叶怎么采？", llm=_FakeLLM()))

    snippet = out["citations"][0]["snippet"]
    assert len(snippet) == 161  # 160 + 省略号
    assert snippet.endswith("…")


# ── 数值护栏：实测 glm-4-flash 会把 45% 判成「高于 70%」 ──────────────────
BAD_ANSWER = "今天不需要浇水。资料[2]提到阈值是土壤含水率低于70%，实测45%高于阈值70%，因此不需要浇水。"


def test_guard_replaces_wrong_numeric_decision(monkeypatch):
    """模型越界拍板时，答案必须被换成确定性的「只报事实 + 走流程」。"""
    _patch_search(monkeypatch, HITS)
    out = asyncio.run(answering.answer("土壤湿度45%，今天该浇水吗？", llm=_FakeLLM(BAD_ANSWER)))

    assert out["guarded"] is True
    assert "高于阈值" not in out["answer"]      # 错误结论被抹掉
    assert "不需要浇水" not in out["answer"]
    assert "45%" in out["answer"]               # 用户给的值照原样回显
    assert "低于 70%" in out["answer"]          # 阈值从资料原文抠出来，不是模型写的
    assert "开始巡园" in out["answer"]          # 有下一步动作，不是一句「我不答」


def test_guard_leaves_knowledge_question_alone(monkeypatch):
    """知识型问答不受影响：没有数值就不该触发护栏。"""
    _patch_search(monkeypatch, HITS)
    out = asyncio.run(answering.answer("茶饼病怎么防治？", llm=_FakeLLM("摘除病叶，发病初期喷药。")))

    assert out["guarded"] is False
    assert out["answer"] == "摘除病叶，发病初期喷药。"


def test_guard_ignores_answer_without_decision(monkeypatch):
    """有数值但答案没下结论（只是转述阈值）→ 不替换。"""
    _patch_search(monkeypatch, HITS)
    text = "资料[1]的阈值是土壤湿度低于70%时灌溉。"
    out = asyncio.run(answering.answer("土壤湿度45%算低吗？", llm=_FakeLLM(text)))

    assert out["guarded"] is False
    assert out["answer"] == text


def test_guard_without_threshold_still_safe(monkeypatch):
    """没抠到阈值原句也要给出可用答复，不能拼出半截话。"""
    _patch_search(monkeypatch, [{"title": "无关资料", "chunk_text": "茶园风景很好。", "score": 0.2, "doc_id": 9}])
    out = asyncio.run(answering.answer("温度32度要不要遮阳？", llm=_FakeLLM("需要遮阳，否则会灼伤。")))

    assert out["guarded"] is True
    assert "32度" in out["answer"]
    assert "开始巡园" in out["answer"]
