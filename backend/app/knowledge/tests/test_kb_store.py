"""存储：本地索引的增删查、Chroma 掉线时的兜底与合并。"""
from __future__ import annotations

from app.knowledge import embed as embed_mod
from app.knowledge.store import ChromaStore, Hit, LocalStore, Record, Storage


def _record(doc_id: int, index: int, text: str) -> Record:
    return Record(
        id=f"doc{doc_id}-{index}",
        doc_id=doc_id,
        title=f"规程{doc_id}.txt",
        chunk_text=text,
        chunk_index=index,
        vector=embed_mod.embed(text),
    )


def test_local_add_query_delete(tmp_path):
    store = LocalStore(tmp_path / "vectors.json")
    store.add([
        _record(1, 0, "土壤湿度低于 55% 应灌溉"),
        _record(1, 1, "茶叶采摘后摊放萎凋"),
    ])
    assert store.stats() == {"chunks": 2, "docs": 1}

    hits = store.query(embed_mod.embed("湿度低要浇水吗"), 2)
    assert len(hits) == 2
    assert "灌溉" in hits[0].chunk_text          # 相关块排第一
    assert hits[0].score > hits[1].score

    assert store.delete_doc(1) == 2
    assert store.stats()["chunks"] == 0
    assert store.query(embed_mod.embed("灌溉"), 3) == []


def test_local_add_is_idempotent_by_id(tmp_path):
    store = LocalStore(tmp_path / "vectors.json")
    store.add([_record(1, 0, "第一版内容")])
    store.add([_record(1, 0, "第二版内容")])      # 同 id 覆盖
    assert store.stats()["chunks"] == 1
    assert "第二版" in store.query(embed_mod.embed("第二版内容"), 1)[0].chunk_text


def test_corrupt_index_is_treated_as_empty(tmp_path):
    path = tmp_path / "vectors.json"
    path.write_text("{not json", encoding="utf-8")
    store = LocalStore(path)
    assert store.stats()["chunks"] == 0


class _BrokenChroma(ChromaStore):
    """模拟“healthcheck 通了但读写真失败”的 Chroma（版本不匹配/权限问题）。"""

    def __init__(self):
        super().__init__("http://127.0.0.1:1")

    def add(self, records):  # noqa: D102
        raise RuntimeError("boom")

    def query(self, vector, top_k):  # noqa: D102
        raise RuntimeError("boom")


def test_storage_falls_back_when_chroma_fails(tmp_path):
    storage = Storage(LocalStore(tmp_path / "vectors.json"), _BrokenChroma())
    storage.add([_record(2, 0, "霜冻预警：低于 4℃ 启动风机")])
    assert storage.stats()["chunks"] == 1        # 本地照写

    hits = storage.query(embed_mod.embed("霜冻预警"), 1)
    assert hits and hits[0].doc_id == 2          # 查询退回本地


class _FakeChroma(ChromaStore):
    def __init__(self):
        super().__init__("http://127.0.0.1:1")
        self.added: list[Record] = []

    def add(self, records):
        self.added.extend(records)

    def delete_doc(self, doc_id):
        return 0

    def query(self, vector, top_k):
        return [Hit(id="doc9-0", doc_id=9, title="镜像.txt", chunk_text="镜像命中",
                    chunk_index=0, score=0.9)]


def test_chroma_heartbeat_false_when_unreachable():
    # 端口 1 必然连不上：心跳要返回 False 而不是抛异常，否则启动时整个知识库挂掉
    assert ChromaStore("http://127.0.0.1:1").heartbeat() is False


def test_storage_merges_mirror_and_local_without_duplicates(tmp_path):
    fake = _FakeChroma()
    storage = Storage(LocalStore(tmp_path / "vectors.json"), fake)
    storage.add([_record(3, 0, "本地内容")])
    assert len(fake.added) == 1                  # 双写：镜像也收到了

    hits = storage.query(embed_mod.embed("本地内容"), 3)
    ids = [h.chunk_text for h in hits]
    assert "镜像命中" in ids
    assert ids.count("本地内容") == 1            # 同 id 不会重复出现
