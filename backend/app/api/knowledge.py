"""知识库（PRD 7.4）：上传 → 切片入库 → 检索测试 → 文档列表。

切片与检索本体在队长的 knowledge/（Chroma）；这里负责 HTTP 层、文件落盘与文档状态记录。
文件存 UPLOAD_DIR（docker 下是具名卷 uploads），不进代码目录。
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import seams
from ..config import get_settings
from ..db import get_db, session_scope
from ..models.knowledge_docs import KnowledgeDoc
from ._common import ensure_found

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
settings = get_settings()

ALLOWED_SUFFIX = {".txt", ".md", ".pdf"}


class SearchIn(BaseModel):
    question: str
    top_k: int = Field(3, ge=1, le=20)


def _doc_dict(doc: KnowledgeDoc) -> dict[str, Any]:
    return {
        "id": doc.id,
        "title": doc.title,
        "source": doc.source,
        "chunk_count": doc.chunk_count,
        "status": doc.status,
        "created_at": doc.created_at.isoformat(sep=" ", timespec="seconds") if doc.created_at else None,
    }


def _ingest_worker(doc_id: int, path: str) -> None:
    """后台线程跑切片入库，避免阻塞上传请求。"""
    try:
        result = seams.ingest(path=path, doc_id=doc_id)
        chunk_count = int(result.get("chunk_count", 0)) if isinstance(result, dict) else 0
        with session_scope() as db:
            doc = db.get(KnowledgeDoc, doc_id)
            if doc is not None:
                doc.status = "ready"
                doc.chunk_count = chunk_count
                doc.chroma_ids_json = result.get("chroma_ids") if isinstance(result, dict) else None
    except Exception as exc:
        logger.exception("知识库入库失败 doc_id={}：{}", doc_id, exc)
        with session_scope() as db:
            doc = db.get(KnowledgeDoc, doc_id)
            if doc is not None:
                doc.status = "failed"


@router.post("/upload", summary="上传文档（txt/md/pdf）→ 异步切片入库")
def upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(status_code=400, detail=f"只支持 {sorted(ALLOWED_SUFFIX)}，收到 {suffix or '未知'}")

    # 没有 loader 就直接 503，避免把文档写进库却永远 processing
    seams.ensure("ingest")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    stored = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(file.file.read())

    doc = KnowledgeDoc(
        title=file.filename or stored.name,
        source=str(stored),
        chunk_count=0,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    threading.Thread(target=_ingest_worker, args=(doc.id, str(stored)), daemon=True).start()
    logger.info("知识库上传：{}（{} 字节）→ doc_id={}", doc.title, stored.stat().st_size, doc.id)
    return _doc_dict(doc)


@router.post("/search", summary="检索测试（返回带引用的片段）")
def search(body: SearchIn) -> dict[str, Any]:
    hits = seams.search(question=body.question, top_k=body.top_k)
    return {"question": body.question, "top_k": body.top_k, "hits": hits}


@router.get("", summary="文档列表与状态")
def list_docs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(KnowledgeDoc).order_by(KnowledgeDoc.id.desc())).all()
    return [_doc_dict(r) for r in rows]


@router.delete("/{doc_id}", summary="删除文档记录并清理向量索引")
def delete_doc(doc_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    doc = db.get(KnowledgeDoc, doc_id)
    ensure_found(doc, f"文档 {doc_id}")

    # 先清向量、再删记录：反过来的话中途失败会留下「记录没了、向量还在」的孤儿，
    # 检索仍会命中一份打不开的文档，而且再也没有接口能清掉它。
    # 向量清理失败不阻断删除（记录是用户明确要删的），但要在返回值和日志里留痕。
    vectors: int | str = 0
    try:
        from ..knowledge.loader import delete as delete_vectors

        vectors = int(delete_vectors(doc_id).get("removed", 0) or 0)
    except Exception as exc:  # noqa: BLE001 知识库模块缺失/索引不可用时降级
        logger.warning("文档 {} 的向量清理失败（记录仍会删除，索引可能残留）：{}", doc_id, exc)
        vectors = "failed"

    db.delete(doc)
    db.commit()
    return {"deleted": doc_id, "vectors_removed": vectors}
