"""建单时的两项归属：run_id 与 assigned_device。

现场问题（2026-11-14 队长真模型联调）：
1. `tasks` / `verifications` 的 run_id 全是 NULL → 报告页按 run 聚合拿不到任务，
   时间线和轮次空白，`GET /api/runs/{id}` 的 tasks 恒为空。工具 schema 里没有
   run_id（也不该让 LLM 填），所以由引擎把 run 写进 ContextVar、建单时读取。
2. 引擎补建的单带 `payload.device_id`，但建单没落到 `assigned_device` → 调度器
   没有派发目标，单子停在 dispatched 空转，超时后变 dead。

这两个字段都不该依赖 LLM 传参：run_id 读上下文，device_id 从 payload 解析。
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as app_db  # noqa: E402
from app.core import ids, runtime_settings, tool_impl  # noqa: E402
from app.models.devices import Device  # noqa: E402
from app.models.tasks import Task  # noqa: E402
from app.models.workflow_runs import WorkflowRun  # noqa: E402

TABLES = [Task.__table__, Device.__table__, WorkflowRun.__table__]


def _metadata() -> MetaData:
    """复制一份 metadata 给 SQLite：BigInteger 主键要换成 Integer 才有 rowid 自增。"""
    md = MetaData()
    for table in TABLES:
        table.to_metadata(md)
    for table in md.tables.values():
        if "id" in table.c:
            table.c.id.type = Integer()
    return md


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'attrib.db').as_posix()}", future=True)
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
    # run_context 是在函数内 `from ..db import session_scope`，要连 app.db 一起换
    monkeypatch.setattr(app_db, "session_scope", fake_scope)
    # 不依赖 Redis（new_task_no 会先试 INCR，宿主机上要等 DNS 超时）
    def boom():
        raise RuntimeError("redis disabled in this test")

    monkeypatch.setattr(ids, "get_redis", boom)
    monkeypatch.setattr(runtime_settings, "get_mode", lambda: "mock")
    tool_impl.CURRENT_RUN_ID.set(None)   # 同一进程内多条用例互不污染
    yield maker
    tool_impl.CURRENT_RUN_ID.set(None)


def _add_run(maker, status="running") -> int:
    with maker() as session:
        run = WorkflowRun(wf_id=3, status=status, trigger="manual")
        session.add(run)
        session.commit()
        return int(run.id)


def _add_devices(maker) -> None:
    with maker() as session:
        session.add_all([
            Device(device_id="mock-k10-act-03", name="A区灌溉终端", role="actuator",
                   location="A区茶垄", is_mock=True, online=True),
            Device(device_id="mock-esp32-soil-02", name="A区土壤探头", role="soil",
                   location="A区茶垄", is_mock=True, online=True),
        ])
        session.commit()


def _only_task(maker) -> Task:
    with maker() as session:
        return session.scalars(select(Task)).one()


# ─────────────────────────── run_id ───────────────────────────

def test_run_id_from_contextvar(db):
    tool_impl.set_current_run_id(77)
    tool_impl.create_task("device_cmd", {"action": "pump"}, priority=9)
    assert _only_task(db).run_id == 77


def test_run_id_falls_back_to_the_only_running_run(db):
    run_id = _add_run(db, "running")
    _add_run(db, "success")
    tool_impl.create_task("device_cmd", {"action": "pump"}, priority=9)
    assert _only_task(db).run_id == run_id


def test_ambiguous_running_runs_leave_run_id_null(db):
    """两条都在跑时不能猜：挂错 run 比 NULL 更难排查。"""
    _add_run(db, "running")
    _add_run(db, "running")
    tool_impl.create_task("device_cmd", {"action": "pump"}, priority=9)
    assert _only_task(db).run_id is None


def test_explicit_run_id_wins(db):
    tool_impl.set_current_run_id(77)
    tool_impl.create_task("report", {"note": "手动"}, run_id=99)
    assert _only_task(db).run_id == 99


# ─────────────────────────── assigned_device ───────────────────────────

def test_payload_device_reference_lands_assigned_device(db):
    """「A区」要按执行器解析：device_cmd 的派发目标是泵/阀，不是土壤探头。"""
    _add_devices(db)
    result = tool_impl.create_task(
        "device_cmd", {"device_id": "A区", "action": "pump", "duration_s": 30}, priority=9,
    )
    task = _only_task(db)
    assert task.assigned_device == "mock-k10-act-03"
    assert task.payload_json["device_id"] == "mock-k10-act-03"   # 回写，执行管家发得出
    assert result["assigned_device"] == "mock-k10-act-03"


def test_exact_device_id_is_kept(db):
    _add_devices(db)
    tool_impl.create_task("device_cmd", {"device_id": "mock-k10-act-03", "action": "pump"})
    assert _only_task(db).assigned_device == "mock-k10-act-03"


def test_unknown_reference_falls_back_to_the_only_actuator(db):
    """「B区泵房3号」这种解析不出的指代，按 device_match 规则 7 落到唯一执行器。

    这是有意的：演示现场只有一台灌溉终端，宁可把单派给它也不要留 NULL 让单子
    空转超时——漏浇一次比"发给唯一的泵"更不可接受。
    """
    _add_devices(db)
    tool_impl.create_task("device_cmd", {"device_id": "B区泵房3号", "action": "pump"})
    assert _only_task(db).assigned_device == "mock-k10-act-03"


def test_no_device_candidates_keeps_raw_value(db):
    """设备表为空（真机还没登记）时保留原值：任务列表里至少能看出想发给谁。"""
    tool_impl.create_task("device_cmd", {"device_id": "B区泵房3号", "action": "pump"})
    assert _only_task(db).assigned_device == "B区泵房3号"


def test_task_without_device_keeps_assigned_device_null(db):
    """agent_call/verify 这类任务没有设备，别硬造一个。"""
    tool_impl.create_task("verify", {"task_no": "task-1"})
    assert _only_task(db).assigned_device is None
