# 硬件实测日志（队友 C 每天记）

方案书里"真实数据"的来源，也是答辩时证明"我们真的跑过硬件"的证据。

**格式**：`日期 ｜ 板子 ｜ 实测读数（土壤湿度 / 空气温湿度 / 光照，写实际数字）｜ 问题与备注`

**要求**：

1. 每天至少一行，当天的事当天记；
2. 读数必须是板上实测，**不许编**；
3. 首次通电、首次浇水、土壤标定（干/湿基准）这几个关键节点必须单独记一行。

---

## 2026-11-10（D8）

- 日期：2026-11-10 ｜ 板子：三块（k10_field / esp32_soil / k10_act）｜ 实测读数：暂无（代码阶段）｜ 问题与备注：
  - 建立 `feature/firmware-three-boards` 分支，三板固件对齐 PRD 4.3 / 第 5 章完成：
    - 心跳 15s（RSSI + uptime）、遥测 30s、NTP Unix 时间戳、MQTT 指数退避重连（1s→30s）
    - k10_field：AHT20 温湿度 + 光照；AHT20 缺失时降级只报光照
    - esp32_soil：GPIO34 ADC 采样 10 次取中位数；干/湿标定 NVS 持久化
    - k10_act：GPIO1 继电器（低电平触发）、pump 120s 安全钳位、relay_off 紧急断开、ack 含实际执行秒数
  - 待办：三块板烧录 + MQTTX 验证（PRD 4.4 四条）；土壤传感器干/湿标定。

---

## 2026-11-17（真实硬件接入准备 + 全链路验证）

- 日期：2026-11-17 ｜ 板子：软件链路（真板未烧录）｜ 实测读数：探针模拟值（气象 24.6℃/63.2%/1250lux，土壤 38.5%/adc=2870）｜ 问题与备注：
  - **修复致命编译 bug**：三个 `platformio.ini` 原锁 `ArduinoJson @ ^7.0.0`，但固件用 `StaticJsonDocument`（v7 已移除）→ 编译必失败。已锁回 `^6.21.5`，代码无需改动。（来源：ArduinoJson v7 升级说明）
  - 核对三板配置：`firmware/*/include/config.h` 已是新 Broker `192.168.137.1:1883` + 账号 `tea`（密码见 .env），MQTT 主题全部对齐 `tea/device/{id}/...` 契约，与 docker compose 的 Mosquitto 一致。
  - 核对 DFRobot 库：`dfrobot/DFRobot_GDL`（可解析到 1.0.4）、`DFRobot_AHT20` 库名/API（`begin`/`startMeasurementReady`/`getTemperature_C`/`getHumidity_RH`）正确。
  - **新增联调探针** `firmware/tools/hw_probe.py`（依赖 paho-mqtt 2.1.0）：`sub` 监听 `tea/device/#`、`pub` 模拟三板上报、`cmd` 手动下发 pump 并等 ack。
  - **全链路实测通过**：`pub --once` 上报后 → `/api/sensor/latest` 返回 `k10-field-01`/`esp32-soil-02` 的 `online=true` 与真实 metrics；`/api/devices?is_mock=false` 三台真实设备 state 均为 online；前端 `http://localhost:5173` HTTP 200。证明「报文 → MQTT → 入库 → 前端大屏」链路已通，真板只要按同样报文上报即可显示。
  - 待办（真板到手后）：① PlatformIO 编译三工程（本机无 pio CLI，需在 VSCode 插件里编译）；② 烧录 + MQTTX/探针 `sub` 看真实心跳遥测；③ 土壤干/湿标定；④ K10 屏幕引脚（固件写 DC=13/CS=7/RST=14/BL=21）需按行空板 K10 实板核对，屏幕非闭环必需，显示异常不影响数据上报；⑤ 浇水闭环 `cmd` 实测 ack。
  - **交接队友 A**：前端 `useDashboard.ts` 的 `METRIC_LABEL` 写的是 `soil_raw`，而土壤固件/后端上报字段是 `adc_raw`（PRD 5.2 也是 `adc_raw`），导致详情卡漏显"原始值"。建议把 label 的 key 改为 `adc_raw`（前端地盘，队友 C 不越界修改）。

