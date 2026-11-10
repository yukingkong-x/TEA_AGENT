"""Mock 设备模拟器（PRD 12.2，REQ-F-019）——开发期的假设备，也是演示的保险。

单进程三线程，行为与真固件一致：同样发 telemetry / status / ack，同样收 cmd。
- 土壤模型：M(t+dt) = M(t) − dry_rate·dt + water_effect
  浇水时「即时上升 60% + 其后 60s 缓慢渗透 40%」，30s 浇水 ≈ +10.5%（gain 0.35%/s）
- 执行终端收到 pump → 立刻 ack received → 等 duration_s → ack finished
- 5 种故障注入：offline / ack_timeout / dry_soil / stuck_moisture / sensor_jitter
  `stuck_moisture` 是两轮对照演示的总开关：第 1 轮注入让验证失败，关掉后第 2 轮自然成功。
"""
from __future__ import annotations

import json
import math
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import paho.mqtt.client as mqtt
from loguru import logger

from ..config import get_settings
from ..core import mqtt_client
from ..core.redis_client import Keys, get_redis, mark_once
from ..core.runtime_settings import get_value
from ..db import session_scope
from ..devices import registry

settings = get_settings()

DEV_FIELD = "mock-k10-field-01"
DEV_SOIL = "mock-esp32-soil-02"
DEV_ACT = "mock-k10-act-03"
ALL_DEVICES = (DEV_FIELD, DEV_SOIL, DEV_ACT)

TELEMETRY_TOPIC = "tea/device/{device_id}/telemetry"
STATUS_TOPIC = "tea/device/{device_id}/status"
ACK_TOPIC = "tea/device/{device_id}/ack"
CMD_SUB_TOPIC = "tea/device/+/cmd"

FAULT_NAMES = ("offline", "ack_timeout", "dry_soil", "stuck_moisture", "sensor_jitter")

WEATHER_PRESETS = {
    "sunny": {"temp_range": [18, 28], "rain_prob": 5, "frost_risk": "none"},
    "cloudy": {"temp_range": [15, 24], "rain_prob": 30, "frost_risk": "none"},
    "rainy": {"temp_range": [14, 21], "rain_prob": 85, "frost_risk": "none"},
    "frost": {"temp_range": [2, 9], "rain_prob": 10, "frost_risk": "high"},
}


@dataclass
class SoilModel:
    """土壤湿度模型：自然蒸发线性下降，浇水即时上升 60% + 60s 内缓慢渗透 40%。"""

    moisture: float = 38.5  # 演示基线 38.5%，与 PRD 15.1 剧本一致
    dry_rate_per_min: float = 0.05  # %/min
    gain_per_s: float = 0.35  # %/s（浇水）
    residual_floor: float = 12.0  # 残余含水量下限：束缚水蒸发不掉（否则隔夜必干到 0，第二天演示全是 0.0）
    soak_rate: float = 0.0  # 当前渗透速率 %/s
    soak_until: float = 0.0
    last_tick: float = field(default_factory=time.time)
    stuck: bool = False

    def tick(self, now: Optional[float] = None) -> None:
        now = now or time.time()
        dt = max(0.0, now - self.last_tick)
        self.last_tick = now
        if dt <= 0:
            return
        # 自然蒸发：越接近残余含水量蒸发越慢（真实物理 + 保证隔夜不归零）
        headroom = max(0.0, self.moisture - self.residual_floor)
        taper = min(1.0, headroom / 20.0)  # 距下限 20% 以内线性放缓
        self.moisture -= self.dry_rate_per_min / 60.0 * dt * taper
        # 缓慢渗透（只在自己有效窗口内生效）
        if now < self.soak_until:
            effective = min(dt, self.soak_until - (now - dt))
            if effective > 0:
                self.moisture += self.soak_rate * effective
        else:
            self.soak_rate = 0.0
        self.moisture = max(self.residual_floor, min(100.0, self.moisture))

    def irrigate(self, duration_s: float) -> float:
        """返回理论提升量（%）。stuck_moisture 注入时水照浇但湿度不涨。"""
        total = self.gain_per_s * duration_s
        if self.stuck:
            logger.warning(
                "【故障注入】stuck_moisture 生效：浇水 {}s 但湿度不上升（演示 Self-Loop 第 1 轮失败）", duration_s
            )
            return total
        now = time.time()
        self.moisture = min(100.0, self.moisture + total * 0.6)
        self.soak_rate += total * 0.4 / 60.0
        self.soak_until = max(self.soak_until, now + 60.0)
        return total


