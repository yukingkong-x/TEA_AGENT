"""验证结论 → 任务终态、删文档 → 清向量、接线失败只降级。

这三条都不是「跑起来看得见」的功能，坏掉时也没有报错，只会在现场表现为
「任务一直转圈」「删了的知识还在被引用」「整个平台起不来」。所以逐条钉成测试。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models  # noqa: E402,F401  触发全部表注册到 metadata
from app.api import knowledge as knowledge_api  # noqa: E402
from app.api import verify as verify_api  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.knowledge_docs import KnowledgeDoc  # noqa: E402
from app.models.tasks import TASK_STATUS, Task  # noqa: E402


@pytest.fixture()
def session(tmp_path):
    """单表 SQLite：只需要 tasks / knowledge_docs。

    BigInteger 主键在 SQLite 下不会自增（只有 INTEGER PRIMARY KEY 才会），
    所以复制一份 metadata 把 id 换成 Integer——不动生产 DDL。
    """
    md = MetaData()
    for table in (Task.__table__, KnowledgeDoc.__table__):
        table.to_metadata(md)
    for table in md.tables.values():
        if "id" in table.c:
            table.c.id.type = Integer()

    engine = create_engine(f"sqlite:///{(tmp_path / 'link.db').as_posix()}", future=True)
    md.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _make_task(db, task_no: str = "task-20261114-0001", status: str = "running") -> Task:
    task = Task(task_no=task_no, type="verify", status=status, priority=5)
    db.add(task)
    db.commit()
    return task


# ---------------------------------------------------------------- 枚举与终态
def test_task_status_enum_has_needs_human():
    """PRD 10.2 / 11.3 要 needs_human；它与 workflow_runs 的口径必须一致。"""
    from app.models.workflow_runs import RUN_STATUS

    assert "needs_human" in TASK_STATUS
    assert "needs_human" in RUN_STATUS


@pytest.mark.parametrize(
    "verdict,expected",
    [("success", "success"), ("failed", "failed"), ("needs_human", "needs_human"), ("NEEDS_HUMAN", "needs_human")],
)
def test_apply_verdict_sets_task_status(session, verdict, expected):
    """验证结论必须落成任务终态：不落的话任务停在 running，60s 后被判超时形成假重试。"""
    _make_task(session)
    out = verify_api._apply_verdict(session, "task-20261114-0001", {"verdict": verdict, "verification_id": 7})
    assert out == expected

    session.expire_all()
    row = session.scalar(select(Task).where(Task.task_no == "task-20261114-0001"))
    assert row.status == expected
    assert row.result_json["verdict"] == verdict.lower()


def test_apply_verdict_merges_instead_of_overwriting_result(session):
    """result_json 里已有 ack 明细时只能增量合并，不能整块覆盖。"""
    _make_task(session)
    row = session.scalar(select(Task).where(Task.task_no == "task-20261114-0001"))
    row.result_json = {"result": "done", "detail": {"executed_s": 8}}
    session.commit()

    verify_api._apply_verdict(
        session, "task-20261114-0001", {"verdict": "success", "achievement": 99.2, "confidence": 88.0}
    )

    session.expire_all()
    row = session.scalar(select(Task).where(Task.task_no == "task-20261114-0001"))
    assert row.result_json["detail"]["executed_s"] == 8, "ack 明细被验证结论冲掉了"
    assert row.result_json["verdict"] == "success"
    assert row.result_json["achievement"] == 99.2


def test_apply_verdict_ignores_unknown_verdict_and_missing_task(session):
    """未知 verdict / 任务已被删：都不能抛异常，也不能乱改状态。"""
    _make_task(session, status="running")
    assert verify_api._apply_verdict(session, "task-20261114-0001", {"verdict": "weird"}) is None
    assert verify_api._apply_verdict(session, "task-不存在", {"verdict": "success"}) is None
    assert verify_api._apply_verdict(session, "task-20261114-0001", None) is None

    session.expire_all()
    row = session.scalar(select(Task).where(Task.task_no == "task-20261114-0001"))
    assert row.status == "running"


# ---------------------------------------------------------------- 删文档清向量
@pytest.fixture()
def fake_loader(monkeypatch):
    """把队长的 knowledge.loader 换成假模块：本分支可能还没有这个包，测试不该因此跳过。"""
    import types

    module = types.ModuleType("app.knowledge.loader")
    calls: list[int] = []

    def delete(doc_id: int) -> dict:
        calls.append(int(doc_id))
        return {"doc_id": int(doc_id), "removed": 4}

    module.delete = delete
    parent = sys.modules.get("app.knowledge") or types.ModuleType("app.knowledge")
    parent.loader = module
    monkeypatch.setitem(sys.modules, "app.knowledge", parent)
    monkeypatch.setitem(sys.modules, "app.knowledge.loader", module)
    return calls


def test_delete_doc_clears_vectors(session, fake_loader):
    """只删 MySQL 记录不删向量 → 已删文档仍会被检索到。"""
    doc = KnowledgeDoc(title="NY/T 5010-2016", status="ready")
    session.add(doc)
    session.commit()

    out = knowledge_api.delete_doc(doc.id, db=session)

    assert fake_loader == [doc.id], "没有调用向量清理"
    assert out == {"deleted": doc.id, "vectors_removed": 4}
    assert session.get(KnowledgeDoc, doc.id) is None


def test_delete_doc_survives_vector_failure(session, monkeypatch):
    """向量库不可用时仍要删掉记录，但必须留痕（返回 failed），不能假装成功。"""
    import types

    module = types.ModuleType("app.knowledge.loader")

    def boom(doc_id: int) -> dict:
        raise RuntimeError("chroma down")

    module.delete = boom
    parent = sys.modules.get("app.knowledge") or types.ModuleType("app.knowledge")
    parent.loader = module
    monkeypatch.setitem(sys.modules, "app.knowledge", parent)
    monkeypatch.setitem(sys.modules, "app.knowledge.loader", module)

    doc = KnowledgeDoc(title="临时文档", status="ready")
    session.add(doc)
    session.commit()

    out = knowledge_api.delete_doc(doc.id, db=session)
    assert out["vectors_removed"] == "failed"
    assert session.get(KnowledgeDoc, doc.id) is None


# ---------------------------------------------------------------- 接线降级
def test_install_degrades_when_module_missing():
    """缺模块只能降级（对应接口 503），绝不能让 app.main 起不来。"""
    from app import bootstrap

    assert bootstrap._install("不存在的模块", ".no_such_pkg.wiring", "install") is False


def test_sync_enum_column_is_silent_when_not_mysql(monkeypatch):
    """SQLite 下 information_schema 不存在：同步枚举必须静默跳过，不能挡住启动。"""
    from app import db as db_module

    engine = create_engine("sqlite://", future=True)
    monkeypatch.setattr(db_module, "engine", engine)
    try:
        assert db_module._sync_enum_column("tasks", "status", TASK_STATUS, default="pending") is False
    finally:
        engine.dispose()
