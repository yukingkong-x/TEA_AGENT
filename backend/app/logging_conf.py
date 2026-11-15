"""日志（PRD 7.5：loguru，格式 时间 | 级别 | 模块 | 消息，写 logs/backend.log 轮转 10MB×5）。"""
from __future__ import annotations

import logging
import sys

from loguru import logger

from .config import get_settings


class _InterceptHandler(logging.Handler):
    """把标准库 logging（uvicorn / sqlalchemy）的日志转进 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - 日志管道
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    settings = get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    fmt = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} | {message}"

    logger.add(sys.stderr, level=settings.log_level.upper(), format=fmt, backtrace=False, diagnose=False)
    logger.add(
        settings.log_dir / "backend.log",
        level=settings.log_level.upper(),
        format=fmt,
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        enqueue=True,
    )

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine", "paho"):
        lg = logging.getLogger(name)
        lg.handlers = [_InterceptHandler()]
        lg.propagate = False

    logger.debug("日志系统就绪，level={}，文件={}", settings.log_level, settings.log_dir / "backend.log")
