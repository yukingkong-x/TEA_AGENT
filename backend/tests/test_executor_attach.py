"""执行管家下发时的「任务认领」：不能让一次浇水在库里变成两张单。

现场链路（2026-11-14 实测）：
1. 决策官/引擎建单 → tasks 里一行 device_cmd（pending，assigned_device 为空）；
2. 调度器 tick 立刻把它标成 dispatched —— 但并没有真的发给设备；
3. 真正下发只有执行管家调 `send_device_cmd` 一条路，而该工具的 schema（PRD 7.3）
   没有 task_no，执行管家拿不到号时就自己造一张新单。
结果：一张单永远超时重试（task-0005 连续 60s×N 次 timeout），另一张才是真执行的。

`send_device_cmd` 因此改成：给了 task_no 就复用；没给就认领「dispatched 且没有
assigned_device」的最近一张同动作单（= 建了但没人发的那张）。
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Integer, MetaData, create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import tool_impl  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.tasks import Task  # noqa: E402

TABLES = [Task.__table__]


def _metadata() -> MetaData:
    md = MetaData()
    for table in TABLES:
        table.to_metadata(md)
    for table in md.tables.values():
        if "id" in table.c:
            table.c.id.type = Integer()
    return md


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    """把 tool_impl 的 session_scope 换成这个测试库，并拦住真正的下发。"""
    engine = create_engine(f"sqlite:///{(tmp_path / 'attach.db').as_posix()}", future=True)
    _metadata().create_all(bind=engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @contextmanager
    def fake_scope():
        session = maker()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(tool_impl, "session_scope", fake_scope)

    captured: dict = {}

    def fake_send(db, device_id, action, params=None, **kwargs):
        captured.update({"device_id": device_id, "action": action,
                         "params": params, "task_no": kwargs.get("task_no")})
        return {"task_no": kwargs.get("task_no") or "task-new", "device_id": device_id,
                "action": action, "params": params}

    monkeypatch.setattr(tool_impl.command, "send_cmd", fake_send)
    return maker, captured


def _add(maker, task_no, status, device=None, action="pump"):
    with maker() as db:
        db.add(Task(task_no=task_no, type="device_cmd", status=status,
                    assigned_device=device, priority=9,
                    payload_json={"action": action, "params": {"duration_s": 30}}))
        db.commit()


def test_attaches_to_the_task_nobody_dispatched(db_session):
    maker, captured = db_session
    _add(maker, "task-0005", "dispatched", device=None)   # 建了单但没下发
    tool_impl.send_device_cmd("A区", "pump", {"duration_s": 30})
    assert captured["task_no"] == "task-0005"


def test_does_not_steal_a_task_that_was_really_sent(db_session):
    """assigned_device 有值 = 真下发过，不能抢回来重发。"""
    maker, captured = db_session
    _add(maker, "task-0004", "dispatched", device="mock-k10-act-03")
    tool_impl.send_device_cmd("A区", "pump", {"duration_s": 30})
    assert captured["task_no"] is None


def test_explicit_task_no_always_wins(db_session):
    maker, captured = db_session
    _add(maker, "task-0005", "dispatched", device=None)
    tool_impl.send_device_cmd("A区", "pump", {"duration_s": 30}, task_no="task-9999")
    assert captured["task_no"] == "task-9999"


def test_other_action_is_not_claimed(db_session):
    """认领只看同动作：泵的单不能被 valve 的下发顺手拿走。"""
    maker, captured = db_session
    _add(maker, "task-0005", "dispatched", device=None, action="pump")
    tool_impl.send_device_cmd("A区", "valve", {"duration_s": 10})
    assert captured["task_no"] is None


def test_newest_candidate_wins(db_session):
    maker, captured = db_session
    _add(maker, "task-0005", "dispatched", device=None)
    _add(maker, "task-0006", "pending", device=None)
    tool_impl.send_device_cmd("A区", "pump", {"duration_s": 30})
    assert captured["task_no"] == "task-0006"
