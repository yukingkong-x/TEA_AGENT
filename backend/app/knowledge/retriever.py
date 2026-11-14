"""接缝：search(question, top_k) -> [{title, chunk_text, score, doc_id}]（REQ-F-020）。

被三处调用：
- `api/knowledge.py` 的检索测试（top_k 由前端传）；
- `core/tool_impl.query_knowledge`（植保员工具，top_k=4）；
- 后续 orchestration 里的“带引用回答”（PRD 13.x 的 [1][2] 编号）。

分数语义：稀疏余弦相似度，范围 [-1, 1]，越大越相关。实测同一主题约 0.07~0.25、
无关主题 0.00~0.02，因此设 0.03 的噪声地板——低于它的命中直接丢掉，让植保员
如实说“知识库中未检索到相关内容”，而不是拿一段沾边的文字硬答（PRD 8.2 的硬要求）。
不归一化到 0-100：前端拿 0.23 直接显示、要百分比自己乘，免得两边各转一次转出偏差。
"""
from __future__ import annotations

import logging

from app.knowledge import embed as embed_mod
from app.knowledge.store import get_storage

logger = logging.getLogger(__name__)

# 噪声地板：稀疏哈希向量的随机重合在 0.02 以下，0.03 以上才算真命中
MIN_SCORE = 0.03
MAX_TOP_K = 20


def search(question: str, top_k: int = 3) -> list[dict]:
    query = (question or "").strip()
    if not query:
        return []
    try:
        k = int(top_k)
    except (TypeError, ValueError):
        k = 3
    k = max(1, min(k, MAX_TOP_K))

    vector = embed_mod.embed(query)
    hits = get_storage().query(vector, k)
    out = [
        {
            "title": hit.title,
            "chunk_text": hit.chunk_text,
            "score": round(hit.score, 4),
            "doc_id": hit.doc_id,
            "chunk_index": hit.chunk_index,
        }
        for hit in hits
        if hit.score > MIN_SCORE
    ]
    logger.debug("知识检索：%r → %s 命中（top_k=%s）", query[:30], len(out), k)
    return out


def stats() -> dict:
    """给 /api/health 或设置页显示“知识库后端/切片数”。"""
    return get_storage().stats()
