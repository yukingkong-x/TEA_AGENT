"""数据库引擎与会话（PRD 3.2：SQLAlchemy 2.x + PyMySQL）。

同步引擎：PyMySQL 是同步驱动，PRD 3.2 已锁定。用法约定：
- FastAPI 路由用 `def`（不是 `async def`），由 Starlette 自动丢线程池，不阻塞事件循环；
- 后台线程（MQTT 回调、模拟器）直接用 `session_scope()`；
- 事件循环里的异步任务要写库时，用 `asyncio.to_thread(...)` 包一层。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

settings = get_settings()

engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,  # 断线自动探活，MySQL 8 默认 8 小时断连
    pool_recycle=1800,
    pool_size=10,
    max_overflow=20,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入用。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """线程内使用的短事务：正常提交，异常回滚。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """建表（幂等）。比赛期不引 Alembic：表结构变更靠 models 改 + create_all。"""
    from . import models  # noqa: F401  必须导入，触发全部表注册到 metadata
    from .models.base import Base

    Base.metadata.create_all(bind=engine)
    logger.info("数据库建表完成：{} 张表", len(Base.metadata.tables))


def ping() -> bool:
    """健康检查用，不抛异常。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - 依赖真实数据库
        logger.warning("MySQL 探活失败：{}", exc)
        return False
