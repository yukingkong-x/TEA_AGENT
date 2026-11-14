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


def _sync_enum_column(table: str, column: str, values: tuple[str, ...], default: str | None = None) -> bool:
    """把 MySQL 原生 ENUM 列补齐到 `values`（只增不删，幂等）。

    为什么需要它：`create_all` 只 CREATE 不 ALTER，**已经存在的库改 models 不会生效**。
    演示机上的库是上一版建的，`tasks.status` 少一个 `needs_human`，验证器一转人工就报
    `Data truncated for column 'status'`——这种错误只会在现场那一刻出现，最容易被当成别的问题。
    比赛期不引 Alembic（PRD 3.2 的取舍），就这一处按需 ALTER，比整库迁移稳。

    只在实际缺值时执行 ALTER；非 MySQL 或表还没建时静默跳过（SQLite 测试库走这条）。
    """
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
                ),
                {"t": table, "c": column},
            ).first()
            if row is None:
                return False
            current = str(row[0] or "")
            missing = [v for v in values if f"'{v}'" not in current]
            if not missing:
                return False
            ddl = ", ".join(f"'{v}'" for v in values)
            tail = f" NOT NULL DEFAULT '{default}'" if default else ""
            conn.execute(text(f"ALTER TABLE {table} MODIFY COLUMN {column} ENUM({ddl}){tail}"))
        logger.info("{}.{} 枚举已补齐：{}", table, column, ", ".join(missing))
        return True
    except Exception as exc:  # noqa: BLE001 同步失败不该挡住启动
        logger.warning("{}.{} 枚举同步失败（写入 {} 可能被 MySQL 截断）：{}", table, column, values[-2:], exc)
        return False


def init_db() -> None:
    """建表（幂等）。比赛期不引 Alembic：表结构变更靠 models 改 + create_all。"""
    from . import models  # noqa: F401  必须导入，触发全部表注册到 metadata
    from .models.base import Base
    from .models.tasks import TASK_STATUS

    Base.metadata.create_all(bind=engine)
    logger.info("数据库建表完成：{} 张表", len(Base.metadata.tables))

    # 老库补列（create_all 覆盖不到的部分）。新库这里直接 return False，无额外开销。
    _sync_enum_column("tasks", "status", TASK_STATUS, default="pending")


def ping() -> bool:
    """健康检查用，不抛异常。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - 依赖真实数据库
        logger.warning("MySQL 探活失败：{}", exc)
        return False
