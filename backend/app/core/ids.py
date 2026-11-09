"""业务 ID 生成：task-20261109-0007 / cmd-20261109-0001（PRD 6.6 / 5.3 的编号样式）。

用 Redis INCR 保证全局唯一且按天归零；Redis 不可用时退回时间戳+随机后缀。
"""
from __future__ import annotations

import random
import time
from datetime import datetime

from loguru import logger

from .redis_client import get_redis


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def next_serial(name: str, width: int = 4) -> str:
    """name: task / cmd / msg / run，返回 `{name}-{yyyymmdd}-{序号}`。"""
    day = _today()
    key = f"tea:seq:{name}:{day}"
    try:
        n = int(get_redis().incr(key))
        # 两天后自动过期，避免 key 堆积
        get_redis().expire(key, 172800)
        return f"{name}-{day}-{n:0{width}d}"
    except Exception as exc:  # pragma: no cover - Redis 不可用
        logger.warning("序列号生成降级（Redis 不可用）：{}", exc)
        return f"{name}-{day}-{int(time.time() * 1000) % 100000:0{width}d}{random.randint(0, 9)}"


def new_task_no() -> str:
    return next_serial("task")


def new_msg_id() -> str:
    return next_serial("cmd")


def new_run_no() -> str:
    return next_serial("run")