---

## 2026-11-17（补充：k10_rs485 方案 —— 队友实际接线与 PRD 不符）

- 日期：2026-11-17 ｜ 板子：一块行空板 K10 + MAX3485 + 两个 RS485 传感器 ｜ 实测读数：暂无（板子未烧录）｜ 问题与备注：
  - **关键发现**：队友当前实物是「一块 K10 + 气象(RS485,0x03) + 土壤(RS485,0x02) + MAX3485(已到货)」，与 PRD 的「三块板（板载 AHT20 / GPIO34 模拟土壤 / 继电器水泵）」不符。直接烧 `firmware/k10_field` 等三工程无效（它们不读 RS485，土壤 GPIO34 悬空会乱跳）。
  - **新增工程** `firmware/k10_rs485/`：一块 K10 通过 MAX3485(UART1, TX=IO16/RX=IO17) 读两个 RS485 传感器，Modbus 功能码 0x03，寄存器按 need.md §3.2（气象 0x01F8×8、土壤 0x0000×4），÷10 换算。
  - **一板两设备技巧**：后端按主题第 3 段取 device_id，故一块板发到两个主题即可让前端显示两台设备——气象→`k10-field-01`、土壤→`esp32-soil-02`；各发 status 心跳。
  - 含 CRC16、TX 回显剔除、reader 超时 300ms、指数退避重连、NTP 时间戳；ArduinoJson 锁 v6；遥测 10s / 心跳 15s。
  - 生成 `config.h`（复用旧项目已验证的 WiFi，SSID/密码只在本地 config.h，永不入库；MQTT 指向 `192.168.137.1`，账号 tea，密码见 .env）。
  - 编写 `firmware/k10_rs485/README.md`：接线表（★MAX3485 用 3.3V、★共地）、配置、烧录步骤、前端验证、7 类常见坑。
  - **报文格式实测**：将新固件会发的完整字段（含 pressure/wind_speed/noise/soil_temp）注入 MQTT → `/api/sensor/latest` 全部正确返回，前端可显示。
  - 待办（队友操作）：VSCode PlatformIO 打开 `firmware/k10_rs485` → Build → Upload → 串口确认 `[Weather]`/`[Soil]` 读数 → 前端看实时变化；读数回填本日志。

---

## 2026-11-18（排错续：最终用 USB-RS485 桥接跑通，真实数据已上前端）

- 日期：2026-11-18 ｜ 板子：PC + USB-RS485 转换器 + 两个 RS485 传感器 ｜ 实测读数：气象 26.2℃/65.4%/2134lux/101.5kPa，土壤 26.6℃/pH3.0（湿度0=探头未插土）｜ 问题与备注：
  - **踩坑链（重要经验）**：
    1. 板型错：一开始 `k10_rs485`/`k10_diag` 用 `espressif32:esp32-s3-devkitc-1`（No PSRAM），实际板子是 LNSF AIoT K10（有8MB PSRAM），程序启动即崩、连不上 MQTT。→ 改用 `platform=unihiker, board=unihiker_k10` 后，诊断固件(k10_diag)成功每2秒发 25.5℃，证明网络层 OK。
    2. MAX3485 自动方向模块不稳：正式固件(k10_rs485)用 MAX3485 读传感器，**每次上电仅第一次读到（21.7℃），之后全无响应**。诊断码 `w_err=0`（收字节=0）。试遍 TX 强制拉高、UART 每次 `end()/begin()` 复位、失败重试4次、间隔拉到5s——最多成功2次。根因=六脚自动方向模块方向切换锁死（need.md §3.6 同类问题），软件不可靠修复。
    3. retained 残留误导：诊断固件发的 25.5℃ 是 `retain=True`，每次订阅都收到，多次误判为"板子还在发"。已清空 `tea/device/{field,soil}/{telemetry,status}` 的 retained。
    4. 测试数据污染：早期多次注入假数据 + `-999` 读失败值共 3986 条污染 sensor_data，已从 MySQL 删除。
    5. CH340 端口僵死：`_test_read.py` 关闭 COM11 后 CH340 进入僵死态（PermissionError 13），必须物理重新插拔 USB 才恢复。**桥接脚本一旦启动就常驻，不再反复开关端口**。
  - **最终方案（已跑通）**：`firmware/tools/pc_bridge_tea.py`（复用旧项目 pc_bridge.py 已验证的 Modbus 读取逻辑），USB-RS485(CH340, COM11) 直读两传感器 → 按茶园契约上报 `tea/device/k10-field-01|esp32-soil-02/telemetry` + status 心跳，账号 tea（密码见 .env）。
  - 接线（need.md §3.3）：黄线→A、蓝线→B，两传感器并联；12V 供电不变；MAX3485 拆除不用。
  - **实测验证**：桥接常驻运行（PID 11164），每10秒一轮 seq 1001→1003 稳定递增；`/api/sensor/latest` 返回真实读数且 online=True、ts 实时更新；前端 http://localhost:5173 显示实时数据。目标达成。
  - 运行命令：`cd firmware/tools; python pc_bridge_tea.py COM11 --interval 10`（COM11 为 CH340 USB-RS485，重新插拔后确认）；日志 `bridge_out.log`/`bridge_err.log`。
  - 待办（若要恢复 ESP32 直连方案）：MAX3485 换带 DE/RE 手动方向控制的模块，或在 k10_rs485 固件里加方向脚控制；当前不影响主目标。

