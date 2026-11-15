"""节点级执行记录：字段映射、幂等、轮次提取、汇总。

这是「每个节点耗时表」的数据源。引擎收尾时只调一行 `record_run_nodes`，
所以这里必须保证：传 NodeRecord 对象或 dict 都能吃、重复写不插重复、
表不存在时返回 0 而不是把 run 打成失败。
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import node_records  # noqa: E402
from app.models.workflow_node_records import WorkflowNodeRecord  # noqa: E402


class FakeNode:
    """形状对齐 engine.NodeRecord（不 import 引擎，基座测试不依赖队长模块）。"""

    def __init__(self, node_id, type, name, status="done", **kw):
        self.node_id = node_id
        self.type = type
        self.name = name
        self.status = status
        self.agent_key = kw.get("agent_key")
        self.output = kw.get("output", "")
        self.error = kw.get("error", "")
        self.degraded = kw.get("degraded", False)
        self.tool_calls = kw.get("tool_calls", [])
        self.tokens_in = kw.get("tokens_in", 0)
        self.tokens_out = kw.get("tokens_out", 0)
        self.duration_ms = kw.get("duration_ms", 0)


def _metadata() -> MetaData:
    md = MetaData()
    WorkflowNodeRecord.__table__.to_metadata(md)
    for table in md.tables.values():
        if "id" in table.c:
            table.c.id.type = Integer()
    return md


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'nodes.db').as_posix()}", future=True)
    _metadata().create_all(bind=engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @contextmanager
    def fake_scope():
        session = maker()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(node_records, "session_scope", fake_scope)
    return maker


def _rows(maker):
    with maker() as session:
        return session.scalars(select(WorkflowNodeRecord).order_by(WorkflowNodeRecord.id)).all()


def test_maps_engine_node_record_fields(db):
    maker = db
    nodes = [
        FakeNode("n1", "start", "开始", duration_ms=3),
        FakeNode("n7", "agent", "灌溉决策", agent_key="decision", duration_ms=8200,
                 output="【决策】本轮决策:irrigate", tokens_in=1200, tokens_out=180,
                 tool_calls=[{"name": "create_task", "status": "ok"}]),
        FakeNode("n11b", "loop", "Self-Loop", output="rounds=2", duration_ms=12, degraded=True),
    ]
    assert node_records.record_run_nodes(23, nodes) == 3
    rows = {r.node_id: r for r in _rows(maker)}
    assert rows["n7"].agent_key == "decision"
    assert rows["n7"].duration_ms == 8200
    assert rows["n7"].tokens_in == 1200
    assert rows["n7"].tool_calls_json[0]["name"] == "create_task"
    assert rows["n7"].started_at is not None and rows["n7"].finished_at is not None
    # 开始时刻 = 结束时刻 - 耗时（引擎没给 started_at，用耗时反推）
    assert (rows["n7"].finished_at - rows["n7"].started_at).total_seconds() == pytest.approx(8.2)
    assert rows["n11b"].round_no == 2
    assert rows["n11b"].degraded is True


def test_accepts_plain_dicts(db):
    """引擎若改成传 dict（比如从 WS 事件回放）也要能写。"""
    maker = db
    assert node_records.record_run_nodes(23, [
        {"node_id": "n4", "node_type": "agent", "name": "气象研判", "status": "done",
         "agent_key": "weather", "duration_ms": 5000},
    ]) == 1
    row = _rows(maker)[0]
    assert row.node_type == "agent" and row.duration_ms == 5000


def test_is_idempotent(db):
    """run 收尾被调两次（重试、异常重入）不能插重复行。"""
    maker = db
    nodes = [FakeNode("n1", "start", "开始", duration_ms=1)]
    assert node_records.record_run_nodes(23, nodes) == 1
    assert node_records.record_run_nodes(23, nodes) == 0
    assert len(_rows(maker)) == 1


def test_skips_without_run_id(db):
    assert node_records.record_run_nodes(None, [FakeNode("n1", "start", "开始")]) == 0
    assert node_records.record_run_nodes(0, [FakeNode("n1", "start", "开始")]) == 0


def test_load_and_summarize(db):
    maker = db
    node_records.record_run_nodes(23, [
        FakeNode("n1", "start", "开始", duration_ms=2),
        FakeNode("n7", "agent", "灌溉决策", agent_key="decision", duration_ms=8200),
        FakeNode("n9", "agent", "执行浇水", agent_key="executor", duration_ms=4100, degraded=True),
        FakeNode("n10", "tool", "渗透等待", duration_ms=90000),
    ])
    loaded = node_records.load_run_nodes(23)
    assert [n["node_id"] for n in loaded] == ["n1", "n7", "n9", "n10"]
    summary = node_records.summarize(loaded)
    assert summary["node_count"] == 4
    assert summary["duration_ms"] == 2 + 8200 + 4100 + 90000
    assert summary["slowest"]["node_id"] == "n10"
    assert summary["degraded_count"] == 1
    assert summary["failed_count"] == 0


def test_summarize_empty():
    assert node_records.summarize([])["node_count"] == 0
    assert node_records.summarize([])["slowest"] is None
