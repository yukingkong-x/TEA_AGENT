"""agents 表种子：`GET /api/agents` 从返回 `[]` 变成 7 张卡片。

两个必须守住的点：
1. tools_json 落库是 list（`to_db_rows()` 给的是 json 字符串，列类型是 JSON）；
2. 只补不缺——设置页改过的提示词/开关/温度不能被一次重启冲掉。
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import agent_seed  # noqa: E402
from app.models.agents import Agent  # noqa: E402

ROWS = [
    {
        "agent_key": "scout",
        "name": "巡园管家",
        "avatar": "🌿",
        "system_prompt": "你是巡园管家",
        "tools_json": json.dumps(["get_env_status", "get_soil_status"], ensure_ascii=False),
        "model": None,
        "temperature": 0.3,
        "enabled": True,
    },
    {
        "agent_key": "decision",
        "name": "决策官",
        "avatar": "🎯",
        "system_prompt": "你是决策官",
        "tools_json": json.dumps(["create_task"]),
        "model": None,
        "temperature": 0.2,
        "enabled": True,
    },
]


def _metadata() -> MetaData:
    md = MetaData()
    Agent.__table__.to_metadata(md)
    for table in md.tables.values():
        if "id" in table.c:
            table.c.id.type = Integer()
    return md


def _maker(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'agents.db').as_posix()}", future=True)
    _metadata().create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def test_seeds_all_rows_and_parses_tools(tmp_path, monkeypatch):
    maker = _maker(tmp_path)
    monkeypatch.setattr(agent_seed, "_rows_from_prompts", lambda: ROWS)
    with maker() as db:
        assert agent_seed.sync_agents(db) == 2
        db.commit()
    with maker() as db:
        rows = {a.agent_key: a for a in db.scalars(select(Agent)).all()}
    assert set(rows) == {"scout", "decision"}
    # 关键：落库是 list，不是 "\"[\\\"get_env_status\\\"]\"" 这种字符串
    assert rows["scout"].tools_json == ["get_env_status", "get_soil_status"]
    assert rows["decision"].tools_json == ["create_task"]
    assert float(rows["decision"].temperature) == 0.2


def test_second_run_adds_nothing(tmp_path, monkeypatch):
    maker = _maker(tmp_path)
    monkeypatch.setattr(agent_seed, "_rows_from_prompts", lambda: ROWS)
    with maker() as db:
        agent_seed.sync_agents(db)
        db.commit()
    with maker() as db:
        assert agent_seed.sync_agents(db) == 0


def test_does_not_overwrite_user_edits(tmp_path, monkeypatch):
    """设置页改过提示词/关掉开关之后再重启，改动必须留着。"""
    maker = _maker(tmp_path)
    monkeypatch.setattr(agent_seed, "_rows_from_prompts", lambda: ROWS)
    with maker() as db:
        agent_seed.sync_agents(db)
        db.commit()
    with maker() as db:
        scout = db.scalar(select(Agent).where(Agent.agent_key == "scout"))
        scout.system_prompt = "我改过的提示词"
        scout.enabled = False
        scout.temperature = 0.9
        db.commit()
    with maker() as db:
        assert agent_seed.sync_agents(db) == 0
        db.commit()
    with maker() as db:
        scout = db.scalar(select(Agent).where(Agent.agent_key == "scout"))
    assert scout.system_prompt == "我改过的提示词"
    assert scout.enabled is False
    assert float(scout.temperature) == 0.9


def test_missing_roster_is_silent(tmp_path, monkeypatch):
    """队长模块没合入时（ImportError）不能拖垮启动。"""
    maker = _maker(tmp_path)
    monkeypatch.setattr(agent_seed, "_rows_from_prompts", lambda: [])
    with maker() as db:
        assert agent_seed.sync_agents(db) == 0
