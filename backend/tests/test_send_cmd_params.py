"""下发参数以任务载荷为准（载荷 19.9、调用方 45 的事故钉子）。

现场（2026-11-14）：Self-Loop 修正任务按缺口算出 `duration_s=20` 写进载荷，
执行管家按提示词传 45，`send_cmd` 用了调用方那个 → 实浇 45 秒。多浇 25 秒白费水是
小事，验证时湿度涨得更多、达成率反而"更漂亮"，等于用错数据奖励自己。

修法：`_merge_task_params` 让**载荷里的键一律优先**，调用方只补载荷缺的键。这样不用
在每个调用方各写一遍兜底，以后新写的入口也自动正确。

顺带钉住同源问题：同一张单换设备会让复测去查另一台传感器，验证结论莫名其妙，
所以载荷里的 device_id 也优先。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models  # noqa: E402,F401  触发全部表注册
from app.core import ids  # noqa: E402
from app.devices import command  # noqa: E402
from app.models.devices import Device  # noqa: E402
from app.models.task_events import TaskEvent  # noqa: E402
from app.models.tasks import Task  # noqa: E402

ACT = "k10-act-03"
ACT2 = "k10-act-04"
TABLES = [Device.__table__, Task.__table__, TaskEvent.__table__]


def _metadata() -> MetaData:
    md = MetaData()
    for table in TABLES:
        table.to_metadata(md)
    for table in md.tables.values():
        if "id" in table.c:
            table.c.id.type = Integer()
    return md


@pytest.fixture()
def sent(monkeypatch):
    """拦下发：捕获真正发出去的 MQTT 载荷（含 params）。"""
    import app.core.mqtt_client as mc

    captured: list[dict] = []

    def fake_publish(topic, payload, **kwargs):
        captured.append({"topic": topic, "payload": payload})
        return True

    monkeypatch.setattr(mc, "publish", fake_publish)
    return captured


@pytest.fixture()
def db(tmp_path, monkeypatch, sent):
    def boom():
        raise RuntimeError("redis disabled in this test")

    monkeypatch.setattr(command, "get_redis", boom)
    monkeypatch.setattr(ids, "get_redis", boom)

    # get_mode 会读 settings 表（走真实的全局 engine，宿主机上解析容器服务名要等 DNS
    # 超时，每个用例白等 8 秒）。本文件不关心 mock/real 的差异，直接钉成 mock。
    import app.core.runtime_settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "get_mode", lambda: "mock")

    engine = create_engine(f"sqlite:///{(tmp_path / 'params.db').as_posix()}", future=True)
    _metadata().create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    session.add_all([
        Device(device_id=ACT, name="执行终端", role="actuator", is_mock=True, online=True),
        Device(device_id=ACT2, name="备用终端", role="actuator", is_mock=True, online=True),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _make_task(db, params=None, device_id=ACT, status="pending") -> str:
    task_no = ids.new_task_no()
    db.add(
        Task(
            task_no=task_no,
            type="device_cmd",
            payload_json={"device_id": device_id, "action": "pump", "params": params or {}},
            priority=9,
            status=status,
        )
    )
    db.commit()
    return task_no


def _last_pump_params(sent) -> dict:
    pumps = [item["payload"] for item in sent if item["payload"].get("action") == "pump"]
    assert pumps, "没有捕获到 pump 指令"
    return pumps[-1]["params"]


def test_task_payload_wins_over_caller(db, sent):
    task_no = _make_task(db, {"duration_s": 20})
    command.send_cmd(db, ACT, "pump", {"duration_s": 45}, issued_by="agent:executor", task_no=task_no)
    assert _last_pump_params(sent)["duration_s"] == 20, "调用方把载荷里的时长盖掉了"


def test_caller_only_fills_missing_keys(db, sent):
    task_no = _make_task(db, {"duration_s": 20})
    command.send_cmd(
        db, ACT, "pump", {"duration_s": 45, "note": "补灌"}, issued_by="agent:executor", task_no=task_no
    )
    params = _last_pump_params(sent)
    assert params["duration_s"] == 20   # 载荷有的键：载荷优先
    assert params["note"] == "补灌"      # 载荷没有的键：调用方补


def test_new_task_uses_caller_params(db, sent):
    """没有 task_no（新建单）时，调用方就是唯一来源，不能被"载荷优先"误伤成 0。"""
    command.send_cmd(db, ACT, "pump", {"duration_s": 45}, issued_by="agent:executor")
    assert _last_pump_params(sent)["duration_s"] == 45


def test_clamp_still_applies_to_task_payload(db, sent):
    """载荷优先不等于跳过保护：载荷写 500 一样要被截到 120。"""
    task_no = _make_task(db, {"duration_s": 500})
    command.send_cmd(db, ACT, "pump", {"duration_s": 30}, issued_by="agent:executor", task_no=task_no)
    assert _last_pump_params(sent)["duration_s"] == command.MAX_PUMP_DURATION_S


def test_clamped_value_is_written_back(db, sent):
    """截断结果回写载荷：下次复用同一张单不该又按 500 算，轨迹也对不上。"""
    task_no = _make_task(db, {"duration_s": 500})
    command.send_cmd(db, ACT, "pump", {"duration_s": 30}, issued_by="agent:executor", task_no=task_no)
    db.expire_all()
    task = db.scalar(select(Task).where(Task.task_no == task_no))
    assert task.payload_json["params"]["duration_s"] == command.MAX_PUMP_DURATION_S


def test_task_device_wins_over_caller(db, sent):
    """同一张单换设备会让复测去查另一台传感器，所以载荷里的 device 也优先。"""
    task_no = _make_task(db, {"duration_s": 20}, device_id=ACT2)
    command.send_cmd(db, ACT, "pump", {"duration_s": 20}, issued_by="agent:executor", task_no=task_no)
    topped = [item["payload"] for item in sent if item["payload"].get("task_id") == task_no]
    assert topped, "没捕获到带 task_id 的指令"
    assert topped[-1]["params"]["duration_s"] == 20
    db.expire_all()
    task = db.scalar(select(Task).where(Task.task_no == task_no))
    assert task.assigned_device == ACT2


def test_dispatch_trail_records_param_source(db, sent):
    """轨迹写清这次是载荷值还是调用方值、盖掉了哪些键 —— 事后对账靠它。"""
    task_no = _make_task(db, {"duration_s": 20})
    command.send_cmd(db, ACT, "pump", {"duration_s": 45}, issued_by="agent:executor", task_no=task_no)
    db.expire_all()
    rows = db.scalars(select(TaskEvent).where(TaskEvent.task_no == task_no)).all()
    dispatch = [row for row in rows if row.event == "dispatch"]
    assert dispatch, "没有写 dispatch 轨迹"
    payload = dispatch[-1].payload_json
    assert payload["params_source"] == "task"
    assert payload["overridden"] == ["duration_s"]
    assert payload["params"]["duration_s"] == 20
