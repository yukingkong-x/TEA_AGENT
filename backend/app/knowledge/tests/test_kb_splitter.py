"""切片：块长上限、重叠、尾巴并块、非法参数。"""
from __future__ import annotations

import pytest

from app.knowledge.splitter import SplitError, paragraphs, split_text


def test_empty_returns_empty_list():
    assert split_text("") == []
    assert split_text("   \n\n  ") == []


def test_short_text_single_chunk():
    chunks = split_text("土壤湿度低于 55% 时应灌溉，沙壤土取下限。")
    assert len(chunks) == 1
    assert chunks[0].startswith("土壤湿度")


def test_hard_limit_is_respected():
    text = "。".join(f"第{i}条：茶园土壤管理要点说明" for i in range(80)) + "。"
    chunks = split_text(text, max_chars=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_overlap_carries_tail_into_next_chunk():
    text = "。".join(f"第{i}条：茶园土壤管理要点，湿度低于五十五应灌溉" for i in range(40)) + "。"
    chunks = split_text(text, max_chars=200, overlap=60)
    assert len(chunks) >= 2
    tail = chunks[0][-60:]
    assert chunks[1].startswith(tail)


def test_overlap_never_breaks_max_chars():
    # 断点：把 tail + piece 直接拼起来而不检查长度，会产出超长块
    text = "。".join("长" * 30 for _ in range(50)) + "。"
    chunks = split_text(text, max_chars=120, overlap=100)
    assert all(len(c) <= 120 for c in chunks)


def test_paragraph_soft_newlines_are_merged():
    text = "第一行说明\n第二行接着\n\n新段落"
    assert paragraphs(text) == ["第一行说明 第二行接着", "新段落"]


def test_tail_fragment_merges_into_previous_chunk():
    body = "。".join(f"条款{i}：灌溉与排水要求" for i in range(30)) + "。"
    text = f"{body}\n\n附则"
    chunks = split_text(text, max_chars=200, overlap=20)
    assert chunks[-1].endswith("附则")
    assert len(chunks[-1]) > len("附则")


def test_invalid_params_raise():
    with pytest.raises(SplitError):
        split_text("abc", max_chars=10)
    with pytest.raises(SplitError):
        split_text("abc", max_chars=200, overlap=200)
