"""把 Agent 花名册同步进 `agents` 表（PRD 6.3 / REQ-F-002 的种子半）。

为什么不写死一份配置：提示词正本是队长的 `app/agents/prompts.py`（`AGENT_SPECS` +
`to_db_rows()`）。基座只负责把它落进表，改提示词仍然只改那一个文件。

为什么必须做：`GET /api/agents` 返回空数组 → 设置页 7 个 Agent 卡片全空，前端只能拿
本地样例兜底（队友A 反馈）。而 `AgentRunner` 每轮都读表，表空意味着设置页改的温度 /
启停开关根本无处可存。

三条硬规则：
1. **只补不缺，不覆盖**：已存在的 agent_key 一律跳过。用户在设置页改过的提示词、关掉的
   开关、调过的温度，不能被一次重启冲掉。
2. **tools_json 必须转成 list**：`to_db_rows()` 给的是 `json.dumps(spec.tools)` 字符串，
   而列类型是 JSON。原样写进去会存成「一个字符串」，接口返回 `"[\\"get_env_status\\"]"`
   这种东西，前端的 `tools_json.map(...)` 直接炸。
3. **失败不影响启动**：队长模块缺失（未合入 / 目录被清）时返回空结果并 debug 日志。
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.agents import Agent


def _rows_from_prompts() -> list[dict[str, Any]]:
    try:
        from ..agents.prompts import to_db_rows
    except Exception as exc:  # noqa: BLE001 队长模块未合入时静默
        logger.debug("Agent 花名册不可用（跳过 agents 种子）：{}", exc)
        return []
    try:
        rows = to_db_rows()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Agent 花名册读取失败（跳过 agents 种子）：{}", exc)
        return []
    return list(rows or [])


def _normalize_tools(value: Any) -> Any:
    """`tools_json` 统一成 list；字符串按 JSON 解析，解析不了就当空。"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def sync_agents(db: Session) -> int:
    """补齐 agents 表缺失的行，返回新增条数（已存在的行一律不动）。"""
    rows = _rows_from_prompts()
    if not rows:
        return 0
    existing = set(db.scalars(select(Agent.agent_key)).all())
    added = 0
    for row in rows:
        agent_key = row.get("agent_key")
        if not agent_key or agent_key in existing:
            continue
        temperature = row.get("temperature")
        db.add(
            Agent(
                agent_key=agent_key,
                name=row.get("name") or agent_key,
                avatar=row.get("avatar"),
                system_prompt=row.get("system_prompt"),
                tools_json=_normalize_tools(row.get("tools_json") or row.get("tools")),
                model=row.get("model"),
                temperature=Decimal(str(temperature if temperature is not None else 0.3)),
                enabled=bool(row.get("enabled", True)),
            )
        )
        existing.add(agent_key)
        added += 1
    if added:
        db.flush()
        logger.info("Agent 种子：新增 {} 个 Agent（{}）", added, ", ".join(sorted(existing)[:8]))
    return added
