"""MQTT 客户端（PRD 5.1 ~ 5.5）—— 平台唯一的设备上行入口。

要点：
- QoS1 订阅 `tea/device/+/telemetry|status|ack`，重连退避 1s→30s；
- paho 回调跑在自己的网络线程里，写库直接用同步 session（不能 await）；
- 广播走 `ws_manager.publish_threadsafe`，丢回主事件循环；
- 幂等：telemetry 按 `device_id+seq`、cmd/ack 按 `msg_id` 去重（Redis SETNX）；
- 兜底：broker 挂了时 `publish()` 会尝试进程内直投（Mock 演示不怕 MQTT 掉线）。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt
from loguru import logger

from ..config import get_settings
from ..db import session_scope
from ..models.sensor_data import SensorData
from .redis_client import Keys, mark_once, touch_last_seen
from .ws_manager import manager

settings = get_settings()

QOS = 1
SUB_TOPICS = [
    ("tea/device/+/telemetry", QOS),
    ("tea/device/+/status", QOS),
    ("tea/device/+/ack", QOS),
]
KNOWN_METRICS = {"temperature_c", "humidity_air", "lux", "soil_moisture"}

_client: Optional[mqtt.Client] = None
_connected = threading.Event()
_local_dispatch: Optional[Callable[[str, dict[str, Any]], None]] = None
_stats = {"rx": 0, "tx": 0, "last_rx_ts": 0.0, "connected": False, "reconnects": 0}


# ------------------------------------------------------------------ 内部：分主题处理
def _device_id_from_topic(topic: str) -> str:
    parts = topic.split("/")
    return parts[2] if len(parts) >= 4 else "unknown"


def _handle_telemetry(device_id: str, payload: dict[str, Any]) -> None:
    ts_raw = payload.get("ts")
    ts = float(ts_raw) if isinstance(ts_raw, (int, float)) else time.time()
    seq = payload.get("seq")
    metrics = payload.get("metrics") or {}
    if not isinstance(metrics, dict) or not metrics:
        logger.warning("遥测报文缺 metrics：{}", payload)
        return

    # seq 去重只防 QoS1 秒级重复，TTL 给 120s 足够；配合 boot_id 让设备重启后 seq 归零也不误杀。
    # （此前 TTL=3600 且键不含 boot_id，重启后新遥测被当成重复静默丢一小时）
    boot_id = payload.get("boot_id")
    if seq is not None and not mark_once(Keys.dedup_seq(device_id, seq, boot_id), ttl_s=120):
        logger.debug("遥测重复丢弃：{} seq={}", device_id, seq)
        return

    clean: dict[str, float] = {}
    for key, value in metrics.items():
        if not isinstance(value, (int, float)):
            logger.warning("遥测指标 {} 类型错误（{}），已跳过", key, type(value).__name__)
            continue
        clean[key] = float(value)

    with session_scope() as db:
        for metric, value in clean.items():
            db.add(
                SensorData(
                    device_id=device_id,
                    metric=metric,
                    value=round(value, 2),
                    raw=payload,
                    ts=_to_datetime(ts),
                )
            )
        # 有遥测就说明设备活着（比等心跳更灵敏）
        touch_last_seen(device_id, ts)

    manager.publish_threadsafe(
        "telemetry",
        {
            "device_id": device_id,
            "metrics": clean,
            "rssi": payload.get("rssi"),
            "ts": ts,
            "seq": seq,
        },
    )
    logger.debug("遥测入库 {} {} seq={}", device_id, clean, seq)


def _handle_status(device_id: str, payload: dict[str, Any]) -> None:
    from ..devices import registry

    ts_raw = payload.get("ts")
    ts = float(ts_raw) if isinstance(ts_raw, (int, float)) else time.time()
    online = payload.get("online", True)
    with session_scope() as db:
        device = registry.touch(
            db,
            device_id,
            ts=ts,
            rssi=payload.get("rssi"),
            online=bool(online),
            is_mock=payload.get("is_mock"),
        )
        db.flush()
        state = registry.state_dict(device)
    manager.publish_threadsafe("device_status", state)
    logger.debug("心跳 {} online={} rssi={}", device_id, online, payload.get("rssi"))


def _handle_ack(device_id: str, payload: dict[str, Any]) -> None:
    from ..devices import command

    # 设备侧可能不带 device_id，用主题里的补上
    payload.setdefault("device_id", device_id)
    with session_scope() as db:
        command.handle_ack(db, payload)


def _to_datetime(ts: float):
    from datetime import datetime

    try:
        return datetime.fromtimestamp(ts)
    except (OverflowError, OSError, ValueError):
        return datetime.now()


# ------------------------------------------------------------------ paho 回调
def _on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
    if getattr(reason_code, "is_failure", False) or reason_code != 0:
        logger.error("MQTT 连接失败：{}", reason_code)
        _stats["connected"] = False
        return
    _connected.set()
    _stats["connected"] = True
    logger.info(
        "MQTT 已连接 {}:{}（client_id={}）",
        settings.mqtt_host,
        settings.mqtt_port,
        settings.mqtt_client_id,
    )
    for topic, qos in SUB_TOPICS:
        client.subscribe(topic, qos=qos)
    logger.info("MQTT 订阅完成：{}", [t for t, _ in SUB_TOPICS])


def _on_disconnect(client: mqtt.Client, userdata, flags=None, reason_code=None, properties=None) -> None:
    _connected.clear()
    _stats["connected"] = False
    _stats["reconnects"] += 1
    logger.warning("MQTT 断开（{}），将自动重连", reason_code)


def _on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    _stats["rx"] += 1
    _stats["last_rx_ts"] = time.time()
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as exc:
        logger.warning("MQTT 报文不是合法 JSON（{}）：{}", msg.topic, exc)
        return

    device_id = _device_id_from_topic(msg.topic)
    kind = msg.topic.rsplit("/", 1)[-1]
    try:
        if kind == "telemetry":
            _handle_telemetry(device_id, payload)
        elif kind == "status":
            _handle_status(device_id, payload)
        elif kind == "ack":
            _handle_ack(device_id, payload)
        else:
            logger.debug("忽略非上行主题：{}", msg.topic)
    except Exception as exc:  # 任何异常都不能让 paho 线程死掉
        logger.exception("处理 MQTT 消息失败 topic={} err={}", msg.topic, exc)


# ------------------------------------------------------------------ 对外 API
def set_local_dispatcher(fn: Optional[Callable[[str, dict[str, Any]], None]]) -> None:
    """Mock 模拟器注册进程内直投回调（broker 掉线时仍能演示）。"""
    global _local_dispatch
    _local_dispatch = fn


def publish(topic: str, payload: dict[str, Any] | str, qos: int = QOS) -> bool:
    """发布消息。返回是否真的发出去了（False 时已尝试进程内直投）。"""
    global _stats
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    client = _client
    if client is not None and _connected.is_set():
        try:
            info = client.publish(topic, text, qos=qos)
            ok = info.rc == mqtt.MQTT_ERR_SUCCESS
            if ok:
                _stats["tx"] += 1
            return ok
        except Exception as exc:  # pragma: no cover
            logger.warning("MQTT 发布失败 {}：{}", topic, exc)

    if _local_dispatch is not None:
        try:
            _local_dispatch(topic, json.loads(text) if isinstance(text, str) else text)
            logger.debug("MQTT 不可用，已进程内直投：{}", topic)
            return False
        except Exception as exc:  # pragma: no cover
            logger.warning("进程内直投失败 {}：{}", topic, exc)
    return False


def start() -> None:
    """启动客户端（连接失败不阻塞启动，后台自动重连）。"""
    global _client
    if _client is not None:
        return
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=settings.mqtt_client_id,
        clean_session=False,
        protocol=mqtt.MQTTv311,
    )
    if settings.mqtt_user:
        client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=settings.mqtt_keepalive)
    client.loop_start()
    _client = client
    logger.info("MQTT 客户端启动：{}:{}", settings.mqtt_host, settings.mqtt_port)


def stop() -> None:
    global _client
    if _client is None:
        return
    try:
        _client.disconnect()
        _client.loop_stop()
    except Exception:  # pragma: no cover
        pass
    _client = None
    _connected.clear()
    logger.info("MQTT 客户端已关闭")


def is_connected() -> bool:
    return _connected.is_set()


def stats() -> dict[str, Any]:
    return {**_stats, "connected": _connected.is_set()}
