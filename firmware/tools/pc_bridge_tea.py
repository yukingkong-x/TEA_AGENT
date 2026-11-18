# firmware/tools/pc_bridge_tea.py
"""
茶园平台 PC 端传感器桥接器（复用深渊哨兵已验证的读取逻辑）。

USB-RS485 转换器直读两个传感器 → 按茶园 MQTT 契约上报：
  气象 -> tea/device/k10-field-01/telemetry (role=field)
  土壤 -> tea/device/esp32-soil-02/telemetry (role=soil)
  心跳 -> 两个设备的 status

用法：
  python pc_bridge_tea.py COM11
  python pc_bridge_tea.py COM11 --interval 10      # 每10秒一轮（默认10s）
依赖：pyserial, paho-mqtt==2.1.0
"""
import sys
import time
import json
import argparse
import serial
import paho.mqtt.client as mqtt

BROKER, PORT = "localhost", 1883
USER, PASS = "tea", "change_me"  # 与 .env 的 MQTT_USER / MQTT_PASSWORD 一致
DEV_FIELD, DEV_SOIL = "k10-field-01", "esp32-soil-02"
WIND_NAMES = {0:"无风",1:"1级",2:"2级",3:"3级",4:"4级",5:"5级",6:"6级",7:"7级",8:"8级",9:"9级",10:"10级",11:"11级",12:"12级"}


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def modbus_read(ser, addr, reg, count):
    f = bytearray(8)
    f[0]=addr; f[1]=0x03; f[2]=(reg>>8)&0xFF; f[3]=reg&0xFF; f[4]=0; f[5]=count
    c = crc16(f[:6]); f[6]=c&0xFF; f[7]=(c>>8)&0xFF
    ser.reset_input_buffer()
    ser.write(bytes(f))
    time.sleep(0.2)
    resp = ser.read(256)
    if len(resp) < 5 or resp[0] != addr or (resp[1] & 0x80):
        return None
    bc = resp[2]
    if len(resp) < 3 + bc + 2:
        return None
    if crc16(resp[:3+bc]) != (resp[3+bc] | (resp[3+bc+1] << 8)):
        return None
    return [(resp[3+i] << 8) | resp[4+i] for i in range(0, bc, 2)]


def main():
    ap = argparse.ArgumentParser(description="茶园平台 USB-RS485 传感器桥接")
    ap.add_argument("port", nargs="?", default="COM11", help="串口号，如 COM11")
    ap.add_argument("--interval", type=int, default=10, help="上报间隔秒数（默认10）")
    args = ap.parse_args()

    print(f"[Bridge] 打开串口 {args.port} ...", flush=True)
    try:
        ser = serial.Serial(args.port, baudrate=9600, timeout=1)
    except Exception as e:
        sys.exit(f"[Bridge] 无法打开 {args.port}: {e} —— 检查端口/重新插拔 USB")

    c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set(USER, PASS)
    c.connect(BROKER, PORT, 60)
    c.loop_start()
    print(f"[Bridge] MQTT 已连接 {BROKER}:{PORT}", flush=True)

    seq = 1000
    try:
        while True:
            seq += 1
            w = modbus_read(ser, 0x03, 0x01F8, 8)
            time.sleep(0.15)
            s = modbus_read(ser, 0x02, 0x0000, 4)
            now = int(time.time())

            # 气象设备
            if w:
                field = {
                    "device_id": DEV_FIELD, "ts": now, "seq": seq, "rssi": -50,
                    "metrics": {
                        "temperature_c": w[1]*0.1, "humidity_air": w[0]*0.1,
                        "lux": float(w[7]), "pressure": w[5]*0.1,
                        "wind_speed": w[3]*0.1, "noise": w[2]*0.1,
                        "wind_dir": float(w[4]),
                        "wind_power": WIND_NAMES.get(int(w[6]), f"{int(w[6])}级"),
                    },
                }
                c.publish(f"tea/device/{DEV_FIELD}/telemetry", json.dumps(field), qos=1)

            # 土壤设备
            if s:
                soil = {
                    "device_id": DEV_SOIL, "ts": now, "seq": seq, "rssi": -50,
                    "metrics": {
                        "soil_moisture": s[0]*0.1, "soil_temp": s[1]*0.1,
                        "soil_ec": float(s[2]), "soil_ph": s[3]*0.1,
                        "adc_raw": s[0],
                    },
                }
                c.publish(f"tea/device/{DEV_SOIL}/telemetry", json.dumps(soil), qos=1)

            # 心跳
            hb = json.dumps({"online": True, "rssi": -50, "uptime": int(time.time())})
            c.publish(f"tea/device/{DEV_FIELD}/status", hb, qos=1)
            c.publish(f"tea/device/{DEV_SOIL}/status", hb, qos=1)

            t = f"{w[1]*0.1:.1f}C/{w[0]*0.1:.1f}%/{float(w[7]):.0f}lux" if w else "读失败"
            sm = f"{s[0]*0.1:.1f}%" if s else "读失败"
            print(f"[{time.strftime('%H:%M:%S')}] 气象={t} 土壤={sm} seq={seq}", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[Bridge] 停止")
    finally:
        ser.close()
        c.loop_stop()
        c.disconnect()
        print("[Bridge] 已退出")


if __name__ == "__main__":
    main()
