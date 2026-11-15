"""路由层公共工具：分页、404 判定、序列化。

跨地盘的调用不在这里了 —— 统一走 `app.seams`（见该文件顶部注释）。
"""
from __future__ import annotations

from typing import Any, Sequence

from fastapi import HTTPException


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
