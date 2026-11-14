"""接缝入口（基座 `seams._CANDIDATES` 找的就是这个模块名）。

为什么要有这层看起来多余的别名：队友 B 的 `app/seams.py` 里写死了
    "start_run": (("app.workflow.service", "start_run"),)
而我这边引擎落在 `app.workflow.engine`。改他的文件要跨地盘，且他改完我还得再合一次；
在这里补一个同名入口，两边都不用动——接缝按名字取函数，取到的是同一个实现。

约定不变：未注入 `EngineDeps` 时抛 `SeamNotReady`（路由 → 503 + SEAM_NOT_READY）。
"""
from __future__ import annotations

from app.workflow.dag import validate_dag
from app.workflow.engine import (
    WorkflowEngine,
    WorkflowError,
    WorkflowNotReady,
    configure,
    is_ready,
    start_run,
)

__all__ = [
    "WorkflowEngine", "WorkflowError", "WorkflowNotReady",
    "configure", "is_ready", "start_run", "validate_dag",
]
