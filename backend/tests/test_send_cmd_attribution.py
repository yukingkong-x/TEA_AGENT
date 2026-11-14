"""真实下发时的两个必备事实：任务挂 run_id、轨迹里留下 `event="dispatch"`。

为什么单独立一条：
- 执行管家自建的单（决策官没给 task_no，schema 也没有）以前 run_id 恒为 NULL，
  报告页按 run 聚合时这条任务根本不出现；
- `event="dispatch"` 是「真的发给设备了」的唯一凭据，任务认领逻辑靠它区分
  「调度器标了 dispatched」和「确实下发过」——少了它一次浇水会变成两张单
  （run 19 实测：task-0011 反复超时、task-0012 才是真执行的那张）。
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import ids, run_context, tool_impl  # noqa: E402
from app.devices import command  # noqa: E402
from app.models.devices import Device  # noqa: E402
from app.models.task_events import TaskEvent  # noqa: E402
from app.models.tasks import Task  # noqa: E402

TABLES = [Task.__table__, Device.__table__, TaskEvent.__table__]


def _metadata() -> MetaData:
    md = MetaData()
    for table in TABLES:
        table.to_metadata(md)
    for table in md.tables.values():
        if "id" in table.c:
            table.c.id.type = Integer()
    return md


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'send.db').as_posix()}", future=True)
    _metadata().create_all(bind=engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = maker()

    def boom():
        raise RuntimeError("redis disabled in this test")

    monkeypatch.setattr(command, "get_redis", boom)
    monkeypatch.setattr(ids, "get_redis", boom)
    with session:
        session.add(Device(device_id="mock-k10-act-03", name="A区灌溉终端", role="actuator",
                           location="A区茶垄", is_mock=True, online=True))
        session.commit()
    tool_impl.CURRENT_RUN_ID.set(None)
    yield session
    tool_impl.CURRENT_RUN_ID.set(None)
    session.close()


def test_send_cmd_writes_run_id_from_context(db):
    token = run_context.set_current_run_id(42)
    try:
        result = command.send_cmd(db, "mock-k10-act-03", "pump", {"duration_s": 5},
                                  issued_by="agent:executor")
    finally:
        run_context.reset_current_run_id(token)

    task = db.scalar(select(Task).where(Task.task_no == result["task_no"]))
    assert task.run_id == 42


def test_send_cmd_leaves_dispatch_evidence(db):
    result = command.send_cmd(db, "mock-k10-act-03", "pump", {"duration_s": 5},
                              issued_by="agent:executor")
    row = db.scalar(select(TaskEvent).where(TaskEvent.task_no == result["task_no"],
                                            TaskEvent.event == "dispatch"))
    assert row is not None, "下发没留 dispatch 轨迹：任务认领会把这张单当成『待发』再发一次"
    assert row.to_status == "dispatched"
    assert row.payload_json["device_id"] == "mock-k10-act-03"
