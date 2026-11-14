"""接缝 search：命中排序、引用字段齐全、空查询与 top_k 边界。"""
from __future__ import annotations

from app.knowledge import loader, retriever

SOIL = (
    "茶园土壤湿度低于 55% 时应及时灌溉。沙壤土田间持水量低，取下限；黏土取上限 65%。\n"
    "灌溉后 30 分钟复测，达成率低于 80% 需补灌 10 至 15 秒。\n"
)
PEST = (
    "茶小绿叶蝉防治：虫口密度超过每百叶 10 头时，优先悬挂黄色粘虫板，"
    "必要时选用印楝素等生物农药，采前 7 天停止用药。\n"
)
WEATHER = "霜冻预警：当预报最低气温低于 4℃ 时，提前启动防霜风机并覆盖遮阳网。\n"


def _seed(tmp_path):
    (tmp_path / "soil.txt").write_text(SOIL, encoding="utf-8")
    (tmp_path / "pest.txt").write_text(PEST, encoding="utf-8")
    (tmp_path / "weather.txt").write_text(WEATHER, encoding="utf-8")
    loader.ingest(str(tmp_path / "soil.txt"), doc_id=1)
    loader.ingest(str(tmp_path / "pest.txt"), doc_id=2)
    loader.ingest(str(tmp_path / "weather.txt"), doc_id=3)


def test_search_returns_citation_fields(tmp_path):
    _seed(tmp_path)
    hits = retriever.search("土壤湿度低了要不要浇水", top_k=3)
    assert hits, "知识库有内容却检索不到"
    top = hits[0]
    assert set(top) >= {"title", "chunk_text", "score", "doc_id"}
    assert top["doc_id"] == 1
    assert top["score"] > 0


def test_search_ranks_right_document(tmp_path):
    _seed(tmp_path)
    pest_hits = retriever.search("茶小绿叶蝉怎么防治", top_k=3)
    assert pest_hits[0]["doc_id"] == 2

    cold_hits = retriever.search("明天有霜冻风险怎么处理", top_k=3)
    assert cold_hits[0]["doc_id"] == 3


def test_search_scores_are_descending(tmp_path):
    _seed(tmp_path)
    scores = [h["score"] for h in retriever.search("灌溉 复测 达成率", top_k=3)]
    assert scores == sorted(scores, reverse=True)


def test_empty_question_returns_empty(tmp_path):
    _seed(tmp_path)
    assert retriever.search("   ", top_k=3) == []


def test_top_k_is_clamped(tmp_path):
    _seed(tmp_path)
    assert len(retriever.search("灌溉", top_k=100)) <= 20
    assert len(retriever.search("灌溉", top_k=0)) == 1
    # 非法值回默认 3：与显式传 3 结果一致，且不抛异常
    assert retriever.search("灌溉", top_k="bad") == retriever.search("灌溉", top_k=3)


def test_empty_knowledge_base_returns_empty(tmp_path):
    assert retriever.search("灌溉") == []
    assert retriever.stats()["chunks"] == 0


def test_off_topic_question_returns_nothing(tmp_path):
    # 宁可检索不到，也不拿沾边段落硬答（PRD 8.2 植保员硬规则）
    _seed(tmp_path)
    assert retriever.search("今年茶叶出口关税是多少", top_k=3) == []
