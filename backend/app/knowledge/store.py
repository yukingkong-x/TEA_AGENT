"""向量存储：本地 JSON 为主，Chroma 为镜像。

**为什么本地是主、Chroma 是镜像**（而不是反过来）：
演示现场最怕的是「Chroma 容器没起 / 端口抢了 / 数据卷空的」，一旦 RAG 依赖它，
植保员就会集体说“未检索到”，评委会认为整个知识库是假的。本地 JSON 索引
零依赖、必定可用，保证检索这条链路永远有结果；Chroma 存在时双写并优先查它，
满足 PRD 19.5 的“Chroma 独立容器”要求。

**不做静默降级**：active_backend 会如实报告当前是 `chroma+local` 还是 `local`，
`/api/health` 与日志都能看到；Chroma 写失败会记 warning 而不是假装成功。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from app.knowledge import embed as embed_mod

logger = logging.getLogger(__name__)

COLLECTION = "tea_knowledge"
_TENANT = "default_tenant"
_DATABASE = "default_database"
_HTTP_TIMEOUT = 5.0


class StoreError(RuntimeError):
    pass


@dataclass
class Record:
    id: str
    doc_id: int
    title: str
    chunk_text: str
    chunk_index: int
    vector: dict[int, float]

    def to_json(self) -> dict:
        """向量存成 [[下标, 值]]：32768 维定长数组会让索引文件膨胀两个数量级。"""
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "title": self.title,
            "chunk_text": self.chunk_text,
            "chunk_index": self.chunk_index,
            "vector": embed_mod.to_pairs(self.vector),
        }

    @classmethod
    def from_json(cls, data: dict) -> "Record":
        return cls(
            id=str(data.get("id", "")),
            doc_id=int(data.get("doc_id", 0) or 0),
            title=str(data.get("title", "")),
            chunk_text=str(data.get("chunk_text", "")),
            chunk_index=int(data.get("chunk_index", 0) or 0),
            vector=embed_mod.from_pairs(data.get("vector")),
        )


@dataclass
class Hit:
    id: str
    doc_id: int
    title: str
    chunk_text: str
    chunk_index: int
    score: float


# ─────────────────────────── 本地 JSON ───────────────────────────

class LocalStore:
    """单文件 JSON 索引。规模在几千切片以内，读写全量即可，不必上 SQLite。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    # -- 读写 --
    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("本地知识索引损坏，按空库处理：%s（%s）", self.path, exc)
            return []
        records = data.get("records")
        return records if isinstance(records, list) else []

    def _save(self, records: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"version": 1, "dim": embed_mod.DIM, "records": records}
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)   # 原子替换：写一半断电不会留半截 JSON

    # -- 接口 --
    def add(self, records: Iterable[Record]) -> None:
        incoming = list(records)
        if not incoming:
            return
        with self._lock:
            existing = {r["id"]: r for r in self._load() if r.get("id")}
            for record in incoming:
                existing[record.id] = record.to_json()
            self._save(list(existing.values()))

    def delete_doc(self, doc_id: int) -> int:
        with self._lock:
            records = self._load()
            kept = [r for r in records if int(r.get("doc_id", 0) or 0) != doc_id]
            removed = len(records) - len(kept)
            if removed:
                self._save(kept)
            return removed

    def query(self, vector: dict[int, float], top_k: int) -> list[Hit]:
        if not vector:
            return []
        with self._lock:
            records = self._load()
        scored: list[Hit] = []
        for raw in records:
            record = Record.from_json(raw)
            scored.append(Hit(
                id=record.id,
                doc_id=record.doc_id,
                title=record.title,
                chunk_text=record.chunk_text,
                chunk_index=record.chunk_index,
                score=embed_mod.cosine(vector, record.vector),
            ))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]

    def stats(self) -> dict:
        records = self._load()
        return {
            "chunks": len(records),
            "docs": len({int(r.get("doc_id", 0) or 0) for r in records}),
        }

    def clear(self) -> None:
        with self._lock:
            self._save([])


# ─────────────────────────── Chroma HTTP ───────────────────────────

