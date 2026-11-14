"""全局配置（PRD 7.4 / 6.14）：设置页读写，mode 切换是全平台总开关。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core import runtime_settings
from ..core.ws_manager import manager
from ..db import get_db
from ..mock.simulator import simulator

router = APIRouter(prefix="/settings", tags=["settings"])
settings = get_settings()


class SettingsIn(BaseModel):
    values: dict[str, Any] = Field(..., description="要修改的键值对，如 {\"mode\": \"real\"}")


@router.get("", summary="读取全部配置（敏感项已掩码）")
def read_settings() -> dict[str, Any]:
    return {
        "mode": runtime_settings.get_mode(),
        "llm_ready": settings.llm_ready,
        "items": runtime_settings.describe_all(),
    }


@router.put("", summary="批量修改配置（改 mode 会广播 mode_changed）")
def update_settings(body: SettingsIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not body.values:
        raise HTTPException(status_code=400, detail="values 不能为空")

    mode_before = runtime_settings.get_mode()

    # llm_api_key 的三态（null=清空 / ""=不改 / 含 *=掩码跳过）全部由
    # runtime_settings._secret_action 判定，路由层不插一手：
    # 以前这里先 pop 掉空串，等于把「不改」策略散成两处，加 null 清空时必然漏一边。
    runtime_settings.set_many(dict(body.values))
    mode_after = runtime_settings.get_mode()
    if "mode" in body.values and mode_before != mode_after:
        _apply_mode(mode_after)
        manager.publish_threadsafe("mode_changed", {"mode": mode_after, "previous": mode_before})

    return {"mode": mode_after, "items": runtime_settings.describe_all(), "changed": list(body.values)}


@router.post("/mode", summary="切换 Mock/Real（等价于 PUT /settings {mode}）")
async def switch_mode(mode: str) -> dict[str, Any]:
    mode = mode.lower()
    if mode not in {"mock", "real"}:
        raise HTTPException(status_code=400, detail="mode 只能是 mock 或 real")
    before = runtime_settings.get_mode()
    runtime_settings.set_many({"mode": mode})
    _apply_mode(mode)
    await manager.broadcast("mode_changed", {"mode": mode, "previous": before})
    return {"mode": mode, "previous": before}


def _apply_mode(mode: str) -> None:
    """mode 落地的副作用：mock 起模拟器，real 停模拟器并停用假设备。"""
    from loguru import logger

    from ..db import session_scope
    from ..devices import registry

    if mode == "mock":
        if settings.simulator_autostart or not simulator.running:
            simulator.start()
        logger.info("平台已切到 Mock 模式（模拟器 {}）", "运行中" if simulator.running else "未启动")
    else:
        if simulator.running:
            simulator.stop()
        # 只停线程不够：mock-* 还留在 devices 表里，120s 后 sweep_offline 会连发假离线报警
        try:
            with session_scope() as db:
                registry.deactivate_mock_devices(db)
        except Exception as exc:  # pragma: no cover - 库不可用不该阻止切模式
            logger.warning("停用 Mock 设备失败（切模式继续）：{}", exc)
        logger.info("平台已切到 Real 模式（模拟器已停，等待真设备心跳）")
