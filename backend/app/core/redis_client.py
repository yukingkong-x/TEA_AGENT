"""Redis 封装（PRD 3.2：缓存/队列/实时状态）。

统一 key 命名，避免四个人各写一套。同步客户端，paho 回调线程与 FastAPI 线程池共用。
"""
from __future__ import annotations

import time
from typing import Optional

import redis
from loguru import logger

from ..config import get_settings

settings = get_settings()

_pool: Optional[redis.ConnectionPool] = None
_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """懒加载单例（decode_responses=True，取出来就是 str）。"""
    global _pool, _client
    if _client is None:
        _pool = redis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=32,
            socket_timeout=3,
            socket_connect_timeout=3,
            health_check_interval=30,
        )
        _client = redis.Redis(connection_pool=_pool)
    return _client


def ping() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception as exc:  # pragma: no cover - 依赖真实 Redis
        logger.warning("Redis 探活失败：{}", exc)
        return False


def close() -> None:
    global _client, _pool
    if _client is not None:
        try:
            _client.close()
        except Exception:  # pragma: no cover
            pass
    if _pool is not None:
        _pool.disconnect()
    _client = None
    _pool = None


class Keys:
    """全部 Redis key 的唯一出口（改前缀只改这里）。"""

    PREFIX = "tea"

    @classmethod
    def device_last_seen(cls, device_id: str) -> str:
        return f"{cls.PREFIX}:device:{device_id}:last_seen"

    @classmethod
    def device_alerted(cls, device_id: str) -> str:
        """离线报警去重标记，避免 45s 一轮刷屏。"""
        return f"{cls.PREFIX}:device:{device_id}:offline_alerted"

    @classmethod
    def dedup_seq(cls, device_id: str, seq: int | str, boot_id: str | None = None) -> str:
        # seq 在设备/模拟器重启后会归零重计，键里必须带 boot_id（本次开机的随机标识），
        # 否则重启后 1 小时内的遥测全被当成重复丢掉（真机重启同样会踩）
        if boot_id:
            return f"{cls.PREFIX}:dedup:seq:{device_id}:{boot_id}:{seq}"
        return f"{cls.PREFIX}:dedup:seq:{device_id}:{seq}"

    @classmethod
    def dedup_msg(cls, msg_id: str) -> str:
        return f"{cls.PREFIX}:dedup:msg:{msg_id}"

    @classmethod
    def ack_wait(cls, msg_id: str) -> str:
        """待收回执的指令：value = 执行超时时间戳。"""
        return f"{cls.PREFIX}:ack:wait:{msg_id}"

    @classmethod
    def runtime_settings(cls, key: str) -> str:
        return f"{cls.PREFIX}:settings:{key}"

    @classmethod
    def weather_scenario(cls) -> str:
        return f"{cls.PREFIX}:mock:weather"


def mark_once(key: str, ttl_s: int = 600) -> bool:
    """幂等去重：第一次见到返回 True，重复消息返回 False。

    Redis 不可用时降级为「永远 True」——宁可重复入库，也不能丢数据。
    """
    try:
        return bool(get_redis().set(key, int(time.time()), nx=True, ex=ttl_s))
    except Exception as exc:  # pragma: no cover
        logger.warning("幂等去重降级（Redis 不可用）：{}", exc)
        return True


def touch_last_seen(device_id: str, ts: float | None = None) -> None:
    try:
        get_redis().set(Keys.device_last_seen(device_id), ts or time.time())
    except Exception as exc:  # pragma: no cover
        logger.warning("写 last_seen 失败 {}: {}", device_id, exc)


def get_last_seen(device_id: str) -> float | None:
    try:
        raw = get_redis().get(Keys.device_last_seen(device_id))
        return float(raw) if raw else None
    except Exception:  # pragma: no cover
        return None
