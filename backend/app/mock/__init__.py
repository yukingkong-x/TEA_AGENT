"""mock 包：Mock 设备模拟器（PRD 12.2，REQ-F-019）。"""
from .simulator import ALL_DEVICES, WEATHER_PRESETS, get_weather, simulator

__all__ = ["simulator", "get_weather", "ALL_DEVICES", "WEATHER_PRESETS"]
