"""后台生命周期编排（PRD 7.5）：MQTT → 模拟器 → 巡检循环。

为什么单独一个文件：main.py 只该管「应用对象」，进程里起停这些东西的逻辑放这里，
队长将来接调度循环（orchestrator.scheduler）也只需要在这里加一行。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Optional

from loguru import logger

from .config import get_settings
from .core import mqtt_client
from .core.runtime_settings import get_mode
from .core.ws_manager import manager
from .db import session_scope
from .devices import command, registry
from .mock.simulator import simulator

settings = get_settings()

_stop = threading.Event()
_housekeeping: Optional[threading.Thread] = None


# ------------------------------------------------------------------ 巡检线程
def _housekeeping_loop() -> None:
    """每 5s 一轮：指令超时扫描；每 15s：设备离线巡检。"""
    tick = 0
    while not _stop.is_set():
        try:
            with session_scope() as db:
                command.sweep_ack_timeouts(db)
                if tick % 3 == 0:
                    registry.sweep_offline(db)
        except Exception as exc:  # 后台线程绝不能死
            logger.exception("巡检循环异常：{}", exc)
        tick += 1
        _stop.wait(5)
    logger.info("巡检线程退出")


def start_housekeeping() -> None:
    global _housekeeping
    if _housekeeping is not None and _housekeeping.is_alive():
        return
    _stop.clear()
    _housekeeping = threading.Thread(target=_housekeeping_loop, name="housekeeping", daemon=True)
    _housekeeping.start()
    logger.info("巡检线程启动（5s 超时扫描 / 15s 离线巡检）")


# ------------------------------------------------------------------ 总起停
def start_all(loop: asyncio.AbstractEventLoop) -> None:
    manager.bind_loop(loop)
    mqtt_client.start()

    mode = get_mode()
    if mode == "mock" and settings.simulator_autostart:
        simulator.start()
    elif mode == "real":
        logger.info("Real 模式：不启动模拟器，等待真设备心跳")
    else:
        logger.info("Mock 模式但 SIMULATOR_AUTOSTART=false：模拟器未启动")

    start_housekeeping()


def stop_all() -> None:
    _stop.set()
    if _housekeeping is not None:
        _housekeeping.join(timeout=3)
    simulator.stop()
    mqtt_client.stop()
    logger.info("后台组件已全部停止")
