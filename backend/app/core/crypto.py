"""密钥加密（PRD 6.14：llm_api_key 加密存）。

用 SECRET_KEY 派生 Fernet 密钥，落库时带 `enc:` 前缀；
明文（历史数据 / 手工入库）也能读，读到不带前缀的值就原样返回。
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from ..config import get_settings

PREFIX = "enc:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plain: str) -> str:
    if not plain:
        return ""
    return PREFIX + _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(stored: str | None) -> str:
    if not stored:
        return ""
    if not stored.startswith(PREFIX):
        return stored
    try:
        return _fernet().decrypt(stored[len(PREFIX) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:  # pragma: no cover
        logger.error("API Key 解密失败（SECRET_KEY 变过？）：{}", exc)
        return ""


def mask(secret: str | None) -> str:
    """给前端看的掩码：sk-a****wxyz。"""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * 4}{secret[-4:]}"
