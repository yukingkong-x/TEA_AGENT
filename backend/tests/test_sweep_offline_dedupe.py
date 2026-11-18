"""离线巡检收敛规则测试（大屏告警条改造）。

守的是一次已经发生的现场事故：真机演示期间大屏顶部攒了 70+ 条未确认告警——
同设备每隔一阵就重复报一次离线、已停用的 mock 设备也在报"离线"、设备恢复后
旧的离线告警还挂在那里等人点确认。

三条收敛规则（与 registry.sweep_offline 文档一一对应）：
1. 同一台设备只保留一条**未确认**的离线报警；
2. mock-* 设备只同步在线状态，不产生告警；
3. 设备恢复在线时自动确认它的历史离线报警。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.devices import registry  # noqa: E402
from app.models.alerts import Alert  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.devices import Device  # noqa: E402

class FakeRedis:
    """只实现 sweep_offline 用到的 set(nx=True) / delete，语义与真 Redis 一致。"""

    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """SQLite 里放一真一 mock 两台设备，Redis / WS 打桩。

    alerts 表用裸 DDL 建：SQLite 里 `BIGINT PRIMARY KEY` 不会自动行别名，
    而 sweep_offline 是不带 id 插入的，必须换成 `INTEGER PRIMARY KEY AUTOINCREMENT`。
    """
    url = f"sqlite:///{(tmp_path / 'dev.db').as_posix()}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(bind=engine, tables=[Device.__table__])
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level VARCHAR(8) NOT NULL,
                source VARCHAR(64),
                message VARCHAR(255),
                acknowledged BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    session.add_all(
        [
            Device(id=1, device_id="esp32-soil-02", name="土壤墒情节点", role="soil", is_mock=False),
            Device(id=2, device_id="mock-esp32-soil-02", name="模拟土壤", role="soil", is_mock=True),
        ]
    )
    session.commit()

    monkeypatch.setattr(registry, "get_last_seen", lambda _device_id: None)
    monkeypatch.setattr(registry, "get_redis", FakeRedis)
    monkeypatch.setattr(registry.manager, "publish_threadsafe", lambda *_a, **_k: None)
    try:
        yield session
    finally:
        session.close()


def _sweep(db, last_seen_s):
    monkey_last = {d.device_id: last_seen_s for d in db.scalars(select(Device)).all()}
    registry.get_last_seen = lambda device_id: monkey_last.get(device_id)  # type: ignore
    return registry.sweep_offline(db)


def test_mock_device_never_raises_alert(db):
    """mock 设备心跳过期：只置离线，不写 alerts；真机同样过期则照常报。"""
    events = _sweep(db, time.time() - 600)
    assert [e["source"] for e in events] == ["device:esp32-soil-02"]
    sources = {s for (s,) in db.execute(select(Alert.source)).all()}
    assert "device:mock-esp32-soil-02" not in sources
    assert "device:esp32-soil-02" in sources
    states = {s["device_id"]: s for s in registry.list_states(db)}
    assert states["mock-esp32-soil-02"]["online"] is False
    assert states["esp32-soil-02"]["online"] is False


def test_duplicate_offline_alert_suppressed_while_unacked(db):
    """同设备已有未确认离线告警：即使 Redis 标记过期也不重复报。"""
    _sweep(db, time.time() - 600)
    first = db.scalar(select(Alert).where(Alert.source == "device:esp32-soil-02"))
    assert first is not None

    # 模拟 Redis 标记过期（ex=3600 到点）后下一轮巡检
    db.get_bind()
    registry.get_redis().store.clear()
    events = _sweep(db, time.time() - 900)
    assert events == []
    count = len(db.scalars(select(Alert).where(Alert.source == "device:esp32-soil-02")).all())
    assert count == 1


def test_reack_allowed_after_manual_ack(db):
    """人工确认过之后才允许再次报警——收敛不等于吞掉故障。"""
    _sweep(db, time.time() - 600)
    first = db.scalar(select(Alert).where(Alert.source == "device:esp32-soil-02"))
    first.acknowledged = True
    db.commit()

    registry.get_redis().store.clear()
    events = _sweep(db, time.time() - 900)
    assert len(events) == 1
    assert events[0]["source"] == "device:esp32-soil-02"


def test_recovery_auto_acks_offline_alerts(db):
    """设备恢复在线：历史离线告警自动置为已确认，不再等人点。"""
    _sweep(db, time.time() - 600)
    assert db.scalar(select(Alert).where(Alert.acknowledged.is_(False))) is not None

    events = _sweep(db, time.time() - 10)  # 心跳新鲜 → 在线
    assert events == []
    pending = db.scalars(select(Alert).where(Alert.acknowledged.is_(False))).all()
    assert pending == []
    states = {s["device_id"]: s for s in registry.list_states(db)}
    assert states["esp32-soil-02"]["online"] is True
