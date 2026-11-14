"""任务轨迹接口（REQ-F-015 / 契约第 11 节）：排序、时间格式、截断语义。

为什么值得单独一个测试文件：轨迹抽屉是 PRD 986 唯一「点开能回溯」的证据，
而它的三个坑都是**看着能跑、现场才炸**的那种：

1. `isoformat(sep=" ")` 在 Safari / iPad 上是 `Invalid Date`（演示机就是 Safari）；
2. 按 `created_at` 排序会在同一秒连落多行时乱序（ack 与状态变更常常同秒）；
3. `total` 若跟着 `limit` 走，前端分不出「只有 6 条」和「有 300 条只看前 100 条」。
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import BigInteger, Integer, MetaData, create_engine, func, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import tasks as tasks_api  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.task_events import TaskEvent  # noqa: E402
from app.models.tasks import Task  # noqa: E402

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# 只建这两张：`reports` 用了 MySQL 专属的 LONGTEXT，SQLite 上 create_all 会 CompileError
TABLES = [Task.__table__, TaskEvent.__table__]

TASK_NO = "task-20261114-0007"


def _sqlite_metadata() -> MetaData:
    """给 SQLite 复制一份 metadata，主键改 Integer。

    生产主键是 BigInteger（MySQL AUTO_INCREMENT），SQLite 只给
    `INTEGER PRIMARY KEY` 分配 rowid；直接用原表建，`db.add()` 不显式给 id 就
    NOT NULL 失败——而落库代码（task_trail.record）本来就不该知道 id 这回事。
    """
    md = MetaData()
    for table in TABLES:
        table.to_metadata(md)
    for table in md.tables.values():
        if "id" in table.c:
            table.c.id.type = Integer()
    return md


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'trail.db').as_posix()}", future=True)
    _sqlite_metadata().create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    # SQLite 的 BigInteger 主键不自增，id 全部显式给
    session.add(Task(id=1, task_no=TASK_NO, type="device_cmd", status="dispatched", retry_count=0))
    session.add(Task(id=2, task_no="task-empty", type="agent_call", status="pending", retry_count=0))
    base = datetime(2026, 11, 14, 10, 31, 2)
    session.add_all(
        [
            # 三行的 created_at 故意**逆序**写入：接口必须按 id 排，不是按时间排
            TaskEvent(
                id=31, task_no=TASK_NO, run_id=1, event="task_status",
                from_status="pending", to_status="dispatched", reason="dispatch",
                actor="scheduler", payload_json={"score": 0.71},
                created_at=base + timedelta(seconds=2), updated_at=base + timedelta(seconds=2),
            ),
            TaskEvent(
                id=34, task_no=TASK_NO, run_id=1, event="task_status",
                from_status="dispatched", to_status="running", reason="ack", actor="device",
                created_at=base, updated_at=base,
            ),
            TaskEvent(
                id=39, task_no=TASK_NO, run_id=1, event="verify",
                from_status="running", to_status="success", reason="verify_pass", actor="verifier",
                created_at=base + timedelta(seconds=5), updated_at=base + timedelta(seconds=5),
            ),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _events(db, limit: int = 100) -> dict:
    return tasks_api.list_task_events(task_no=TASK_NO, limit=limit, db=db)


def test_events_are_ordered_by_id_not_timestamp(db):
    """按 id 升序 —— 同一秒里连落多行时，时间排序不可靠。"""
    items = _events(db)["items"]
    assert [e["id"] for e in items] == [31, 34, 39]
    # 时间戳本身是逆序写入的，若实现改回 created_at 排序，这里立刻红
    assert [e["at"] for e in items] == ["2026-11-14T10:31:04", "2026-11-14T10:31:02", "2026-11-14T10:31:07"]


def test_at_is_isoformat_with_t(db):
    """`at` 必须带 `T`：`2026-11-14 10:31:02` 在 Safari 上是 Invalid Date。"""
    for e in _events(db)["items"]:
        assert "T" in e["at"]
        assert " " not in e["at"]
        assert datetime.fromisoformat(e["at"])  # 能被标准解析器吃下


def test_item_fields_match_contract(db):
    """字段名必须是契约第 11 节的 from/to/payload，不是 from_status/to_status。"""
    first = _events(db)["items"][0]
    assert first == {
        "id": 31,
        "event": "task_status",
        "from": "pending",
        "to": "dispatched",
        "reason": "dispatch",
        "actor": "scheduler",
        "at": "2026-11-14T10:31:04",
        "payload": {"score": 0.71},
    }


def test_total_counts_all_events_even_when_limit_truncates(db):
    """`total` 是总数、不受 limit 影响 —— 前端据此判断「被截断」而不是「就这么多」。"""
    page = _events(db, limit=2)
    assert len(page["items"]) == 2
    assert page["total"] == 3


def test_unknown_task_returns_404(db):
    """任务号打错要 404，不能返回空数组 —— 否则前端分不出「还没跑」和「打错了」。"""
    with pytest.raises(HTTPException) as exc:
        tasks_api.list_task_events(task_no="task-nope", limit=100, db=db)
    assert exc.value.status_code == 404


def test_existing_task_without_events_returns_empty(db):
    page = tasks_api.list_task_events(task_no="task-empty", limit=100, db=db)
    assert page == {"items": [], "total": 0}


def test_run_id_column_is_biginteger():
    """`run_id` 必须跟 tasks.run_id 同为 BigInteger：Integer 在执行号上会溢出。"""
    assert isinstance(TaskEvent.__table__.c.run_id.type, BigInteger)


def test_no_space_separated_isoformat_left_in_app():
    """全站守卫：`isoformat(sep=" ` 一个都不能留（Safari 解析失败）。

    这条替代「改一次忘一处」的人工检查——19 处序列化分散在 10 个文件，
    靠 review 看不住，只能靠测试。
    """
    offenders = [
        f"{p.relative_to(APP_DIR).as_posix()}:{i}"
        for p in APP_DIR.rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        # 只认真正的调用（前面有个点），文档里提到这个反例不算违规
        if re.search(r'\.isoformat\(\s*sep\s*=\s*["\'] ', line)
    ]
    assert offenders == [], f"这些地方还在用空格分隔的时间格式：{offenders}"


# ---------------------------------------------------------------- 落库侧（device_cmd 链路）
def test_trail_writes_one_row_per_transition(db):
    """下发→回执两跳各落一行，from/to 是状态机的边。"""
    pytest.importorskip("app.orchestrator.events")  # 拼装逻辑在队长分支，缺它时本模块静默降级

    from app.core import task_trail

    baseline = _events(db)["total"]
    assert task_trail.record(
        db, task_no=TASK_NO, from_status=None, to_status="dispatched", reason="dispatch", actor="human"
    )
    assert task_trail.record(
        db, task_no=TASK_NO, from_status="dispatched", to_status="running", reason="ack", actor="device"
    )
    db.commit()

    items = _events(db)["items"]
    assert len(items) == baseline + 2
    assert [(e["from"], e["to"], e["reason"], e["actor"]) for e in items[-2:]] == [
        (None, "dispatched", "dispatch", "human"),
        ("dispatched", "running", "ack", "device"),
    ]


def test_trail_skips_identical_consecutive_event(db):
    """设备重复回 `received` 时 running→running 会刷屏，同构事件必须丢掉。"""
    pytest.importorskip("app.orchestrator.events")

    from app.core import task_trail

    baseline = _events(db)["total"]
    kwargs = dict(task_no=TASK_NO, from_status="dispatched", to_status="running", reason="ack", actor="device")
    assert task_trail.record(db, **kwargs) is True
    assert task_trail.record(db, **kwargs) is False   # 与上一行同构 → 跳过
    db.commit()
    assert _events(db)["total"] == baseline + 1


def test_trail_never_raises_when_table_missing(tmp_path):
    """缺表时只降级不抛异常：轨迹是加分项，不能让指令下发/回执跟着挂。"""
    pytest.importorskip("app.orchestrator.events")

    from app.core import task_trail

    engine = create_engine(f"sqlite:///{(tmp_path / 'no_table.db').as_posix()}", future=True)
    Base.metadata.create_all(bind=engine, tables=[Task.__table__])  # 故意不建 task_events
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        assert task_trail.record(
            session, task_no=TASK_NO, from_status="pending", to_status="dispatched", reason="dispatch"
        ) is False
        # 会话仍可用：SAVEPOINT 回滚了失败的插入，没有把整个事务带进 aborted 状态
        assert session.scalar(select(func.count()).select_from(Task)) == 0
    finally:
        session.close()


def test_verdict_lands_terminal_status_and_verify_event(db):
    """验证结论落终态时补一行 `event=verify` 的轨迹（actor=verifier）。

    抽屉要能区分「调度器派发的」和「验证官判出来的」，所以 event 不用 task_status。
    这条同时钉住「验证不再留下 running 孤儿」——没有这一层，任务会一直 running，
    60s 后被调度器判超时、重试、再超时，大屏上像在反复失败。
    """
    pytest.importorskip("app.orchestrator.events")

    from app.api.verify import _VERDICT_TO_STATUS, _apply_verdict

    baseline = _events(db)["total"]
    status = _apply_verdict(db, TASK_NO, {"verdict": "failed", "confidence": 71.5, "note": "湿度未达标"})

    assert status == _VERDICT_TO_STATUS["failed"] == "failed"
    items = _events(db)["items"]
    assert len(items) == baseline + 1
    last = items[-1]
    assert (last["event"], last["to"], last["reason"], last["actor"]) == ("verify", "failed", "failed", "verifier")
    assert last["payload"]["confidence"] == 71.5

    # result_json 是合并写入：不能把已有的 ack 明细冲掉
    assert db.get(Task, 1).result_json["verdict"] == "failed"