class ChromaStore:
    """Chroma 0.5.x REST（/api/v1）。用 httpx 直连，避免给镜像加 chromadb 依赖。"""

    def __init__(self, base_url: str, collection: str = COLLECTION):
        self.base_url = base_url.rstrip("/")
        self.collection = collection
        self._collection_id: Optional[str] = None
        self._lock = threading.Lock()

    # -- 基础 --
    def _client(self):
        import httpx

        return httpx.Client(base_url=self.base_url, timeout=_HTTP_TIMEOUT)

    def _params(self) -> dict:
        return {"tenant": _TENANT, "database": _DATABASE}

    def heartbeat(self) -> bool:
        try:
            with self._client() as client:
                resp = client.get("/api/v1/heartbeat")
                return resp.status_code == 200
        except Exception:  # noqa: BLE001 网络异常一律视为不可用
            return False

    def _cid(self) -> str:
        with self._lock:
            if self._collection_id:
                return self._collection_id
            payload = {
                "name": self.collection,
                "metadata": {"hnsw:space": "cosine"},
                "get_or_create": True,
            }
            with self._client() as client:
                resp = client.post("/api/v1/collections", params=self._params(), json=payload)
                if resp.status_code >= 400:
                    raise StoreError(f"创建 collection 失败 {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
            cid = data.get("id")
            if not cid:
                raise StoreError(f"Chroma 未返回 collection id: {data}")
            self._collection_id = cid
            return cid

    # -- 接口 --
    def add(self, records: Iterable[Record]) -> None:
        incoming = list(records)
        if not incoming:
            return
        cid = self._cid()
        body = {
            "ids": [r.id for r in incoming],
            "embeddings": [embed_mod.to_dense(r.vector) for r in incoming],
            "documents": [r.chunk_text for r in incoming],
            "metadatas": [
                {"doc_id": r.doc_id, "title": r.title, "chunk_index": r.chunk_index}
                for r in incoming
            ],
        }
        with self._client() as client:
            resp = client.post(f"/api/v1/collections/{cid}/add", json=body)
            if resp.status_code >= 400:
                raise StoreError(f"Chroma add 失败 {resp.status_code}: {resp.text[:200]}")

    def delete_doc(self, doc_id: int) -> int:
        cid = self._cid()
        with self._client() as client:
            resp = client.post(
                f"/api/v1/collections/{cid}/delete", json={"where": {"doc_id": doc_id}}
            )
            if resp.status_code >= 400:
                raise StoreError(f"Chroma delete 失败 {resp.status_code}: {resp.text[:200]}")
        return 0   # Chroma 不回条数，调用方以本地删除数为准

    def query(self, vector: dict[int, float], top_k: int) -> list[Hit]:
        if not vector:
            return []
        cid = self._cid()
        body = {
            "query_embeddings": [embed_mod.to_dense(vector)],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        with self._client() as client:
            resp = client.post(f"/api/v1/collections/{cid}/query", json=body)
            if resp.status_code >= 400:
                raise StoreError(f"Chroma query 失败 {resp.status_code}: {resp.text[:200]}")
            data = resp.json()

        ids = (data.get("ids") or [[]])[0]
        docs = (data.get("documents") or [[]])[0]
        metas = (data.get("metadatas") or [[]])[0]
        dists = (data.get("distances") or [[]])[0]
        hits: list[Hit] = []
        for i, chunk_id in enumerate(ids):
            meta = metas[i] if i < len(metas) and metas[i] else {}
            distance = dists[i] if i < len(dists) else 1.0
            hits.append(Hit(
                id=chunk_id,
                doc_id=int(meta.get("doc_id", 0)),
                title=str(meta.get("title", "")),
                chunk_text=docs[i] if i < len(docs) else "",
                chunk_index=int(meta.get("chunk_index", 0)),
                # cosine 空间下 distance = 1 - 相似度
                score=1.0 - float(distance),
            ))
        return hits

    def stats(self) -> dict:
        cid = self._cid()
        with self._client() as client:
            resp = client.get(f"/api/v1/collections/{cid}/count")
            if resp.status_code >= 400:
                raise StoreError(f"Chroma count 失败 {resp.status_code}")
            return {"chunks": int(resp.json()), "docs": -1}


# ─────────────────────────── 门面 ───────────────────────────

class Storage:
    """双写 + 合并查询。对外只暴露这一层。"""

    def __init__(self, local: LocalStore, chroma: Optional[ChromaStore] = None):
        self.local = local
        self.chroma = chroma
        self._warned = False

    @property
    def backend(self) -> str:
        return "chroma+local" if self.chroma else "local"

    def add(self, records: list[Record]) -> None:
        self.local.add(records)          # 先写兜底，再写镜像
        if not self.chroma:
            return
        try:
            self.chroma.add(records)
        except Exception as exc:  # noqa: BLE001 镜像失败不能拖垮入库
            if not self._warned:
                logger.warning("Chroma 写入失败，本次仅落本地索引：%s: %s", type(exc).__name__, exc)
                self._warned = True

    def delete_doc(self, doc_id: int) -> int:
        removed = self.local.delete_doc(doc_id)
        if self.chroma:
            try:
                self.chroma.delete_doc(doc_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Chroma 删除失败（本地已删）：%s: %s", type(exc).__name__, exc)
        return removed

    def query(self, vector: dict[int, float], top_k: int) -> list[Hit]:
        hits: dict[str, Hit] = {}
        if self.chroma:
            try:
                for hit in self.chroma.query(vector, top_k):
                    hits[hit.id] = hit
            except Exception as exc:  # noqa: BLE001 查询期镜像掉线 → 退回本地
                logger.warning("Chroma 查询失败，改用本地索引：%s: %s", type(exc).__name__, exc)
        for hit in self.local.query(vector, top_k):
            hits.setdefault(hit.id, hit)   # 同 id 以镜像分数为准（两者向量一致）
        merged = sorted(hits.values(), key=lambda h: h.score, reverse=True)
        return merged[:top_k]

    def stats(self) -> dict:
        info = {"backend": self.backend, **self.local.stats()}
        if self.chroma:
            try:
                info["chroma_chunks"] = self.chroma.stats()["chunks"]
            except Exception as exc:  # noqa: BLE001
                info["chroma_chunks"] = -1
                info["chroma_error"] = f"{type(exc).__name__}: {exc}"
        return info

    def clear(self) -> None:
        self.local.clear()


# ─────────────────────────── 单例 ───────────────────────────

_storage: Optional[Storage] = None
_lock = threading.Lock()


def store_dir() -> Path:
    env = os.getenv("KNOWLEDGE_STORE_DIR")
    if env:
        return Path(env)
    # app/knowledge/store.py → parents[2] 是 backend/
    return Path(__file__).resolve().parents[2] / "data" / "knowledge"


def _chroma_url() -> Optional[str]:
    """优先读基座 config（.env 生效），读不到再退回环境变量；off 即禁用镜像。"""
    mode = os.getenv("KNOWLEDGE_CHROMA", "").strip().lower()
    if mode in {"off", "0", "false", "disabled"}:
        return None
    if mode in {"on", "1", "true"}:
        url = os.getenv("CHROMA_URL")
        if url:
            return url
    try:
        from app.config import get_settings

        return get_settings().chroma_url
    except Exception:  # noqa: BLE001 单测/独立运行时不依赖基座配置
        host = os.getenv("CHROMA_HOST", "127.0.0.1")
        port = os.getenv("CHROMA_PORT", "8100")
        return f"http://{host}:{port}"


def get_storage() -> Storage:
    global _storage
    if _storage is not None:
        return _storage
    with _lock:
        if _storage is not None:
            return _storage
        local = LocalStore(store_dir() / "vectors.json")
        chroma: Optional[ChromaStore] = None
        url = _chroma_url()
        if url:
            candidate = ChromaStore(url)
            if candidate.heartbeat():
                chroma = candidate
                logger.info("知识库：Chroma 可用（%s），本地索引同时启用", url)
            else:
                logger.info("知识库：Chroma 不可达（%s），仅用本地索引", url)
        _storage = Storage(local, chroma)
        return _storage


def reset_storage() -> None:
    """测试用：清掉单例，让下次 get_storage() 重新探测。"""
    global _storage
    with _lock:
        _storage = None
