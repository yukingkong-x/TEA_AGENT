"""简化鉴权（PRD 7.1 core/security.py：单管理员 token）。

规则：
- 默认**不拦**任何请求（本地演示、评委现场操作零门槛）；
- 一旦 `ENFORCE_AUTH=true`（`.env` 里开），写操作（POST/PUT/DELETE）必须带
  `X-Admin-Token` 或 `?token=`，与 ADMIN_TOKEN 一致；
- WebSocket 同样支持 `?token=`，不校验时忽略。
"""
from __future__ import annotations

import os

from fastapi import Header, HTTPException, Query, status

from ..config import get_settings

settings = get_settings()
ENFORCE = os.getenv("ENFORCE_AUTH", "false").lower() in {"1", "true", "yes"}


def require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    token: str | None = Query(default=None, description="备用：查询参数传 token"),
) -> None:
    if not ENFORCE:
        return
    provided = x_admin_token or token
    if provided != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理员令牌无效")


def check_ws_token(token: str | None) -> bool:
    if not ENFORCE:
        return True
    return token == settings.admin_token
