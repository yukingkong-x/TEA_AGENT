"""接缝：ingest(path, doc_id) -> {"chunk_count", "chroma_ids", ...}（REQ-F-020）。

调用方是基座 `api/knowledge.py` 的后台线程，它把 `chunk_count` 与 `chroma_ids`
写回 knowledge_docs 表。所以这里失败必须抛异常——让它把 doc 标成 failed，
而不是返回 0 切片假装成功。
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.knowledge import embed as embed_mod
from app.knowledge.extract import ExtractionError, extract_text
from app.knowledge.splitter import split_text
from app.knowledge.store import Record, get_storage

logger = logging.getLogger(__name__)

__all__ = ["ingest", "delete", "chunk_id_for"]


def chunk_id_for(doc_id: int, index: int) -> str:
    """切片 id 规则固定，重传同一文档可原地覆盖，不会产生重复向量。"""
    return f"doc{doc_id}-{index}"


def ingest(path: str, doc_id: int) -> dict:
    """抽正文 → 切片 → 向量化 → 入库（幂等：先清旧块）。"""
    file = Path(path)
    text = extract_text(file)          # 抽不出正文直接抛，由调用方标 failed
    chunks = split_text(text)
    if not chunks:
        raise ExtractionError(f"{file.name} 切片结果为空（正文 {len(text)} 字）")

    title = file.name
    records = [
        Record(
            id=chunk_id_for(doc_id, index),
            doc_id=int(doc_id),
            title=title,
            chunk_text=chunk,
            chunk_index=index,
            vector=embed_mod.embed(chunk),
        )
        for index, chunk in enumerate(chunks)
    ]

    storage = get_storage()
    storage.delete_doc(int(doc_id))    # 重传覆盖：先删旧块
    storage.add(records)

    logger.info(
        "知识入库：doc_id=%s《%s》%s 字 → %s 块，backend=%s",
        doc_id, title, len(text), len(records), storage.backend,
    )
    return {
        "doc_id": int(doc_id),
        "title": title,
        "chunk_count": len(records),
        "chroma_ids": [r.id for r in records],
        "chars": len(text),
        "backend": storage.backend,
    }


def delete(doc_id: int) -> dict:
    """删除某文档的全部向量（基座删除文档记录时应一并调用）。"""
    removed = get_storage().delete_doc(int(doc_id))
    return {"doc_id": int(doc_id), "removed": removed}
