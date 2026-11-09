"""运行期配置（settings 表）读写 + 缓存 + 变更广播。

为什么单独一个模块：`config.py` 只能读 .env（启动前连不上库），
而 mode / 阈值 / 调度参数是**运行期**要改的，必须走表 + 缓存。

缓存策略：每个 key 单独缓存在 Redis（TTL 10s），写入时立刻失效，
所以设置页点一下「切 Real」，下一轮读取就是新值——演示不能有延迟。
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select

from ..db import session_scope
from ..models.settings import Setting
from .crypto import decrypt, encrypt
from .redis_client import Keys, get_redis

CACHE_TTL_S = 10
SECRET_KEYS = {"llm_api_key"}

# 表里读不到、Redis 也挂了的最后兜底（保证平台永远能起）
FALLBACK: dict[str, Any] = {
    "mode": "mock",
    "llm_provider": "glm",
    "irrigation_default_range": [55, 65],
    "schedule_cron": "0 */2 * * *",
    "parallel_enabled": True,
    "max_retries": 3,
    "weather_scenario": "sunny",
    "mock_dry_rate_per_min": 0.05,
    "mock_pump_gain_per_s": 0.35,
}


def _cache_set(key: str, value: Any) -> None:
    import json

    try:
        get_redis().set(Keys.runtime_settings(key), json.dumps(value, ensure_ascii=False), ex=CACHE_TTL_S)
    except Exception:  # pragma: no cover
        pass


def _cache_get(key: str) -> tuple[bool, Any]:
    import json

    try:
        raw = get_redis().get(Keys.runtime_settings(key))
    except Exception:  # pragma: no cover
        return False, None
    if raw is None:
        return False, None
    try:
        return True, json.loads(raw)
    except Exception:  # pragma: no cover
        return False, None


def _cache_drop(key: str | None = None) -> None:
    try:
        if key is None:
            for k in get_redis().scan_iter(f"{Keys.PREFIX}:settings:*"):
                get_redis().delete(k)
        else:
            get_redis().delete(Keys.runtime_settings(key))
    except Exception:  # pragma: no cover
        pass


def get_value(key: str, default: Any = None) -> Any:
    """读一个配置项（带缓存）。"""
    hit, cached = _cache_get(key)
    if hit:
        return cached
    try:
        with session_scope() as db:
            row = db.scalar(select(Setting).where(Setting.key == key))
            value = row.value if row is not None else FALLBACK.get(key, default)
    except Exception as exc:  # pragma: no cover - 库不可用
        logger.warning("读配置 {} 失败，用兜底值：{}", key, exc)
        value = FALLBACK.get(key, default)
    _cache_set(key, value)
    return value


def get_secret(key: str) -> str:
    """读敏感配置（解密后的明文），只给后端内部用。"""
    raw = get_value(key, "")
    return decrypt(raw if isinstance(raw, str) else "")


def get_all(mask_secrets: bool = True) -> dict[str, Any]:
    """给 GET /api/settings 用。"""
    with session_scope() as db:
        rows = db.scalars(select(Setting).order_by(Setting.key)).all()
        out: dict[str, Any] = {}
        for row in rows:
            if mask_secrets and row.key in SECRET_KEYS:
                from .crypto import mask

                out[row.key] = mask(decrypt(row.value if isinstance(row.value, str) else ""))
                continue
            out[row.key] = row.value
    return out


def describe_all() -> list[dict[str, Any]]:
    """带说明的扁平列表，设置页直接用。"""
    from .crypto import mask

    with session_scope() as db:
        rows = db.scalars(select(Setting).order_by(Setting.key)).all()
        return [
            {
                "key": row.key,
                "value": mask(decrypt(row.value)) if row.key in SECRET_KEYS and isinstance(row.value, str) else row.value,
                "description": row.description,
            }
            for row in rows
        ]


def set_many(values: dict[str, Any]) -> dict[str, Any]:
    """批量写配置：落库 → 失效缓存 → 返回变更后的全量（脱敏）。

    mode 变更由调用方（api/settings.py）额外广播 mode_changed，
    避免本模块依赖 WS 管理器造成循环引用。
    """
    changed: list[str] = []
    with session_scope() as db:
        for key, value in values.items():
            if key in SECRET_KEYS and isinstance(value, str) and value:
                value = encrypt(value)
            row = db.scalar(select(Setting).where(Setting.key == key))
            if row is None:
                db.add(Setting(key=key, value=value, description="运行期新增"))
            else:
                if row.value == value:
                    continue
                row.value = value
            changed.append(key)
    _cache_drop()
    if changed:
        logger.info("运行期配置已更新：{}", ", ".join(changed))
    return get_all()


def get_mode() -> str:
    mode = str(get_value("mode", "mock")).lower()
    return mode if mode in {"mock", "real"} else "mock"
