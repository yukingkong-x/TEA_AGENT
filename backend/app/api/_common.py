"""路由层公共工具：分页、跨地盘模块调用、序列化。"""
from __future__ import annotations

import importlib
from typing import Any, Sequence

from fastapi import HTTPException


def delegate(dotted: str, attr: str | None = None, *, owner: str = "队长"):
    """调用别人地盘的模块（knowledge / workflow / verification / reports）。

    对方模块还没落地时返回 503 + 一句人话，而不是 500 —— 前端能据此显示「模块未就绪」。
    接口约定见 docs/contracts/api_seams.md。
    """
    try:
        module = importlib.import_module(dotted)
    except Exception as exc:  # ImportError 或模块内部初始化失败
        raise HTTPException(
            status_code=503,
            detail=f"依赖模块 {dotted} 尚未就绪（{owner} 地盘）：{exc}",
        ) from exc
    if attr is None:
        return module
    fn = getattr(module, attr, None)
    if fn is None:
        raise HTTPException(
            status_code=503,
            detail=f"模块 {dotted} 缺少接口 {attr}()（{owner} 地盘），约定见 docs/contracts/api_seams.md",
        )
    return fn


def page_payload(items: Sequence[dict[str, Any]], total: int, page: int, page_size: int) -> dict[str, Any]:
    return {
        "items": list(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size else 0,
    }


def ensure_found(obj: Any, what: str) -> Any:
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{what} 不存在")
    return obj