---

## 2026-11-18（续2：浇水执行端 k10-act 跑通 + 开机自启）

- 日期：2026-11-18 ｜ 板子：K10(无屏幕,LNSF定制) + 继电器 ｜ 实测：pump 6s，received+finished 两条ack齐全，executed_s=6 ｜ 备注：
  - **执行端固件改造** `firmware/k10_act/`：① 板型 `esp32-s3-devkitc-1`→`unihiker_k10`；② 移除全部 DFRobot_GDL 屏幕代码（该板无屏幕）；③ 继电器脚 GPIO1→**IO15**（GPIO1 在定制板上导致继电器抖动/滋滋声，IO15 是旧项目验证脚）。
  - **烧录端口大坑**：K10 原生 USB(VID_303A&PID_1001) 会随插拔变号。之前一直往失效的 COM10 烧录显示 SUCCESS 但实际没写入（板子一直跑旧固件，心跳只有 `{"online":true}`）。重新插拔后变 **COM12**，指定 `--upload-port COM12` 才真正烧进（日志出现 `Chip is ESP32-S3` + `MAC: 80:b5:4e:cd:42:f0` + `Hash verified`）。**教训：烧录必须确认日志有芯片MAC，且用当前 OK 状态的端口**。
  - **finished ack 丢失根因**（连查多轮）：
    1. 曾误加 `client.loop()` 到 send_ack（callback 内重入）→ 已删除；
    2. 真正根因：`serializeJson(doc, buffer)` 未用返回值，`client.publish(topic, buffer)` 按 C 字符串发送到 `\0`，finished（带 detail）尾部带随机字节 → 订阅端 `UnicodeDecodeError 0xa5` 乱码。修复：`size_t len=serializeJson(...); client.publish(topic, buffer, len);`（ack + status 都改），并加 `setBufferSize(768)`、ack msg_id 加递增序号防同毫秒去重。
  - **验证结果**：`pump 6s` → `[ACK] received done` + `[ACK] finished done {executed_s:6, clamped:false}`，PASS；pumping 状态 True→false 正确恢复；心跳每15s稳定。继电器动作正常（绿灯为电源灯常亮，非状态指示）。
  - **三机全在线**：k10-field-01 / esp32-soil-02（桥接）/ k10-act-03（K10执行端）全部 online=True。
  - 清理：`sensor_data` 删除诊断字段(w_ok/w_err/w_raw/s_ok/s_err/s_raw)及污染数据。
  - **开机自启**：`firmware/tools/start_bridge.bat`（异常退出10s重试），快捷方式已放入 Windows 启动文件夹 `茶园传感器桥接.lnk`。当前桥接 PID 13044 常驻 COM11。
  - 未接水泵（用户暂无）：继电器 COM/NO 空置，已证明控制链路通；水泵到货后独立 USB 电源接 COM/NO 即可出水。

---
