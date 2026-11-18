# k10_rs485 · 一块 K10 直读两个 RS485 传感器

> 目标（最小改动跑通）：一块行空板 K10 + MAX3485 + 你的两个 RS485 传感器，接到平台后在前端大屏看到**实时跳动的温湿度/土壤数据**。
> 一块板通过两个 MQTT 主题伪装成两个逻辑设备：`k10-field-01`（气象）、`esp32-soil-02`（土壤）。后端按主题第 3 段识别设备，前端会自动显示这两台设备的读数。

---

## 1. 接线（对照 need.md §3.3，已按你的实物调整）

### 电源（12V 适配器）
```
+12V ──→ 气象传感器 VCC
+12V ──→ 土壤传感器 VCC   （并联）
GND  ──→ 气象传感器 GND
GND  ──→ 土壤传感器 GND
GND  ──→ K10 GND          ★必须共地，否则 RS485 读数乱跳/读不到
```

### RS485 A/B（两个传感器并联在同一对线上）
```
气象传感器  黄线 ──→ MAX3485 A
气象传感器  蓝线 ──→ MAX3485 B
土壤传感器  黄线 ──→ MAX3485 A   （并联）
土壤传感器  蓝线 ──→ MAX3485 B   （并联）
```
> ⚠️ 若读不到数据，先对调 A/B（有些模块黄蓝定义相反）。

### MAX3485 ↔ K10（ESP32-S3）
```
MAX3485 VCC ──→ K10 3.3V   ★MAX3485 用 3.3V 供电（这是它解决 5V 不兼容的关键）
MAX3485 GND ──→ K10 GND
MAX3485 TXD ──→ K10 IO17   （config.h: RS485_RX_PIN=17）
MAX3485 RXD ──→ K10 IO16   （config.h: RS485_TX_PIN=16）
```
> 若你的 MAX3485 模块带 `DE/RE` 方向脚（非自动方向），需要额外接一个 GPIO 并在固件里控制——大部分市售"自动方向"模块无需此步。先按自动方向试，读不到再排查。

### 传感器地址（出厂已设好，无需再改）
```
气象传感器 = 0x03   （need.md：出厂 0x02 已改为 0x03）
土壤传感器 = 0x02   （默认）
波特率均为 9600
```

---

## 2. 配置（烧录前）

编辑 `include/config.h`（已从 `.example` 复制好，填的是旧项目验证过的参数）：

| 项 | 当前值 | 说明 |
| --- | --- | --- |
| `ssid` / `password` | （WiFi SSID/密码只在本地 config.h，永不入库） | 你之前用的本机热点，若换了 WiFi 就改这里 |
| `mqtt_server` | `192.168.137.1` | 跑 docker 的那台电脑的 IP；Windows 热点通常是这个。**不是** `127.0.0.1` |
| `mqtt_user` / `mqtt_password` | `tea` / `.env` 里的 MQTT_PASSWORD | 与 `.env` 一致 |
| `RS485_TX_PIN` / `RS485_RX_PIN` | `16` / `17` | 按上面接线 |
| `WEATHER_ADDR` / `SOIL_ADDR` | `0x03` / `0x02` | 传感器地址 |

**确认电脑 IP**：在电脑上 `ipconfig`，看你和板子同网的那块网卡 IP，填进 `mqtt_server`。板子 ping 不通这个 IP 就连不上 MQTT。

---

## 3. 编译 + 烧录（VSCode + PlatformIO）

1. VSCode 装 PlatformIO IDE 插件
2. 打开 folder：**这个文件所在的 `k10_rs485` 目录**（不是 firmware 根目录）
3. 底部状态栏点 **Build**（先编译，确认无报错；常见报错见第 6 节）
4. USB 数据线（不是充电线）连接 K10，点 **Upload**
   - 若报端口占用/超时：按住 K10 的 `BOOT` 键再点 Upload，进入下载模式
