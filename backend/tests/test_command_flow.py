"""指令下发 → 回执 → 任务状态流转（用 SQLite 文件库，不依赖 MySQL/Redis/MQTT）。

这里刻意用**两个独立的 Engine/Session**模拟真实拓扑：
- Session A：FastAPI 请求线程，调 `send_cmd`
- Session B：paho 回调线程，处理设备 ack（`_handle_ack` 自己开 `session_scope`）

两者之间没有任何共享内存，能不能看到彼此的数据完全由「提交时机」决定。
`send_cmd` 一旦把 `db.commit()` 退回 `db.flush()`，Session B 就查不到 Task，
于是 ack 只广播不落库、任务永远卡在 dispatched、超时后还会补一条假报警。
这条测试就是钉住那个时序的。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models  # noqa: E402,F401  触发全部表注册到 metadata
from app.core import ids  # noqa: E402
from app.devices import command  # noqa: E402
from app.models.alerts import Alert  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.devices import Device  # noqa: E402
from app.models.tasks import Task  # noqa: E402

ACT = "k10-act-03"

# 只建这三张：reports 用了 MySQL 专属的 LONGTEXT，SQLite 方言渲染不了，
# 而本测试也用不到它（建全表会让 CompileError 把整个 fixture 拖挂）。
FLOW_TABLES = [Device.__table__, Task.__table__, Alert.__table__]


def _sqlite_metadata() -> MetaData:
    """复制一份 metadata 给 SQLite 用。

    生产主键是 BigInteger（MySQL AUTO_INCREMENT），SQLite 只认
    `INTEGER PRIMARY KEY` 才给 rowid 自动分配，否则 NOT NULL 直接失败。
    用 to_metadata 复制而不是改原表，避免污染其他测试与生产 DDL。
    """
    md = MetaData()
    for table in FLOW_TABLES:
        table.to_metadata(md)
    for table in md.tables.values():
        if "id" in table.c:
            table.c.id.type = Integer()
    return md


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """本文件不依赖 Redis：所有相关调用都在 try/except 里，让它立刻抛。

    注意必须连 `ids` 的 `get_redis` 一起打桩：`new_task_no()` / `new_msg_id()`
    会先试 `INCR`，在宿主机上解析容器服务名要等 DNS 超时（单次 ~2.7s），
    每个用例白等 5 秒。打掉后走「时间戳+随机」降级分支，测试也不依赖 6379。
    """

    def boom():
        raise RuntimeError("redis disabled in this test")

    monkeypatch.setattr(command, "get_redis", boom)
    monkeypatch.setattr(ids, "get_redis", boom)


@pytest.fixture()
def two_sessions(tmp_path):
    """两个互不相知的 session，指向同一个 SQLite 文件。"""
    url = f"sqlite:///{(tmp_path / 'flow.db').as_posix()}"
    engine_a = create_engine(url, future=True)
    _sqlite_metadata().create_all(bind=engine_a)
    mk = lambda: sessionmaker(bind=create_engine(url, future=True), expire_on_commit=False, future=True)()  # noqa: E731
    # B 用独立 engine，确保不共享连接池里的那条连接
    a = sessionmaker(bind=engine_a, expire_on_commit=False, future=True)()
    b = mk()
    try:
        yield a, b
    finally:
        a.close()
        b.close()


def test_send_cmd_visible_to_other_session_before_ack(two_sessions):
    """下发后立刻用另一个 session 查：必须查得到（= publish 之前已经 commit）。"""
    a, b = two_sessions
    result = command.send_cmd(a, ACT, "pump", {"duration_s": 5}, issued_by="api:manual")

    seen = b.scalar(select(Task).where(Task.task_no == result["task_no"]))
    assert seen is not None, "ack 线程查不到 Task：send_cmd 在 publish 前没有 commit"
    assert seen.status == "dispatched"
    assert seen.assigned_device == ACT


def test_ack_flow_reaches_success(two_sessions):
    """received → running，finished → success，且状态能被第三个 session 看到。"""
    a, b = two_sessions
    result = command.send_cmd(a, ACT, "pump", {"duration_s": 5}, issued_by="agent:executor")
    task_no = result["task_no"]

    command.handle_ack(b, {"task_id": task_no, "device_id": ACT, "stage": "received", "result": "done"})
    b.commit()
    running = b.scalar(select(Task).where(Task.task_no == task_no))
    assert running.status == "running"

    command.handle_ack(
        b,
        {
            "task_id": task_no,
            "device_id": ACT,
            "stage": "finished",
            "result": "done",
            "detail": {"executed_s": 5},
        },
    )
    b.commit()

    # 回到 A 的 session 读，确认已落库而不是只在 B 的会话里
    a.expire_all()
    final = a.scalar(select(Task).where(Task.task_no == task_no))
    assert final.status == "success", f"任务没流转到 success，停在 {final.status}"
    assert final.result_json["result"] == "done"


def test_ack_for_unknown_task_does_not_crash(two_sessions):
    """设备报了个库里没有的 task_no：只广播、不落库、不能抛异常。"""
    _, b = two_sessions
    out = command.handle_ack(b, {"task_id": "task-19700101-9999", "device_id": ACT, "stage": "finished"})
    assert out["status"] == "success"
    assert out["task_no"] == "task-19700101-9999"


# ---------------------------------------------------------------- 模拟器 → 后端 端到端
@pytest.fixture()
def scoped(tmp_path, monkeypatch):
    """把 mqtt_client 的 `session_scope` 换成本地 SQLite，模拟 paho 线程自己开事务。"""
    from contextlib import contextmanager

    url = f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}"
    engine = create_engine(url, future=True)
    _sqlite_metadata().create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @contextmanager
    def scope():
        db = Session()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    import app.core.mqtt_client as mc

    monkeypatch.setattr(mc, "session_scope", scope)
    monkeypatch.setattr(mc, "_local_dispatchers", [])  # 防止别的用例残留接收方
    try:
        yield Session
    finally:
        engine.dispose()


def test_mock_ack_reaches_success_without_broker(scoped):
    """模拟器发 finished ack → 后端 tasks 表流转到 success，全程没有 MQTT broker。

    这条同时守两件事：
    1) `send_cmd` 的 commit 时机（ack 线程是另一个 session）；
    2) broker 不可用时 ack 走进程内回灌——`publish()` 的降级分支必须把上行主题
       回喂给 `_dispatch_inbound`，否则 ack 直接消失，任务停在 timeout。
    """
    from app.core import mqtt_client
    from app.mock.simulator import simulator

    assert mqtt_client.is_connected() is False, "本用例要求 broker 不可用"

    db = scoped()
    result = command.send_cmd(db, ACT, "pump", {"duration_s": 1}, issued_by="agent:executor")
    task_no = result["task_no"]

    simulator._send_ack(ACT, result["msg_id"], task_no, "finished", "done", {"executed_s": 1})

    db.expire_all()
    task = db.scalar(select(Task).where(Task.task_no == task_no))
    assert task is not None
    assert task.status == "success", f"ack 没落库，任务停在 {task.status}"
    assert task.result_json["detail"]["executed_s"] == 1

