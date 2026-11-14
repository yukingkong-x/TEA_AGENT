"""平台事实注入:把「真实设备清单」告诉 Agent,免得它把地点名当 device_id。

实测(2026-11-14 run #8,真模型 glm-4-flash):
    scout 调 get_env_status({"device_id": "A区茶垄"}) → 工具报「设备 A区茶垄 不存在」
    soil/pest 同错 → 三方都说「设备信息缺失」→ decision 判 none → 一个任务没建。
工具没写错,是 Agent 手里没有事实:它不知道该填 `mock-esp32-soil-02`。

所以每次 run 由接线层取一次设备清单,拼成短文本塞进 system prompt。
刻意做得轻:一次 SELECT、15 秒进程内缓存、取不到就返回空串(不让演示因为查库失败而崩)。
"""
from __future__ import annotations

import time
from typing import Optional

CACHE_TTL_S = 15.0
_cache: tuple[float, str] = (0.0, "")

ROLE_LABEL = {"field": "巡园终端", "soil": "土壤探头", "actuator": "执行终端"}


def _mode_name() -> str:
    try:
        from app.core import runtime_settings

        return str(runtime_settings.get_mode() or "")
    except Exception:  # noqa: BLE001 基座未合入时不影响注入
        return ""


_ids_cache: tuple[float, dict[str, str]] = (0.0, {})


def device_ids() -> dict[str, str]:
    """role → 设备 id（同批次优先，取 id 最小的那台）。

    引擎补建任务时要知道「下发给谁」：payload 里没 device_id，create_task 就只能落一张
    没有归属的空单。这里按 mock/真机批次给出执行终端与土壤探头的 id。
    """
    global _ids_cache
    now = time.monotonic()
    if _ids_cache[0] and now - _ids_cache[0] < CACHE_TTL_S:
        return dict(_ids_cache[1])

    try:
        from sqlalchemy import select

        from app.core import runtime_settings
        from app.db import session_scope
        from app.models.devices import Device

        is_mock = str(runtime_settings.get_mode() or "mock") != "real"
        with session_scope() as db:
            rows = db.execute(
                select(Device.device_id, Device.role, Device.is_mock).order_by(Device.id)
            ).all()
    except Exception:  # noqa: BLE001
        return {}

    picked: dict[str, str] = {}
    for device_id, role, mock in rows:
        if bool(mock) == is_mock and role not in picked:
            picked[str(role)] = str(device_id)
    _ids_cache = (now, picked)
    return dict(picked)


def format_roster(rows: list[tuple], mode: str = "") -> str:
    """把设备行拼成注入文本(纯函数,便于单测)。

    rows: [(device_id, name, role, location, online), ...]
    """
    if not rows:
        return ""
    lines = ["【设备事实】平台已登记设备（device_id｜角色｜位置｜在线）："]
    for device_id, name, role, location, online in rows:
        lines.append(
            f"- {device_id}｜{ROLE_LABEL.get(role, role)}｜{location or '未知位置'}"
            f"｜{'在线' if online else '离线'}｜{name}"
        )
    lines.append(
        "调用工具时 device_id 只能填上面第一列的 id（例如 mock-esp32-soil-02），"
        "**不要填「A区茶垄」这类地点名，也不要自己拼 id**；"
        "查墒情请用 role=土壤探头 的那台，下发指令请用 role=执行终端 的那台。"
    )
    if mode:
        lines.append(f"当前模式：{mode}。")
    return "\n".join(lines)


def device_roster_text(force: bool = False) -> str:
    """返回「设备事实」文本;拿不到设备表时返回空串(调用方据此跳过注入)。"""
    global _cache
    now = time.monotonic()
    if not force and _cache[0] and now - _cache[0] < CACHE_TTL_S:
        return _cache[1]

    try:
        from sqlalchemy import select

        from app.db import session_scope
        from app.models.devices import Device

        with session_scope() as db:
            rows = db.execute(
                select(Device.device_id, Device.name, Device.role, Device.location, Device.online)
                .order_by(Device.is_mock, Device.id)
            ).all()
    except Exception:  # noqa: BLE001 没有基座/表未建,静默跳过注入
        return ""

    text = format_roster([tuple(r) for r in rows], _mode_name())
    if text:
        _cache = (now, text)
    return text


def reset_cache() -> None:
    """测试用:清缓存。"""
    global _cache
    _cache = (0.0, "")
