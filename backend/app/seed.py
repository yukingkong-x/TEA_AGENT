"""首启种子数据（PRD 17.1：REQ-O-001 的「设备种子半」归队友 B）。

- 3 台真实设备（PRD 4.1）：k10-field-01 / esp32-soil-02 / k10-act-03
- settings 默认键值（PRD 6.14）
- **不写** agents / workflows 表：那两块的种子是队长的（提示词见 app/agents/prompts.py）

全部幂等：只补缺失项，不覆盖用户/队长改过的值。
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models.devices import Device
from .models.settings import Setting

# ---------------------------------------------------------------- 设备（PRD 4.1）
DEFAULT_DEVICES: list[dict[str, Any]] = [
    {
        "device_id": "k10-field-01",
        "name": "巡园员一号",
        "role": "field",
        "location": "A 区茶垄东段",
        "is_mock": False,
        "config_json": {"telemetry_interval_s": 30, "status_interval_s": 15, "board": "K10"},
    },
    {
        "device_id": "esp32-soil-02",
        "name": "土壤墒情节点",
        "role": "soil",
        "location": "A 区茶垄",
        "is_mock": False,
        "config_json": {
            "telemetry_interval_s": 30,
            "status_interval_s": 15,
            "board": "ESP32-E",
            "adc_pin": 34,
            "calibrated": False,
        },
    },
    {
        "device_id": "k10-act-03",
        "name": "执行终端",
        "role": "actuator",
        "location": "A 区泵房",
        "is_mock": False,
        "config_json": {
            "telemetry_interval_s": 30,
            "status_interval_s": 15,
            "board": "K10",
            "relay_pin": 1,
            "relay_active_low": True,
            "max_duration_s": 120,
        },
    },
]

# ---------------------------------------------------------------- 全局配置（PRD 6.14）
DEFAULT_SETTINGS: list[dict[str, Any]] = [
    {"key": "mode", "value": "mock", "description": "运行模式：mock / real"},
    {"key": "llm_provider", "value": "glm", "description": "LLM 主供应商：glm / deepseek"},
    {"key": "llm_api_key", "value": "", "description": "加密存储的 API Key（设置页填写）"},
    {"key": "irrigation_default_range", "value": [55, 65], "description": "土壤湿度目标区间 %"},
    {"key": "schedule_cron", "value": "0 */2 * * *", "description": "巡园定时（默认每 2 小时）"},
    {"key": "parallel_enabled", "value": True, "description": "并行调度开关（串并行演示用）"},
    {"key": "max_retries", "value": 3, "description": "任务最大重试次数"},
    {"key": "weather_scenario", "value": "sunny", "description": "Mock 天气档位：sunny/cloudy/rainy/frost"},
    {"key": "mock_dry_rate_per_min", "value": 0.05, "description": "Mock 土壤每小时蒸发速率 %/min"},
    {"key": "mock_pump_gain_per_s", "value": 0.35, "description": "Mock 浇水每秒提升湿度 %/s"},
]


def seed_devices(db: Session) -> int:
    """补齐缺失设备，返回新增条数。"""
    existing = {row for row in db.scalars(select(Device.device_id)).all()}
    added = 0
    for item in DEFAULT_DEVICES:
        if item["device_id"] in existing:
            continue
        db.add(Device(**item))
        added += 1
    if added:
        db.flush()
        logger.info("设备种子：新增 {} 台设备（{}）", added, ", ".join(d["device_id"] for d in DEFAULT_DEVICES))
    return added


def seed_settings(db: Session) -> int:
    """补齐缺失配置键，返回新增条数。"""
    existing = set(db.scalars(select(Setting.key)).all())
    added = 0
    for item in DEFAULT_SETTINGS:
        if item["key"] in existing:
            continue
        db.add(Setting(**item))
        added += 1
    if added:
        db.flush()
        logger.info("配置种子：新增 {} 个配置键", added)
    return added


def seed_defaults(db: Session) -> dict[str, int]:
    stats = {"devices": seed_devices(db), "settings": seed_settings(db)}
    db.commit()
    return stats