class Simulator:
    """三台虚拟设备 + 故障注入开关。线程安全（一把大锁足够，量很小）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._client: Optional[mqtt.Client] = None
        self._running = False

        self.seq = {DEV_FIELD: 0, DEV_SOIL: 0, DEV_ACT: 0}
        self.boot_id = ""  # start() 时生成；上报里带它，重启后 seq 归零也不被去重误杀
        self.soil = SoilModel()
        self.act_busy_until = 0.0

        self.offline_until: dict[str, float] = {}
        self.faults: dict[str, Any] = {
            "offline": {},
            "ack_timeout": {"enabled": False, "remaining": 0},
            "dry_soil": False,
            "stuck_moisture": False,
            "sensor_jitter": False,
        }
        # 注意：这里不要读 settings 表 —— 模块导入时库还没建表，等 start() 再读
        self.weather = "sunny"

    # ------------------------------------------------------------ 生命周期
    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        # 本次开机的随机标识：随遥测上报，后端 seq 去重键带上它，
        # 这样模拟器（真机同理）重启后 seq 归零也不会被误判成重复报文
        self.boot_id = uuid.uuid4().hex[:8]

        self.soil.dry_rate_per_min = float(get_value("mock_dry_rate_per_min", 0.05))
        self.soil.gain_per_s = float(get_value("mock_pump_gain_per_s", 0.35))
        self.weather = str(get_value("weather_scenario", "sunny") or "sunny")

        self._register_devices()
        self._start_cmd_client()
        mqtt_client.set_local_dispatcher(self._on_local_dispatch)

        self._threads = [
            threading.Thread(target=self._run_field, name="sim-field", daemon=True),
            threading.Thread(target=self._run_soil, name="sim-soil", daemon=True),
            threading.Thread(target=self._run_act, name="sim-act", daemon=True),
        ]
        for t in self._threads:
            t.start()
        logger.info("Mock 模拟器已启动：{}", ", ".join(ALL_DEVICES))

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop.set()
        mqtt_client.set_local_dispatcher(None)
        if self._client is not None:
            try:
                self._client.disconnect()
                self._client.loop_stop()
            except Exception:  # pragma: no cover
                pass
            self._client = None
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []
        logger.info("Mock 模拟器已停止")

    def _register_devices(self) -> None:
        with session_scope() as db:
            registry.ensure_device(db, DEV_FIELD, role="field", name="[Mock] 巡园员一号", location="A 区茶垄东段", is_mock=True,
                                   config={"telemetry_interval_s": 30, "status_interval_s": 15, "board": "K10(sim)"})
            registry.ensure_device(db, DEV_SOIL, role="soil", name="[Mock] 土壤墒情节点", location="A 区茶垄", is_mock=True,
                                   config={"telemetry_interval_s": 30, "status_interval_s": 15, "board": "ESP32-E(sim)"})
            registry.ensure_device(db, DEV_ACT, role="actuator", name="[Mock] 执行终端", location="A 区泵房", is_mock=True,
                                   config={"telemetry_interval_s": 30, "status_interval_s": 15, "board": "K10(sim)", "max_duration_s": 120})
            db.commit()

    # ------------------------------------------------------------ 命令接收（MQTT + 进程内直投）
    def _start_cmd_client(self) -> None:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"zhiqiu-simulator-{int(time.time()) % 10000}",
            protocol=mqtt.MQTTv311,
        )
        if settings.mqtt_user:
            client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        client.reconnect_delay_set(1, 30)
        client.on_connect = lambda c, u, f, rc, p=None: c.subscribe(CMD_SUB_TOPIC, qos=1)
        client.on_message = lambda c, u, msg: self._dispatch_cmd(msg.topic, self._safe_json(msg.payload))
        try:
            client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=60)
            client.loop_start()
            self._client = client
        except Exception as exc:  # pragma: no cover
            logger.warning("模拟器 MQTT 客户端启动失败（不影响进程内直投）：{}", exc)

    @staticmethod
    def _safe_json(raw: bytes) -> dict[str, Any]:
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _on_local_dispatch(self, topic: str, payload: dict[str, Any]) -> None:
        self._dispatch_cmd(topic, payload)

    def _dispatch_cmd(self, topic: str, payload: dict[str, Any]) -> None:
        parts = topic.split("/")
        if len(parts) < 4 or parts[1] != "device" or parts[3] != "cmd":
            return
        device_id = parts[2]
        if device_id not in ALL_DEVICES:
            return
        msg_id = payload.get("msg_id")
        if msg_id and not mark_once(Keys.dedup_msg(msg_id), ttl_s=600):
            return  # MQTT 与进程内直投可能各来一次，msg_id 去重
        threading.Thread(target=self._handle_cmd, args=(device_id, payload), daemon=True).start()

    def _handle_cmd(self, device_id: str, payload: dict[str, Any]) -> None:
        action = payload.get("action")
        params = payload.get("params") or {}
        msg_id = payload.get("msg_id")
        task_no = payload.get("task_id") or payload.get("task_no")
        logger.info("【模拟设备】{} 收到指令 {} {} task={}", device_id, action, params, task_no)

        if self._is_offline(device_id):
            logger.warning("【模拟设备】{} 处于 offline 注入中，不响应指令（演示重试）", device_id)
            return

        self._send_ack(device_id, msg_id, task_no, "received", "done", {})

        if action == "pump":
            duration = float(params.get("duration_s", 30))
            with self._lock:
                self.act_busy_until = time.time() + duration
            # 土壤侧立即生效（即时 60%）
            if device_id == DEV_ACT:
                with self._lock:
                    gained = self.soil.irrigate(duration)
            else:
                gained = 0.0
            end = time.time() + duration
            while time.time() < end and not self._stop.is_set():
                time.sleep(0.1)
            detail = {"executed_s": duration, "clamped": duration > 120, "moisture_gain": round(gained, 2)}
            self._send_ack(device_id, msg_id, task_no, "finished", "done", detail)
            logger.info("【模拟设备】{} 浇水完成 {}s，理论提升 {:.2f}%", device_id, duration, gained)

        elif action == "read_now":
            self._publish_once(device_id, force=True)
            self._send_ack(device_id, msg_id, task_no, "finished", "done", {"executed_s": 0})

        elif action == "relay_off":
            with self._lock:
                self.act_busy_until = 0.0
            self._send_ack(device_id, msg_id, task_no, "finished", "done", {"executed_s": 0})

        elif action in {"calibrate_dry", "calibrate_wet"}:
            with self._lock:
                self.soil.moisture = 0.0 if action == "calibrate_dry" else 100.0
            self._send_ack(device_id, msg_id, task_no, "finished", "done", {"calibrated": action})

        elif action == "reboot":
            self._send_ack(device_id, msg_id, task_no, "finished", "done", {"rebooted": True})

        else:
            self._send_ack(device_id, msg_id, task_no, "finished", "rejected", {"reason": f"unsupported action {action}"})

    def _send_ack(self, device_id: str, msg_id: str | None, task_no: str | None, stage: str, result: str, detail: dict[str, Any]) -> None:
        # ack_timeout 注入：吞掉 finished 回执，制造超时/重试
        if stage == "finished" and self._ack_suppressed():
            logger.warning("【故障注入】ack_timeout：{} 的 finished 回执被丢弃", device_id)
            return
        payload = {
            "msg_id": f"ack-{int(time.time() * 1000) % 10**10}",
            "ref_msg_id": msg_id,
            "task_id": task_no,
            "device_id": device_id,
            "stage": stage,
            "result": result,
            "detail": detail,
            "ts": int(time.time()),
        }
        mqtt_client.publish(ACK_TOPIC.format(device_id=device_id), payload)

    # ------------------------------------------------------------ 三个设备的循环
    def _run_field(self) -> None:
        self._loop_device(DEV_FIELD, self._field_metrics, telemetry_s=30, status_s=15)

    def _run_soil(self) -> None:
        self._loop_device(DEV_SOIL, self._soil_metrics, telemetry_s=30, status_s=15)

    def _run_act(self) -> None:
        self._loop_device(DEV_ACT, self._act_metrics, telemetry_s=30, status_s=15)

    def _loop_device(self, device_id: str, metrics_fn, telemetry_s: int, status_s: int) -> None:
        next_tel = 0.0
        next_status = 0.0
        while not self._stop.is_set():
            try:
                now = time.time()
                if self._is_offline(device_id):
                    self._stop.wait(1.0)
                    continue
                if now >= next_status:
                    self._publish_status(device_id)
                    next_status = now + status_s
                if now >= next_tel:
                    self._publish_once(device_id, metrics_fn=metrics_fn)
                    next_tel = now + telemetry_s
            except Exception as exc:  # 线程绝不能静默死掉：死了遥控还在、遥测没了，最难排查
                logger.error("遥测循环 {} 异常（继续运行）：{}: {}", device_id, type(exc).__name__, exc)
            self._stop.wait(0.5)

    def _publish_status(self, device_id: str) -> None:
        payload = {
            "device_id": device_id,
            "online": True,
            "boot_id": self.boot_id,
            "rssi": -55 - random.randint(0, 12),
            "uptime_s": int(time.time() % 100000),
            "ts": int(time.time()),
        }
        mqtt_client.publish(STATUS_TOPIC.format(device_id=device_id), payload)

    def _publish_once(self, device_id: str, metrics_fn=None, force: bool = False) -> None:
        fn = metrics_fn or {
            DEV_FIELD: self._field_metrics,
            DEV_SOIL: self._soil_metrics,
            DEV_ACT: self._act_metrics,
        }[device_id]
        with self._lock:
            self.seq[device_id] += 1
            seq = self.seq[device_id]
            metrics = fn()
        payload = {
            "device_id": device_id,
            "ts": int(time.time()),
            "seq": seq,
            "boot_id": self.boot_id,
            "rssi": -55 - random.randint(0, 12),
            "metrics": metrics,
        }
        mqtt_client.publish(TELEMETRY_TOPIC.format(device_id=device_id), payload)
        logger.debug("【模拟设备】{} 上报 {} seq={}", device_id, metrics, seq)

    # ------------------------------------------------------------ 各设备指标模型
    def _jitter(self, value: float) -> float:
        if self.faults["sensor_jitter"]:
            return round(value * random.uniform(0.85, 1.15), 2)
        return round(value + random.uniform(-0.4, 0.4), 2)

    def _field_metrics(self) -> dict[str, float]:
        t = time.time()
        hour = time.localtime(t).tm_hour + time.localtime(t).tm_min / 60.0
        temp = 24 + 3 * math.sin((hour - 9) / 24 * 2 * math.pi)
        humidity = 60 + 10 * math.sin((hour - 3) / 24 * 2 * math.pi)
        day = max(0.0, math.sin((hour - 6) / 12 * math.pi))
        lux = 200 + 1050 * day + random.uniform(-30, 30)
        return {
            "temperature_c": self._jitter(round(temp, 1)),
            "humidity_air": self._jitter(round(humidity, 1)),
            "lux": round(max(0.0, lux), 0),
        }

    def _soil_metrics(self) -> dict[str, float]:
        self.soil.tick()
        moisture = self.soil.moisture
        if self.faults["dry_soil"]:
            moisture = min(moisture, 25.0)
        return {
            "soil_moisture": round(moisture if not self.faults["sensor_jitter"] else self._jitter(moisture), 2),
            "adc_raw": int(2870 - moisture * 12),
        }

    def _act_metrics(self) -> dict[str, float]:
        busy = max(0.0, self.act_busy_until - time.time())
        return {"relay_state": 1.0 if busy > 0 else 0.0, "remaining_s": round(busy, 1)}

    # ------------------------------------------------------------ 故障注入
    def _is_offline(self, device_id: str) -> bool:
        until = self.offline_until.get(device_id, 0.0)
        return until > time.time()

    def _ack_suppressed(self) -> bool:
        state = self.faults["ack_timeout"]
        now = time.time()
        if state.get("until", 0) > now:
            return True
        try:
            raw = get_redis().get(f"tea:fault:ack_timeout:{DEV_ACT}")
            if raw and float(raw) > now:
                return True
        except Exception:  # pragma: no cover
            pass
        return False

    def inject(self, fault: str, **kwargs) -> dict[str, Any]:
        """故障注入入口（设置页 / 命令行 / api/devices/fault 都走这里）。"""
        if fault not in FAULT_NAMES:
            raise ValueError(f"未知故障 {fault}，可选 {FAULT_NAMES}")
        now = time.time()
        with self._lock:
            if fault == "offline":
                device = kwargs.get("device") or DEV_SOIL
                seconds = int(kwargs.get("seconds", 120))
                self.offline_until[device] = now + seconds
                logger.warning("【故障注入】{} 静默 {}s", device, seconds)
            elif fault == "ack_timeout":
                self.faults["ack_timeout"]["until"] = now + int(kwargs.get("seconds", 60))
                logger.warning("【故障注入】接下来的指令不回 finished ack")
            elif fault == "dry_soil":
                self.faults["dry_soil"] = True
                self.soil.moisture = 25.0
                logger.warning("【故障注入】土壤湿度强制降到 25%")
            elif fault == "stuck_moisture":
                self.faults["stuck_moisture"] = True
                self.soil.stuck = True
                logger.warning("【故障注入】stuck_moisture 开启：浇水后湿度不上升（第 1 轮失败开关）")
            elif fault == "sensor_jitter":
                self.faults["sensor_jitter"] = True
                logger.warning("【故障注入】读数 ±15% 抖动（低置信度演示）")
        return self.state()

    def clear(self, fault: str | None = None) -> dict[str, Any]:
        with self._lock:
            if fault in (None, "offline"):
                self.offline_until.clear()
            if fault in (None, "ack_timeout"):
                self.faults["ack_timeout"]["until"] = 0
                try:
                    get_redis().delete(f"tea:fault:ack_timeout:{DEV_ACT}")
                except Exception:  # pragma: no cover
                    pass
            if fault in (None, "dry_soil"):
                self.faults["dry_soil"] = False
            if fault in (None, "stuck_moisture"):
                self.faults["stuck_moisture"] = False
                self.soil.stuck = False
            if fault in (None, "sensor_jitter"):
                self.faults["sensor_jitter"] = False
        logger.warning("【故障注入】已清除 {}", fault or "全部故障")
        return self.state()

    def set_weather(self, scenario: str) -> dict[str, Any]:
        if scenario not in WEATHER_PRESETS:
            raise ValueError(f"未知天气档位 {scenario}，可选 {list(WEATHER_PRESETS)}")
        self.weather = scenario
        try:
            get_redis().set(Keys.weather_scenario(), scenario)
        except Exception:  # pragma: no cover
            pass
        logger.info("【Mock 天气】切换为 {}", scenario)
        return self.state()

    def get_weather(self, city: str = "A区茶园", hours: int = 24) -> dict[str, Any]:
        preset = WEATHER_PRESETS.get(self.weather, WEATHER_PRESETS["sunny"])
        return {"city": city, "hours": hours, "scenario": self.weather, **preset}

    def state(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "devices": list(ALL_DEVICES),
            "weather": self.weather,
            "soil_moisture": round(self.soil.moisture, 2),
            "faults": {
                "offline": {k: max(0, round(v - time.time())) for k, v in self.offline_until.items()},
                "ack_timeout_until": round(self.faults["ack_timeout"].get("until", 0), 0),
                "dry_soil": self.faults["dry_soil"],
                "stuck_moisture": self.faults["stuck_moisture"],
                "sensor_jitter": self.faults["sensor_jitter"],
            },
        }


simulator = Simulator()


def get_weather(city: str = "A区茶园", hours: int = 24) -> dict[str, Any]:
    """PRD 7.3 工具池 get_weather 的 Mock 数据源（工具函数由队长实现，数据来源在这里）。"""
    return simulator.get_weather(city, hours)
