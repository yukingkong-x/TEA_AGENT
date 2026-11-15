"""设备列表口径测试（PRD 3.1：契约默认值变更必须走 issue，不能悄悄变）。

这条测试守的是一次已经发生的回归：曾经把 `is_mock=None` 改成「按当前运行模式过滤」，
结果 Mock 演示时 3 台真机被滤掉、Real 模式下模拟器设备被滤掉，而演示现场常常两者
同时在跑（真板子在烧、模拟器也开着），两个方向都在丢信息；前端大屏也是照「6 台」写的。

现在定死：缺省 = 全量，只有显式传 true/false 才过滤。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.devices import registry  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.devices import Device  # noqa: E402

TABLES = [Device.__table__]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """SQLite 里放两台设备（一真一 mock）。online 状态走 Redis，这里直接打桩。"""
    url = f"sqlite:///{(tmp_path / 'dev.db').as_posix()}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(bind=engine, tables=TABLES)
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    # SQLite 的 BigInteger 主键不自增，显式给 id
    session.add_all(
        [
            Device(id=1, device_id="k10-field-01", name="田间 K10", role="field", is_mock=False),
            Device(id=2, device_id="mock-k10-field-01", name="模拟 K10", role="field", is_mock=True),
        ]
    )
    session.commit()
    monkeypatch.setattr(registry, "get_last_seen", lambda _device_id: None)
    try:
        yield session
    finally:
        session.close()


def test_default_returns_all_devices(db):
    """缺省必须全量——不按当前 mode 过滤。"""
    states = registry.list_states(db)
    assert {s["device_id"] for s in states} == {"k10-field-01", "mock-k10-field-01"}


def test_explicit_true_returns_only_mock(db):
    states = registry.list_states(db, is_mock=True)
    assert [s["device_id"] for s in states] == ["mock-k10-field-01"]
    assert all(s["is_mock"] for s in states)


def test_explicit_false_returns_only_real(db):
    states = registry.list_states(db, is_mock=False)
    assert [s["device_id"] for s in states] == ["k10-field-01"]
    assert all(not s["is_mock"] for s in states)
