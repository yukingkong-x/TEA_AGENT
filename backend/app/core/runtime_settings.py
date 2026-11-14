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
from .crypto import PREFIX as ENC_PREFIX
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


SECRET_ACTION_WRITE = "write"
SECRET_ACTION_CLEAR = "clear"
SECRET_ACTION_SKIP = "skip"


def _secret_action(key: str, value: Any) -> str:
    """敏感字段该做什么：`write`（加密落库）/ `clear`（清空）/ `skip`（保留原值）。

    三态由**前端语义**决定，缺一不可：

    | 收到 | 动作 | 场景 |
    | --- | --- | --- |
    | `null` | `clear` | 用户点「清除 Key」，前后端约定用 null 表达「显式清空」 |
    | `""` / 纯空白 | `skip` | 设置页整表 PUT 时没填的字段——**不能当成清空**，否则改个阈值就把 Key 抹了 |
    | 含 `*` / 以 `enc:` 开头 | `skip` | `GET /api/settings` 回传的掩码或已加密值，再加密一次就 401 |

    `null` 与 `""` 必须分开：整表 PUT 里没填的输入框天然就是 `""`，
    把 `""` 当清空会让「改个灌溉区间」顺手删掉 LLM Key，而症状是隔天才发现所有
    Agent 静默降级。显式清空用 `null`，是可被测试钉住的强语义。
    """
    if key not in SECRET_KEYS:
        return SECRET_ACTION_WRITE
    if value is None:
        return SECRET_ACTION_CLEAR
    if not isinstance(value, str) or not value.strip():
        return SECRET_ACTION_SKIP
    if "*" in value or value.startswith(ENC_PREFIX):
        return SECRET_ACTION_SKIP
    return SECRET_ACTION_WRITE


def set_many(values: dict[str, Any]) -> dict[str, Any]:
    """批量写配置：落库 → 失效缓存 → 返回变更后的全量（脱敏）。

    mode 变更由调用方（api/settings.py）额外广播 mode_changed，
    避免本模块依赖 WS 管理器造成循环引用。

    敏感字段（SECRET_KEYS）走 `_secret_action` 三态判定（见其 docstring）。
    命中 `skip` 只记 warning 并跳过该项，不抛异常——设置页不该因一个字段整体失败。
    """
    changed: list[str] = []
    skipped: list[str] = []
    cleared: list[str] = []
    with session_scope() as db:
        for key, value in values.items():
            action = _secret_action(key, value)
            if action == SECRET_ACTION_SKIP:
                logger.warning(
                    "跳过敏感配置 {} 的写入（收到 {!r}）：空串视为未填写，掩码/密文视为前端回传，均保留库中原值",
                    key,
                    str(value)[:12],
                )
                skipped.append(key)
                continue
            if action == SECRET_ACTION_CLEAR:
                # 落明文空串而不是加密空串：`decrypt("")` 与 `mask("")` 都返回 ""，
                # GET /api/settings 于是显示空输入框 = 「确实没有 Key」，读侧无需特判。
                value = ""
                cleared.append(key)
            elif key in SECRET_KEYS:
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
    if cleared:
        logger.warning("敏感配置已被清空：{}（LLM 将走规则降级）", ", ".join(cleared))
    if skipped:
        logger.info("运行期配置已跳过：{}", ", ".join(skipped))
    return get_all()


def get_mode() -> str:
    mode = str(get_value("mode", "mock")).lower()
    return mode if mode in {"mock", "real"} else "mock"
