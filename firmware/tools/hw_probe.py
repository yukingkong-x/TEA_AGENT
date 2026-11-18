# firmware/tools/hw_probe.py
"""
硬件联调探针（队友 C）— 不烧录也能验证「报文 → MQTT → 入库 → 前端大屏」整条链路。

三种用途：
  1) sub    监听 tea/device/# 所有报文 —— 看真板是否上线、平台下发了什么指令
  2) pub    用真实设备 ID 模拟三块板发 telemetry/status —— 验证前端能显示真机数据
  3) cmd    手动向 k10-act-03 下发 pump 指令并等 ack —— 验证执行终端链路

依赖：pip install paho-mqtt==2.1.0
Broker：默认 localhost:1883，账号与口令同 .env（MQTT_USER / MQTT_PASSWORD）

用法示例：
  python hw_probe.py sub
  python hw_probe.py pub --once
  python hw_probe.py pub --seconds 60
  python hw_probe.py cmd --duration 5
"""
import argparse
import json
import sys
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    sys.exit("缺少 paho-mqtt，请先执行：pip install paho-mqtt==2.1.0")

BROKER = "localhost"
PORT = 1883
USER = "tea"
PASS = "change_me"  # 与 .env 的 MQTT_PASSWORD 一致

DEVICES = ["k10-field-01", "esp32-soil-02", "k10-act-03"]


def make_client():
    c = mqtt.Client(client_id=f"hw_probe_{int(time.time())}",
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set(USER, PASS)
    c.connect(BROKER, PORT, 60)
    c.loop_start()
    return c


def ts():
    return int(time.time())


# ---------- sub：监听所有设备报文 ----------
def run_sub():
    c = make_client()
    print("[SUB] 订阅 tea/device/#  ...（Ctrl+C 退出）", flush=True)

    def on_message(client, userdata, msg):
        try:
            body = json.loads(msg.payload.decode())
        except Exception:
            body = msg.payload.decode(errors="replace")
        print(f"[{time.strftime('%H:%M:%S')}] {msg.topic}  {json.dumps(body, ensure_ascii=False)}",
              flush=True)

    c.on_message = on_message
    c.subscribe("tea/device/#", qos=1)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        c.loop_stop()
        c.disconnect()


# ---------- pub：模拟三块板上报 ----------
def telemetry_payloads(seq):
    """字段与 PRD 5.2 / 固件 send_telemetry() 完全一致。"""
    return {
        "k10-field-01": {
            "device_id": "k10-field-01", "ts": ts(), "seq": seq, "rssi": -55,
            "metrics": {"temperature_c": 24.6, "humidity_air": 63.2, "lux": 1250},
        },
        "esp32-soil-02": {
            "device_id": "esp32-soil-02", "ts": ts(), "seq": seq, "rssi": -61,
            "metrics": {"soil_moisture": 38.5, "adc_raw": 2870},
        },
    }


def status_payload():
    return {"online": True, "rssi": -58, "uptime": 600}


def run_pub(once, seconds):
    c = make_client()
    start = time.monotonic()
    duration = 0 if once else seconds
    seq = 1000
    print(f"[PUB] 向 {BROKER}:{PORT} 上报（{'单次' if once else f'持续 {seconds}s'}）...", flush=True)
    try:
        while True:
            seq += 1
            # 心跳：让三台设备在前端显示 online
            for d in DEVICES:
                c.publish(f"tea/device/{d}/status", json.dumps(status_payload()), qos=1)
            # 遥测：气象 + 土壤（执行终端无遥测，只在 status 里带状态）
            for d, payload in telemetry_payloads(seq).items():
                c.publish(f"tea/device/{d}/telemetry", json.dumps(payload), qos=1)
            print(f"[{time.strftime('%H:%M:%S')}] 已上报一批 telemetry/status seq={seq}", flush=True)
            if once:
                break
            if duration and time.monotonic() - start >= duration:
                break
            time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        c.loop_stop()
        c.disconnect()
        print("[PUB] 结束", flush=True)


# ---------- cmd：手动下发 pump 指令 ----------
def run_cmd(duration):
    c = make_client()
    got_ack = []

    def on_message(client, userdata, msg):
        body = json.loads(msg.payload.decode())
        got_ack.append(body)
        print(f"[ACK] {msg.topic}  {json.dumps(body, ensure_ascii=False)}", flush=True)

    c.on_message = on_message
    c.subscribe("tea/device/k10-act-03/ack", qos=1)
    cmd = {
        "msg_id": f"cmd-probe-{int(time.time())}",
        "task_id": f"task-probe-{int(time.time())}",
        "action": "pump",
        "params": {"duration_s": duration},
        "issued_by": "agent:executor",
        "ts": ts(),
    }
    print(f"[CMD] 下发 pump {duration}s → k10-act-03/cmd", flush=True)
    c.publish("tea/device/k10-act-03/cmd", json.dumps(cmd), qos=1)
    deadline = time.time() + duration + 10
    while time.time() < deadline and len(got_ack) < 2:
        time.sleep(0.5)
    if not got_ack:
        print("[CMD] 未收到 ack —— 执行终端可能未在线（真板未烧录/未连 WiFi）", flush=True)
    c.loop_stop()
    c.disconnect()


def main():
    ap = argparse.ArgumentParser(description="茶园平台硬件联调探针")
    sub = ap.add_subparsers(dest="mode", required=True)

    sub.add_parser("sub", help="监听 tea/device/# 所有报文")

    p_pub = sub.add_parser("pub", help="模拟三块板上报 telemetry/status")
    p_pub.add_argument("--once", action="store_true", help="只上报一批就退出")
    p_pub.add_argument("--seconds", type=int, default=60, help="持续上报秒数（默认 60）")

    p_cmd = sub.add_parser("cmd", help="手动向 k10-act-03 下发 pump 指令")
    p_cmd.add_argument("--duration", type=int, default=5, help="浇水秒数（默认 5）")

    args = ap.parse_args()
    if args.mode == "sub":
        run_sub()
    elif args.mode == "pub":
        run_pub(args.once, args.seconds)
    elif args.mode == "cmd":
        run_cmd(args.duration)


if __name__ == "__main__":
    main()
