"""后台生命周期编排（PRD 7.5）：MQTT → 模拟器 → 巡检循环 → 队长三块接线。

为什么单独一个文件：main.py 只该管「应用对象」，进程里起停这些东西的逻辑放这里。
"""
from __future__ import annotations

import asyncio
import importlib
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


# ------------------------------------------------------- 队长地盘的接线点
def _install(name: str, module: str, func: str) -> bool:
    """导入并执行队长侧的一个接线函数，失败只降级、不带崩应用。

    为什么不写在模块顶部 import：`workflow/` `verification/` `orchestrator/` 是并行分支上
    的目录，这两支合并前本分支并没有它们。顶部 import 一旦缺模块，`app.main` 直接导入失败
    ——连 `/api/health` 都拿不到，问题还看不出在哪。放在这里，缺模块只表现为
    「对应接口 503 + health 里 not_ready」，符合 PRD 的原则：宁可功能未就绪，不让平台起不来。

    三个 install/start 自身也是幂等的、内部失败只记日志，这里再兜一层是为了防 import 期异常。
    """
    try:
        mod = importlib.import_module(module, __package__)
        getattr(mod, func)()
        return True
    except Exception as exc:  # noqa: BLE001 接线失败绝不能让进程起不来
        logger.warning("{} 未接线（相关接口将返回 503）：{}: {}", name, type(exc).__name__, exc)
        return False


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

    # 队长三块接线。顺序有讲究：引擎先接库（并首次写入默认工作流）→ 验证引擎才能取数落库
    # → 调度器最后开跑，否则 1s 后的第一轮就可能拿到未接线的 deps。
    _install("工作流引擎", ".workflow.wiring", "install")
    _install("验证引擎", ".verification.wiring", "install")
    _install("任务调度器", ".orchestrator.wiring", "start_scheduler")


def stop_all() -> None:
    # 调度器先停：它每轮都会写库，别让它在 MySQL 断开后还在 tick
    _install("任务调度器", ".orchestrator.wiring", "stop_scheduler")
    _stop.set()
    if _housekeeping is not None:
        _housekeeping.join(timeout=3)
    simulator.stop()
    mqtt_client.stop()
    logger.info("后台组件已全部停止")
