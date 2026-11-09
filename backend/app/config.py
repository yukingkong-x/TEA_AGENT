"""统一配置对象（PRD 7.1 · config.py）。

分工：
- 本文件只负责**静态**配置（.env：连接串、密钥、路径、开关）；
- 运行期可改的业务开关（mode / llm_provider / 调度参数 / 阈值）落在 `settings` 表，
  由 `app.core.runtime_settings` 读取并带缓存——因为启动前还连不上数据库，
  配置对象不可能在 import 期就去查表。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
ROOT_DIR = BACKEND_DIR.parent  # 仓库根


class Settings(BaseSettings):
    """全部字段都能用同名环境变量覆盖（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        # 容器里用 /app/.env（compose env_file 注入），本机调试用仓库根 .env
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 应用 ----------
    app_name: str = "知秋 · 茶园多智能体编排平台"
    app_version: str = "1.0.0"
    tz: str = "Asia/Shanghai"
    log_level: str = "INFO"
    debug: bool = False
    secret_key: str = "dev-only-secret-key-change-me-in-env-32chars"
    admin_token: str = "dev-only-admin-token"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"

    # ---------- MySQL ----------
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "zhiqiu"
    mysql_user: str = "zhiqiu"
    mysql_password: str = "CHANGE_ME_demo_password"
    mysql_root_password: str = "CHANGE_ME_mysql_root"

    # ---------- Redis ----------
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # ---------- MQTT ----------
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_user: str = "tea"
    mqtt_password: str = "CHANGE_ME_mqtt"
    mqtt_client_id: str = "zhiqiu-backend"
    mqtt_keepalive: int = 60

    # ---------- Chroma ----------
    chroma_host: str = "127.0.0.1"
    chroma_port: int = 8100

    # ---------- LLM ----------
    llm_provider: str = "glm"  # glm | deepseek
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-4-flash"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # ---------- 运行开关 ----------
    simulator_autostart: bool = True
    backend_port: int = 8000

    # ---------- 路径 ----------
    @property
    def upload_dir(self) -> Path:
        return BACKEND_DIR / "uploads"

    @property
    def log_dir(self) -> Path:
        return BACKEND_DIR / "logs"

    # ---------- 连接串 ----------
    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{quote_plus(self.redis_password)}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ---------- LLM provider 链 ----------
    @property
    def llm_provider_chain(self) -> list[dict[str, str]]:
        """主 provider 在前、备 provider 在后，直接喂给 core/llm.py 的 LLMClient。

        注意：api_key 可能是空串（没填 key 时），由 LLMClient 走降级逻辑，
        这里不做过滤，避免「没 key 就起不来」。
        """
        glm = {
            "name": "glm",
            "base_url": self.glm_base_url,
            "api_key": self.glm_api_key,
            "model": self.glm_model,
        }
        deepseek = {
            "name": "deepseek",
            "base_url": self.deepseek_base_url,
            "api_key": self.deepseek_api_key,
            "model": self.deepseek_model,
        }
        return [glm, deepseek] if self.llm_provider != "deepseek" else [deepseek, glm]

    @property
    def llm_ready(self) -> bool:
        """至少配了一个 key 才算可调用；否则全平台进入规则降级。"""
        return bool(self.glm_api_key or self.deepseek_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
