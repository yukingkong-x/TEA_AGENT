"""向量化：确定性、单位化、中文 bigram 的区分度。"""
from __future__ import annotations

import math

from app.knowledge import embed as E


def test_same_text_same_vector():
    # 断点：换用随机初始化/带时间戳的向量化会让回归测试失效
    assert E.embed("土壤湿度低于 55% 应灌溉") == E.embed("土壤湿度低于 55% 应灌溉")


def test_vector_is_unit_length():
    vec = E.embed("茶园霜冻预警：气温低于 4℃ 时启动防霜风机")
    assert vec, "非空文本不应产生空向量"
    assert all(0 <= idx < E.DIM for idx in vec)
    assert math.isclose(math.sqrt(sum(v * v for v in vec.values())), 1.0, rel_tol=1e-9)


def test_empty_text_is_zero_vector():
    assert E.embed("") == {}
    assert E.cosine({}, E.embed("灌溉")) == 0.0


def test_dense_export_keeps_weights():
    vec = E.embed("土壤湿度")
    dense = E.to_dense(vec, 4096)
    assert len(dense) == 4096
    for index, value in vec.items():
        if index < 4096:
            assert dense[index] == value


def test_related_topic_scores_higher_than_unrelated():
    query = E.embed("土壤湿度多少需要浇水")
    related = E.embed("土壤水分不足时应及时灌溉补水")
    unrelated = E.embed("茶叶采摘后需摊放萎凋，避免高温闷堆")
    assert E.cosine(query, related) > E.cosine(query, unrelated)
    assert E.cosine(query, unrelated) < 0.2


def test_ascii_words_and_numbers_are_tokens():
    tokens = dict(E.tokenize("pH 5.5 偏酸，需施石灰"))
    assert "w:ph" in tokens
    assert "w:5.5" in tokens


def test_punctuation_does_not_break_bigram():
    # 标点转空格后仍应命中“灌溉”这个词的 bigram
    a = dict(E.tokenize("需要灌溉。"))
    b = dict(E.tokenize("需要灌溉"))
    assert "b:灌溉" in a and "b:灌溉" in b


def test_cosine_guards_empty_and_disjoint():
    assert E.cosine({}, {1: 1.0}) == 0.0
    assert E.cosine({1: 1.0}, {}) == 0.0
    assert E.cosine({1: 1.0}, {2: 1.0}) == 0.0        # 无共享维 → 0，不抛错
