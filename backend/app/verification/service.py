"""接缝入口（基座 `seams._CANDIDATES` 找的是 `app.verification.service.verify_task`）。

实现都在 `engine.py`，这里只是让接缝按名字找得到。同 `workflow/service.py`，
补别名而不是去改队友 B 的 `seams.py`：少一次跨地盘改动，也少一次合并冲突。
"""
from __future__ import annotations

from app.verification.engine import (
    VerificationDeps,
    configure,
    generate_report,
    is_ready,
    verify_task,
)

__all__ = ["VerificationDeps", "configure", "is_ready", "verify_task", "generate_report"]
