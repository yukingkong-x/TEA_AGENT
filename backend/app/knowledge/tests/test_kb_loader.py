"""接缝 ingest：切片数、幂等重传、删除、抽不出正文必须失败。"""
from __future__ import annotations

import pytest

from app.knowledge import loader
from app.knowledge.extract import ExtractionError
from app.knowledge.store import get_storage

TXT = (
    "一、土壤湿度低于 55% 时应灌溉，沙壤土取下限，黏土取上限。\n\n"
    "二、单次灌溉以湿润 20 厘米土层为准，避免地表径流。\n\n"
    "三、灌溉后 30 分钟复测，达成率低于 80% 需补灌。\n"
)


def _write(tmp_path, name: str, text: str):
    file = tmp_path / name
    file.write_text(text, encoding="utf-8")
    return file


def test_ingest_returns_contract_fields(tmp_path):
    result = loader.ingest(str(_write(tmp_path, "规程.txt", TXT)), doc_id=1)
    assert result["chunk_count"] >= 1
    assert len(result["chroma_ids"]) == result["chunk_count"]
    assert result["title"] == "规程.txt"
    assert result["backend"] == "local"


def test_ingest_is_idempotent_for_same_doc(tmp_path):
    path = str(_write(tmp_path, "规程.txt", TXT))
    first = loader.ingest(path, doc_id=7)
    second = loader.ingest(path, doc_id=7)
    assert first["chunk_count"] == second["chunk_count"]
    # 断点：重传不先清旧块会让切片数翻倍，检索出现大量重复引用
    assert get_storage().stats()["chunks"] == second["chunk_count"]


def test_ingest_different_docs_accumulate(tmp_path):
    loader.ingest(str(_write(tmp_path, "a.txt", TXT)), doc_id=1)
    loader.ingest(str(_write(tmp_path, "b.txt", "霜冻预警：气温低于 4℃ 启动防霜风机。")), doc_id=2)
    assert get_storage().stats()["docs"] == 2


def test_delete_removes_vectors(tmp_path):
    loader.ingest(str(_write(tmp_path, "a.txt", TXT)), doc_id=3)
    assert loader.delete(3)["removed"] >= 1
    assert get_storage().stats()["chunks"] == 0


def test_ingest_raises_when_no_text(tmp_path):
    file = tmp_path / "short.txt"
    file.write_text("短", encoding="utf-8")
    with pytest.raises(ExtractionError):
        loader.ingest(str(file), doc_id=4)
    # 失败不应留下半截向量
    assert get_storage().stats()["chunks"] == 0
