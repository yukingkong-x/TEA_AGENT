"""测试隔离：知识库一律用 tmp 目录 + 禁用 Chroma 镜像（不碰真实数据卷）。"""
from __future__ import annotations

import pytest

from app.knowledge import store as store_mod


@pytest.fixture(autouse=True)
def isolated_knowledge_store(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_STORE_DIR", str(tmp_path / "knowledge"))
    monkeypatch.setenv("KNOWLEDGE_CHROMA", "off")
    store_mod.reset_storage()
    yield
    store_mod.reset_storage()
