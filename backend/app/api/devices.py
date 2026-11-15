"""设备（PRD 7.4）+ Mock 模拟器控制台（PRD 12.2 故障注入）。

路径顺序有讲究：静态路径（/devices/fault、/devices/mock）必须写在 /devices/{device_id} 之前，
否则会被当成 device_id 匹配走。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import mqtt_client
from ..core.redis_client import ping as redis_ping
from ..core.runtime_settings import get_mode
from ..db import get_db
from ..devices import command, registry
from ..mock.simulator import ALL_DEVICES, FAULT_NAMES, WEATHER_PRESETS, simulator
from ..models.devices import Device
from ._common import ensure_found

router = APIRouter(prefix="/devices", tags=["devices"])


class CmdIn(BaseModel):
    action: str = Field(..., description="pump / read_now / relay_off / calibrate_dry / calibrate_wet / reboot")
    params: dict[str, Any] = Field(default_factory=dict)
    task_no: str | None = None


class FaultIn(BaseModel):
    fault: str = Field(..., description=" / ".join(FAULT_NAMES))
    device: str | None = Field(None, description="offline 注入的目标设备，默认土壤节点")
    seconds: int = 120


# ---------------------------------------------------------------- Mock 控制台
@router.get("/mock", summary="模拟器状态与故障开关")
def mock_state() -> dict[str, Any]:
    return {"mode": get_mode(), **simulator.state()}


@router.post("/mock/start", summary="启动模拟器")
def mock_start() -> dict[str, Any]:
    simulator.start()
    return simulator.state()


@router.post("/mock/stop", summary="停止模拟器")
def mock_stop() -> dict[str, Any]:
    simulator.stop()
    return simulator.state()


@router.post("/fault", summary="注入故障（PRD 12.2 五种）")
def inject_fault(body: FaultIn) -> dict[str, Any]:
    if body.fault not in FAULT_NAMES:
        raise HTTPException(status_code=400, detail=f"未知故障 {body.fault}，可选 {list(FAULT_NAMES)}")
    if not simulator.running:
        simulator.start()
    return simulator.inject(body.fault, device=body.device, seconds=body.seconds)


@router.delete("/fault", summary="清除故障注入（传 fault 只清一种，不传清全部）")
def clear_fault(fault: str | None = Query(None)) -> dict[str, Any]:
    return simulator.clear(fault)


@router.post("/weather", summary="切换 Mock 天气档位（sunny/cloudy/rainy/frost）")
def switch_weather(scenario: str = Query(..., description=" / ".join(WEATHER_PRESETS))) -> dict[str, Any]:
    if scenario not in WEATHER_PRESETS:
        raise HTTPException(status_code=400, detail=f"未知档位 {scenario}")
    return simulator.set_weather(scenario)


@router.get("/mqtt", summary="MQTT 链路统计（联调用）")
def mqtt_stats() -> dict[str, Any]:
    return {**mqtt_client.stats(), "redis": redis_ping(), "mode": get_mode(), "mock_devices": list(ALL_DEVICES)}


# ---------------------------------------------------------------- 设备
@router.get("", summary="设备列表（含在线三态；缺省返回全量）")
def list_devices(
    is_mock: str | None = Query(
        None,
        description="true=只要 Mock / false=只要真机 / all=全量（等同缺省）",
    ),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """缺省不过滤——Mock 与真机可能同时在跑，交给前端按 is_mock 字段分组。"""
    if is_mock is None:
        return registry.list_states(db)
    flag = is_mock.strip().lower()
    if flag == "all":
        return registry.list_states(db)
    if flag in {"true", "1", "yes"}:
        return registry.list_states(db, is_mock=True)
    if flag in {"false", "0", "no"}:
        return registry.list_states(db, is_mock=False)
    raise HTTPException(status_code=400, detail="is_mock 只接受 true / false / all")


@router.get("/{device_id}", summary="设备详情")
def get_device(device_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    device = db.scalar(select(Device).where(Device.device_id == device_id))
    ensure_found(device, f"设备 {device_id}")
    data = registry.state_dict(device)
    data["config"] = device.config_json
    return data


@router.post("/{device_id}/cmd", summary="手动下发指令（设置页调试）")
def send_device_cmd(device_id: str, body: CmdIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        result = command.send_cmd(
            db,
            device_id,
            body.action,
            body.params,
            task_no=body.task_no,
            issued_by="api:manual",
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return result