5. 点 **Serial Monitor**（115200），应看到：
```
[WiFi] connected ip=192.168.137.xx
[MQTT] connected
[CFG] RS485 TX=16 RX=17 UART1 @9600 | sensors 0x03/0x02
[Weather] 24.2C 79.3% 114lux 100.1kPa
[Soil] 38.5% 24.1C raw=385
[MQTT] field telemetry xxxB
[MQTT] soil telemetry xxxB
```

---

## 4. 验证前端显示

1. 浏览器打开 `http://localhost:5173`（若页面没起来：`docker compose --profile ui up -d`）
2. 大屏上 `k10-field-01`（巡园员一号）显示气温≈24.2℃，`esp32-soil-02`（土壤墒情节点）显示土壤湿度≈38.5%
3. 用手握住土壤探头 / 对气象传感器哈气，等 10s，看数值变化（遥测每 10s 上报一次）
4. 想看原始报文：
```
cd firmware/tools
python hw_probe.py sub        # 订阅 tea/device/#，实时打印所有上报
```
5. 想确认后端入库：
```
curl http://localhost:8000/api/sensor/latest
```

---

## 5. 前端显示的字段对应关系

| 设备（device_id） | 前端角色 | 主读数 | 详情字段 |
| --- | --- | --- | --- |
| `k10-field-01` | field 巡园员 | `temperature_c` 气温 | `humidity_air` 空气湿度、`lux` 光照 |
| `esp32-soil-02` | soil 土壤节点 | `soil_moisture` 土壤湿度 | `adc_raw`、`soil_temp` |

> 注：`pressure / wind_speed / noise` 后端会入库，但前端详情卡目前只显示前 3 个字段（队友 A 的地盘，需要可找他加）。

---

## 6. 常见坑（按出现顺序排查）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 编译报 `StaticJsonDocument is not a member of ArduinoJson` | ArduinoJson 版本不对 | `platformio.ini` 已锁 `^6.21.5`，确认没被改成 v7 |
| 串口一直 `[WiFi] connecting......` | WiFi 名称/密码错，或不在同网 | 核对 `config.h` 的 ssid/password |
| `[MQTT] connecting...` 一直失败 | `mqtt_server` 填错，或 docker 没起 | `ipconfig` 确认电脑 IP；`docker ps` 看 mosquitto 是否 up |
| `[RS485] no response` | A/B 接反 / 没共地 / 传感器没供电 / 地址不对 | 对调 A/B；确认 GND 共地；万用表量传感器 VCC=12V |
| 读到的值乱跳（如湿度 300%） | 寄存器换算错 / 波特率不对 / 没共地 | 本固件已按 need.md ÷10 换算；确认 9600 和共地 |
| 前端设备灰色离线 | 心跳没上来 / last_seen 超 45s | 看串口有没有 `[MQTT] status x2`；用 `hw_probe.py sub` 看 status 报文 |
| 土壤传感器读数一直是 0 | 探头没插土（need.md 实测未插土就是 0.0） | 插进土里或捏湿纸巾贴探头再测 |

---

## 7. 安全提醒

- MAX3485 用 **3.3V**，别接 5V（接 5V 就退回不兼容问题了）
- 12V 只给传感器，别接到 K10
- 后续接继电器+水泵时，水泵用独立 USB 电源，不从 K10 取电

---

## 8. 已验证 / 未验证

- ✅ 固件报文格式：`pressure/temperature_c/humidity_air/lux/wind_speed/noise` 与 `soil_moisture/adc_raw/soil_temp` 注入后，`/api/sensor/latest` 全部正确返回，前端可显示
- ✅ ArduinoJson 版本、DFRobot 库名、MQTT 账号主题对齐
- ⬜ 真板编译/烧录/串口实测（需你在 VSCode 操作）
- ⬜ MAX3485 实物接线与读数（板子到手后实测，读数记入 `docs/hardware_log.md`）
