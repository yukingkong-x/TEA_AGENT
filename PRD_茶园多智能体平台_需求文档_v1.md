# 茶园多智能体编排平台 · 产品需求文档（PRD）

> **版本**：v1.1 ｜ **日期**：2026-11-09 ｜ **状态**：施工级（可直接开发）
>
> **关于项目名**：项目正式名称未定，本文档统一使用临时代号 **「知秋」（zhiqiu）**。定名后全局替换即可，不影响任何技术内容。
>
> **本文档的两种读法**：
>
> - **人类读法**：按顺序读第 1-3 章了解全貌，第 13-15 章看界面和演示效果，第 17 章看排期分工。
> - **Claude（AI 助手）读法**：本文档所有需求都有编号（如 `REQ-F-013`）。开发时请用如下方式下达任务："按 REQ-F-013 实现调度器，验收标准见该条目"。每个需求条目自带验收标准（DoD），完成一个核对一个。

---

## 目录

1. [项目概述](#1-项目概述)
2. [名词表（先看这个，人话解释）](#2-名词表)
3. [总体架构](#3-总体架构)
4. [硬件规格与接线（三块板）](#4-硬件规格与接线)
5. [数据与通信契约（MQTT 主题与报文）](#5-数据与通信契约)
6. [数据库设计（MySQL 全表结构）](#6-数据库设计)
7. [后端规格（FastAPI）](#7-后端规格)
8. [七个 Agent 完整规格（含提示词全文）](#8-七个-agent-规格)
9. [工作流引擎规格（DAG）](#9-工作流引擎规格)
10. [调度器规格（动态调度）](#10-调度器规格)
11. [验证引擎规格（Self-Loop 核心）](#11-验证引擎规格)
12. [Mock / Real 双模式](#12-mock--real-双模式)
13. [前端规格（六个页面）](#13-前端规格)
14. [UI 设计规范（深色大屏风）](#14-ui-设计规范)
15. [端到端演示剧本（含两轮对照实验）](#15-端到端演示剧本)
16. [需求编号总表与验收标准](#16-需求编号总表与验收标准)
17. [排期与四人分工](#17-排期与四人分工)
18. [Git 与协作规范](#18-git-与协作规范)
19. [环境搭建指南](#19-环境搭建指南)
20. [风险与预案](#20-风险与预案)
21. [附录（配置文件与视频分镜）](#21-附录)

---

# 1. 项目概述

## 1.1 一句话定位

一个 **多智能体（Multi-Agent）编排调度平台**，落地在茶园灌溉场景，用 **"决策 → 真实浇水 → 传感器复测 → 达成率验证 → 自动修正"** 的物理闭环，证明 Agent 的决策在真实世界中有效。

## 1.2 参赛背景

- 比赛：2026 第五届"未来杯"创新大赛（中软卓越杯体系），赛题"Agent 编排创新应用"
- 对标对象：LobeHub、DeepSeek Harness 等主流 Agent Harness 框架
- 考察点：知识库定义与集成、Agent 团队定义、工作流编排、动态调度、Self-Loop、结果验证与反馈优化
- 交付物：≥5000 字方案书 PDF、10-15 页 PPT、3-5 分钟视频、可运行代码仓库
- 三条红线：可运行原型 ✅ Docker 一键启动；真多智能体 ✅ 7 个 Agent 协作；Self-Loop ✅ 物理闭环

## 1.3 项目目标（按优先级）

| 优先级 | 目标           | 衡量标准                                                                 |
| ------ | -------------- | ------------------------------------------------------------------------ |
| P0     | 核心闭环可演示 | 点一次"开始巡园"，完成 感知→开会→决策→真浇水→复测→达成率报告 全流程 |
| P0     | 初赛三件套     | 方案书 / PPT / 视频 达到可提交质量                                       |
| P1     | 平台能力完整   | 知识库管理页、串并行对比、Mock/Real 切换                                 |
| P2     | 云端部署       | 阿里云 2核4G 可访问，长期运行证据                                        |

## 1.4 设计原则（给 Claude 的施工约束）

1. **模型无关**：所有 LLM 调用走 OpenAI 兼容接口，`GLM-4-Flash`（主力，免费）与 `DeepSeek-chat`（备用）通过 `.env` 一键切换。
2. **Mock/Real 一键切换**：一个全局开关决定数据来自模拟器还是真实硬件，上层代码完全无感。
3. **权限分离**：7 个 Agent 中只有「执行管家」绑定了下发设备指令的工具，其余 Agent 的任何决策都不能直接触碰硬件。
4. **决策与验证分离**：决策由「灌溉决策官」做出，验证由「验证审计官」独立完成，二者不共享决策上下文。
5. **一切可观测**：每一条消息、每一次工具调用、每一次状态变更都落库，前端全程可视化。
6. **参数皆可配**：本文档中所有阈值、权重、间隔均定义为配置项（settings 表或 .env），不写死在代码里。

---

# 2. 名词表

| 名词                          | 人话解释                                                                                                       |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Agent（智能体）**     | 一个有人设、有专属工具、有记忆的 AI 员工。本项目共 7 个，各有分工。                                            |
| **Harness（挽具）**     | 包住大模型的那层"骨架"：工具调用、上下文管理、执行循环。马是模型，挽具是缰绳和马鞍。                           |
| **MQTT**                | 设备之间传消息的轻量协议，像"快递驿站"：所有设备往驿站发件/取件，互不直连。                                    |
| **Mosquitto**           | 那个"驿站"软件本身，开源免费，跑在 Docker 里。                                                                 |
| **DAG**                 | 有向无环图。工作流的数学形态：任务 A 完成 → 触发 B 和 C 并行 → 都完成 → 触发 D。                            |
| **Self-Loop（自循环）** | 系统自己闭环改进：做完事 → 检查效果 → 不达标自己修正 → 再做。本项目的独门武器是让**物理世界当裁判**。 |
| **RAG（检索增强生成）** | 让 AI 回答前先去知识库里翻资料，回答时标注引用了哪条，减少瞎编。                                               |
| **MCP**                 | Model Context Protocol， Anthropic 发起的工具接入协议，Agent 接工具的"USB 标准"。本项目工具层兼容此协议。      |
| **达成率**              | 本项目的核心指标：任务执行后，实测值向目标值靠拢的程度，0-100%。                                               |
| **置信度**              | 对"这个结果可信吗"的打分，由三路证据加权算出，低于 60% 转人工。                                                |
| **Mock / Real**         | 模拟模式 / 真实模式。Mock 用软件假装硬件，Real 用真板子。一键切换。                                            |
| **PlatformIO**          | VSCode 里的嵌入式开发插件，用来给三块板子写代码、编译、烧录。                                                  |
| **继电器**              | 用小电流指挥大电流的开关。板子 GPIO 信号 → 继电器 → 水泵电源通断。                                           |
| **指数退避**            | 失败重试的等待策略：第 1 次失败等 2s，第 2 次等 4s，第 3 次等 8s，避免雪崩。                                   |
| **熔断**                | 连续失败太多次后，暂时"拉黑"该设备几分钟，防止无意义重试。                                                     |

---

# 3. 总体架构

## 3.1 架构图

```
┌─────────────────────────── 浏览器（评委/用户） ───────────────────────────┐
│   React 前端：大屏 / 画布 / 对话剧场 / 任务中心 / 报告 / 设置              │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │ HTTP(REST) + WebSocket(实时推送)
┌──────────────────────────────▼───────────────────────────────────────────┐
│                     FastAPI 后端（核心，所有智能在这里）                    │
│                                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ 7个Agent │ │ 工作流引擎 │ │ 调度器    │ │ 验证引擎  │ │ 工具池(MCP兼容)│  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬────────┘  │
│       │            │            │            │              │           │
│  ┌────▼────────────▼────────────▼────────────▼──────────────▼────────┐  │
│  │                    LLM 接入层（GLM-4-Flash / DeepSeek）             │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└───────┬──────────────┬───────────────┬──────────────┬───────────────────┘
        │              │               │              │
   ┌────▼────┐    ┌────▼────┐     ┌────▼────┐   ┌────▼─────┐
   │ MySQL   │    │ Redis   │     │ Mosquitto│   │  Chroma  │
   │ 业务数据 │    │ 缓存/队列│     │ (MQTT)   │   │ 知识库RAG │
   └─────────┘    └─────────┘     └────┬─────┘   └──────────┘
                                       │ WiFi
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
             ┌──────▼──────┐   ┌──────▼───────┐   ┌──────▼──────┐
             │ K10一号      │   │ ESP32-E      │   │ K10二号      │
             │ 环境巡园员   │   │ 土壤墒情节点   │   │ 执行终端      │
             │ 板载温湿/光照 │   │ 外接土壤传感器 │   │ 继电器→水泵   │
             └─────────────┘   └──────────────┘   └─────────────┘
                          （Mock 模式下三个设备 = simulator/ 里的假设备）
```

## 3.2 技术栈（锁定，不换）

| 层         | 选型                                        | 说明                             |
| ---------- | ------------------------------------------- | -------------------------------- |
| 后端框架   | Python 3.11 + FastAPI + uvicorn             | 异步、自动生成 API 文档（/docs） |
| ORM        | SQLAlchemy 2.x + PyMySQL                    | MySQL 8.0                        |
| 缓存/队列  | Redis 7                                     | 任务队列、实时状态缓存、分布式锁 |
| 消息总线   | eclipse-mosquitto 2.x（MQTT 3.1.1）         | paho-mqtt 客户端                 |
| 向量库     | Chroma（独立容器）                          | RAG 知识库                       |
| LLM        | GLM-4-Flash（主）+ DeepSeek-chat（备）      | OpenAI SDK 兼容模式              |
| 前端       | React 18 + Vite + TypeScript + Tailwind CSS | SPA                              |
| 工作流画布 | React Flow (@xyflow/react)                  | 拖拽编排 + 执行动画              |
| 图表       | ECharts                                     | 曲线、仪表盘、圆环               |
| 定时任务   | APScheduler                                 | 周期巡园触发                     |
| 部署       | Docker Compose                              | 一键启动全部 6 个服务            |
| 固件       | PlatformIO + Arduino 框架                   | K10=ESP32-S3，ESP32-E=ESP32      |
| 协议兼容   | 工具层暴露 MCP Server（SSE）                | 赛题关键词，加分项               |

## 3.3 数据流总览（一次巡园的消息旅程）

```
传感器 → MQTT(telemetry) → 后端入库 → 工作流引擎触发
  → 巡园管家汇总 → 并行派发 气象员/土壤师/植保员
  → 灌溉决策官拍板(浇水30s) → 调度器打分选派 → 执行管家
  → MQTT(cmd) → K10二号 → 继电器闭合 → 水泵出水 30s
  → 等待渗透(90s) → MQTT(telemetry) 复测数据
  → 验证引擎算达成率 → 验证审计官出具报告
  → 达成率<60%？→ 是：反馈修正 → 生成新任务（Self-Loop）
                → 否：闭环成功 → 日报
```

---

# 4. 硬件规格与接线

## 4.1 设备清单与角色

| 设备          | 设备ID            | 角色         | 板载/外接                                 | 主要动作                                                         |
| ------------- | ----------------- | ------------ | ----------------------------------------- | ---------------------------------------------------------------- |
| 行空板 K10 ① | `k10-field-01`  | 环境巡园员   | 板载 AHT20 温湿度 + 光照传感器 + 2.4 寸屏 | 每 30s 上报遥测；屏幕滚动显示当前读数与在线状态                  |
| ESP32-E       | `esp32-soil-02` | 土壤墒情节点 | 外接 土壤湿度传感器（模拟输出 AO）        | 每 30s 上报土壤湿度；支持标定模式                                |
| 行空板 K10 ② | `k10-act-03`    | 执行终端     | GPIO → 1 路继电器 → USB 小水泵          | 接收浇水指令；执行继电器通断；屏幕显示执行状态；每次动作上报 ack |

> 注：K10 具体板载传感器型号以 I2C 扫描实测为准（预期为 AHT20，地址 0x38）。若个别传感器不可用，固件降级为只上报可用项，平台不受影响。

## 4.2 接线表（队友 C 照此接线）

### ESP32-E（土壤节点）

| 传感器引脚         | ESP32-E 引脚       | 说明                                  |
| ------------------ | ------------------ | ------------------------------------- |
| 土壤传感器 VCC     | 3V3                | 电容式/电阻式均可                     |
| 土壤传感器 GND     | GND                | 共地                                  |
| 土壤传感器 AO      | GPIO 34 (ADC1_CH7) | 模拟输入，34 号脚只能做输入，勿接其他 |
| （可选）DHT11 DATA | GPIO 4             | 若有 DHT11 可加，没有就不接           |

### K10二号（执行终端）

| 继电器引脚 | K10 引脚                       | 说明                                                     |
| ---------- | ------------------------------ | -------------------------------------------------------- |
| 继电器 VCC | 5V                             | K10 的 5V 输出                                           |
| 继电器 GND | GND                            | 共地                                                     |
| 继电器 IN  | GPIO 1                         | **低电平触发**（多数常见模块），固件里注意逻辑取反 |
| 继电器 COM | 水泵电源正极（USB 线红线剥开） | 串入回路                                                 |
| 继电器 NO  | 水泵（另一端）                 | 常开触点：给信号才闭合                                   |

> **供电安全三条铁律**：① 水泵用**独立 USB 电源**供电（手机充电头即可），不要从 K10 的 5V 取电（USB 口带不动感性负载，会重启）；② 继电器触点是物理隔离的，控制回路与水泵回路天然隔离，不会互相干扰；③ 所有测试在水杯中进行，垫纸巾，首次通水时队友 C 全程在场。

### K10一号（巡园员）

无需接线（全部板载），只需 WiFi 配置。

## 4.3 固件行为规格（PlatformIO，Arduino 框架）

三个独立工程：`firmware/k10_field`、`firmware/esp32_soil`、`firmware/k10_act`。共同行为：

1. **开机**：连 WiFi（SSID/密码写在固件配置区，编译前填）→ 连 MQTT（地址/账号见 .env 同步修改）→ 订阅自己的 cmd 主题 → 上线即向 `status` 主题发一条 `{"online": true}`。
2. **心跳**：每 15s 发一次 `status`（含 RSSI 信号强度、运行秒数）。
3. **遥测**：每 30s 发一次 `telemetry`（报文格式见第 5 章）。
4. **命令**：收到 `cmd` 先回 `ack`（received），执行完再回 `ack`（done / failed + 原因）。
5. **离线重连**：MQTT 断线自动重连（指数退避 1s/2s/4s/...上限 30s），WiFi 断线自动重连。
6. **屏幕**：K10 两块板的屏幕显示：设备名、在线状态点（绿闪/灰）、最新读数或执行状态、IP 地址。字体大小以 1 米外可读为准。

### k10-field 固件专属

- 读取 AHT20（温度 ℃、湿度 %RH）与光照（lux），打包上报。
- 收到 `cmd: read_now` 立即补测一次上报（供复测场景使用）。

### esp32-soil 固件专属

- ADC 采样 10 次取中位数 → 按标定曲线换算为湿度百分比 0-100%。
- **标定流程**：收到 `cmd: calibrate_dry` 时把当前 ADC 原始值存为"干燥基准"（写入 NVS 持久化）；`calibrate_wet` 存"湿润基准"。线性映射：干=0%，湿=100%。**首次烧录后必须做一次标定**。
- 收到 `cmd: read_now` 立即补测上报。

### k10-act 固件专属

- 收到 `cmd: pump` + 参数 `{"duration_s": 30}`：屏幕显示"浇水中 剩余Ns"→ 继电器闭合 → 倒计时 → 断开 → 回 ack done（含实际执行秒数）。
- 安全阀：单次 duration_s 最大 120s，超过按 120s 执行并在 ack 中标注 `clamped: true`。
- 收到 `cmd: relay_off`：紧急断开（人工救援通道）。
- 屏幕常显"待命"。

## 4.4 固件验收标准

- [ ] 三块板在 MQTTX 工具里能看到心跳与遥测
- [ ] MQTTX 手动向 `k10-act-03/cmd` 发 `{"action":"pump","duration_s":3}`，水泵转 3 秒并收到两条 ack
- [ ] 拔掉任一板子电源 ≥60s 再上电，平台侧能看到 offline→online 状态变化
- [ ] 土壤传感器标定后，干土读数 <10%，捏湿纸巾贴住探头读数 >85%

---

# 5. 数据与通信契约

## 5.1 MQTT 主题规划（全表）

| 方向 | 主题                                 | 发布者   | 说明                                 |
| ---- | ------------------------------------ | -------- | ------------------------------------ |
| 上行 | `tea/device/{device_id}/telemetry` | 设备     | 遥测数据（每 30s）                   |
| 上行 | `tea/device/{device_id}/status`    | 设备     | 心跳/在线状态（每 15s）              |
| 上行 | `tea/device/{device_id}/ack`       | 设备     | 指令回执（收到时 + 完成时各一条）    |
| 下行 | `tea/device/{device_id}/cmd`       | 平台     | 指令下发                             |
| 下行 | `tea/cmd/{task_id}`                | 平台     | 带任务号的指令（主流通道，用于追踪） |
| 双向 | `tea/agent/bus`                    | 后端内部 | Agent 消息总线（调试用，QoS0）       |

约定：QoS 全部用 1（至少一次），后端以 `task_id` + `msg_id` 做幂等去重。所有报文 JSON UTF-8。

## 5.2 遥测报文（telemetry）

```json
{
  "device_id": "k10-field-01",
  "ts": 1730700000,
  "seq": 1024,
  "rssi": -58,
  "metrics": {
    "temperature_c": 24.6,
    "humidity_air": 63.2,
    "lux": 1250
  }
}
```

```json
{
  "device_id": "esp32-soil-02",
  "ts": 1730700000,
  "seq": 987,
  "rssi": -61,
  "metrics": {
    "soil_moisture": 38.5,
    "adc_raw": 2870
  }
}
```

字段说明：`ts` 为设备 Unix 时间戳（秒）；`seq` 自增序号，后端用于去重与断点检测；`metrics` 只包含该设备能提供的键，允许缺键不允许错型。

## 5.3 指令报文（cmd）

```json
{
  "msg_id": "cmd-20261103-0001",
  "task_id": "task-20261103-0007",
  "action": "pump",
  "params": { "duration_s": 30 },
  "issued_by": "agent:executor",
  "ts": 1730700100
}
```

支持的 action 全集：`pump`（浇水，参数 duration_s）、`read_now`（立即补测）、`relay_off`（紧急断开）、`calibrate_dry` / `calibrate_wet`（仅土壤节点）、`reboot`（设备重启，救援用）。

## 5.4 回执报文（ack）

```json
{
  "msg_id": "ack-20261103-0501",
  "ref_msg_id": "cmd-20261103-0001",
  "task_id": "task-20261103-0007",
  "device_id": "k10-act-03",
  "stage": "received",
  "result": "done",
  "detail": { "executed_s": 30, "clamped": false },
  "ts": 1730700131
}
```

`stage`：`received`（已收到）或 `finished`（已执行完）；`result`：`done` / `failed` / `rejected`。后端收到 `received` 后启动执行超时计时，收到 `finished` 后进入验证流程。

## 5.5 心跳与离线判定

- 设备每 15s 发 `status`；后端 Redis 写 `device:{id}:last_seen`。
- **在线判定**：`now - last_seen ≤ 45s` 在线；45-120s 疑似离线（界面黄色）；>120s 判定离线（灰色 + 报警）。

---

# 6. 数据库设计（MySQL 8，库名 `zhiqiu`，utf8mb4）

> 所有表含 `created_at` / `updated_at`（DATETIME，默认 CURRENT_TIMESTAMP），下表不再重复列出。主键统一 `id BIGINT AUTO_INCREMENT`。

## 6.1 devices 设备表

| 字段        | 类型                            | 说明                                 |
| ----------- | ------------------------------- | ------------------------------------ |
| device_id   | VARCHAR(32) UNIQUE              | 如 k10-field-01                      |
| name        | VARCHAR(64)                     | 显示名：巡园员一号                   |
| role        | ENUM('field','soil','actuator') | 角色                                 |
| location    | VARCHAR(64)                     | A 区茶垄                             |
| is_mock     | BOOLEAN                         | 是否模拟设备                         |
| online      | BOOLEAN                         | 冗余在线状态（Redis 为准，定时回写） |
| last_seen   | DATETIME                        | 最后心跳时间                         |
| config_json | JSON                            | 采样间隔、标定基准等                 |

## 6.2 sensor_data 遥测表（分区按月或按 id 范围，量最大）

| 字段      | 类型          | 说明                                               |
| --------- | ------------- | -------------------------------------------------- |
| device_id | VARCHAR(32)   | 索引                                               |
| metric    | VARCHAR(32)   | temperature_c / humidity_air / lux / soil_moisture |
| value     | DECIMAL(10,2) | 数值                                               |
| raw       | JSON          | 原始报文                                           |
| ts        | DATETIME      | 设备时间戳，索引 (device_id, metric, ts)           |

## 6.3 agents Agent 配置表（REQ-F-002：Agent 团队定义）

| 字段          | 类型               | 说明                                                           |
| ------------- | ------------------ | -------------------------------------------------------------- |
| agent_key     | VARCHAR(32) UNIQUE | scout / weather / soil / pest / decision / executor / verifier |
| name          | VARCHAR(32)        | 巡园管家                                                       |
| avatar        | VARCHAR(8)         | emoji 或图标名                                                 |
| system_prompt | TEXT               | 人设全文（见第 8 章，可在设置页修改）                          |
| tools_json    | JSON               | 绑定工具名列表                                                 |
| model         | VARCHAR(64)        | 默认取全局配置，可覆盖                                         |
| temperature   | DECIMAL(3,2)       | 默认 0.3，决策官 0.2，植保员 0.4                               |
| enabled       | BOOLEAN            | 停用开关                                                       |

## 6.4 workflows 工作流定义表

| 字段     | 类型               | 说明                              |
| -------- | ------------------ | --------------------------------- |
| wf_key   | VARCHAR(32) UNIQUE | patrol_irrigation（标准巡园浇水） |
| name     | VARCHAR(64)        | 巡园浇水工作流                    |
| dag_json | JSON               | 节点与边（见第 9 章 schema）      |
| version  | INT                | 每次保存 +1                       |
| enabled  | BOOLEAN            |                                   |

## 6.5 workflow_runs 执行实例表

| 字段                     | 类型                                                                  | 说明                                 |
| ------------------------ | --------------------------------------------------------------------- | ------------------------------------ |
| wf_id                    | BIGINT                                                                | 来源工作流                           |
| status                   | ENUM('pending','running','success','failed','canceled','needs_human') | 状态机                               |
| trigger                  | VARCHAR(32)                                                           | manual / schedule / event / selfloop |
| context_json             | JSON                                                                  | 全局上下文（各节点读写）             |
| started_at / finished_at | DATETIME                                                              | 计时                                 |

## 6.6 tasks 任务表（调度器核心）

| 字段            | 类型                                                                                             | 说明                                                 |
| --------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| task_no         | VARCHAR(32) UNIQUE                                                                               | task-20261103-0007                                   |
| run_id          | BIGINT                                                                                           | 所属执行实例                                         |
| type            | VARCHAR(32)                                                                                      | agent_call / device_cmd / verify / report / selfloop |
| payload_json    | JSON                                                                                             | 任务参数                                             |
| priority        | INT                                                                                              | 1-10                                                 |
| score           | DECIMAL(6,2)                                                                                     | 调度打分                                             |
| status          | ENUM('pending','dispatched','running','success','failed','timeout','retrying','dead','canceled') | 状态机见 10.2                                        |
| assigned_agent  | VARCHAR(32)                                                                                      | 接单 Agent                                           |
| assigned_device | VARCHAR(32)                                                                                      | 目标设备                                             |
| retry_count     | INT                                                                                              | 已重试次数（上限 3）                                 |
| timeout_s       | INT                                                                                              | 超时秒数                                             |
| deadline_at     | DATETIME                                                                                         | 时间窗                                               |
| result_json     | JSON                                                                                             | 执行结果                                             |

## 6.7 agent_messages Agent 对话记录（对话剧场数据源）

| 字段                   | 类型                                     | 说明                         |
| ---------------------- | ---------------------------------------- | ---------------------------- |
| run_id                 | BIGINT                                   | 索引                         |
| agent_key              | VARCHAR(32)                              | 发言者                       |
| role                   | ENUM('user','assistant','tool','system') | 消息角色                     |
| content                | TEXT                                     | 文本内容                     |
| tool_calls_json        | JSON                                     | 工具调用与返回（可折叠展示） |
| citations_json         | JSON                                     | 引用的知识库条目 id 数组     |
| tokens_in / tokens_out | INT                                      | 计费统计                     |
| latency_ms             | INT                                      | 本轮耗时                     |

## 6.8 decisions 决策记录

| 字段          | 类型         | 说明                                                                      |
| ------------- | ------------ | ------------------------------------------------------------------------- |
| run_id        | BIGINT       |                                                                           |
| decision_type | VARCHAR(32)  | irrigate / none / escalate                                                |
| summary       | VARCHAR(255) | A 区缺水，建议浇水 30 秒                                                  |
| params_json   | JSON         | { "device_id": "k10-act-03", "duration_s": 30, "target_range": [55, 65] } |
| basis_json    | JSON         | 决策依据（引用各 Agent 结论摘要）                                         |

## 6.9 verifications 验证记录

| 字段                     | 类型                                   | 说明              |
| ------------------------ | -------------------------------------- | ----------------- |
| run_id                   | BIGINT                                 |                   |
| task_no                  | VARCHAR(32)                            | 被验证的任务      |
| baseline_value           | DECIMAL(10,2)                          | 执行前基准值 38.5 |
| target_low / target_high | DECIMAL(10,2)                          | 目标区间 55 / 65  |
| measured_value           | DECIMAL(10,2)                          | 复测值 45.0       |
| achievement              | DECIMAL(5,2)                           | 达成率 41.18（%） |
| confidence               | DECIMAL(5,2)                           | 置信度 0-100      |
| conf_detail_json         | JSON                                   | 三路证据分数      |
| conclusion               | ENUM('success','failed','needs_human') | 结论              |

## 6.10 knowledge_docs 知识库文档表

| 字段            | 类型                                | 说明                    |
| --------------- | ----------------------------------- | ----------------------- |
| title           | VARCHAR(128)                        | 文档名                  |
| source          | VARCHAR(255)                        | 来源（标准号/书名/URL） |
| chunk_count     | INT                                 | 切片数                  |
| chroma_ids_json | JSON                                | 对应向量库 id           |
| status          | ENUM('processing','ready','failed') |                         |

## 6.11 alerts 报警表

| 字段         | 类型                              | 说明                               |
| ------------ | --------------------------------- | ---------------------------------- |
| level        | ENUM('info','warning','critical') |                                    |
| source       | VARCHAR(64)                       | device:k10-act-03 / agent:verifier |
| message      | VARCHAR(255)                      |                                    |
| acknowledged | BOOLEAN                           | 人工确认                           |

## 6.12 reports 报告表

| 字段        | 类型                | 说明                                   |
| ----------- | ------------------- | -------------------------------------- |
| run_id      | BIGINT              |                                        |
| report_type | ENUM('daily','run') | 日报 / 单次执行报告                    |
| content_md  | LONGTEXT            | Markdown 全文                          |
| stats_json  | JSON                | 汇总数字（任务数、成功率、平均达成率） |

## 6.13 feedback_logs 反馈修正日志（Self-Loop 证据链，REQ-F-018）

| 字段            | 类型        | 说明                                                                              |
| --------------- | ----------- | --------------------------------------------------------------------------------- |
| run_id          | BIGINT      |                                                                                   |
| round           | INT         | 第几轮（1, 2, ...）                                                               |
| failure_reason  | TEXT        | 诊断：沙质土渗透快于预期，单次水量不足                                            |
| correction_json | JSON        | 修正动作：{ "strategy": "split", "duration_s": 20, "interval_s": 60, "times": 2 } |
| next_task_no    | VARCHAR(32) | 修正后新任务                                                                      |
| outcome         | VARCHAR(16) | improved / same / worse（下一轮回填）                                             |

## 6.14 settings 全局配置表（键值对）

关键键：`mode`（mock/real）、`llm_provider`（glm/deepseek）、`llm_api_key`（加密存）、`irrigation_default_range`（[55,65]）、`schedule_cron`（巡园定时，默认每 2 小时）、`parallel_enabled`（true/false，串并行演示开关）、`max_retries`（3）。

---

# 7. 后端规格（FastAPI）

## 7.1 目录结构（与仓库根目录对应）

```
backend/app/
├── main.py                 # 入口：挂载路由、启动 MQTT 客户端与调度循环
├── config.py               # 读 .env 与 settings 表，统一配置对象
├── core/
│   ├── mqtt_client.py      # paho-mqtt 封装：订阅/发布/重连/幂等去重
│   ├── llm.py              # OpenAI 兼容接入层：GLM/DeepSeek 切换、重试、降级
│   ├── ws_manager.py       # WebSocket 连接管理与广播
│   └── security.py         # 简化鉴权（单管理员 token）
├── agents/
│   ├── base.py             # AgentRunner：构造消息→调LLM→解析工具调用→执行→回填
│   ├── prompts.py          # 7 个 Agent 的默认提示词（首启写入 agents 表）
│   └── runner_{key}.py     # 各 Agent 的工具绑定与输出解析（7 个薄文件）
├── workflow/
│   ├── engine.py           # DAG 解析、拓扑就绪检查、节点执行器
│   ├── nodes.py            # 节点类型实现：agent/tool/condition/parallel/join/loop
│   └── context.py          # run 上下文读写
├── orchestrator/           # ★ 调度器
│   ├── scheduler.py        # 主循环：取任务→打分→选派→超时→重试→熔断
│   ├── scorer.py           # 打分公式（REQ-F-014）
│   └── breaker.py          # 熔断器（按设备维度）
├── verification/
│   ├── achievement.py      # 达成率公式（REQ-F-016）
│   ├── confidence.py       # 三路置信度（REQ-F-017）
│   └── feedback.py         # 不达标诊断与修正建议生成（REQ-F-018）
├── devices/
│   ├── registry.py         # 设备注册、在线判定
│   └── command.py          # 指令构造、下发、ack 跟踪（唯一允许下发处）
├── knowledge/
│   ├── loader.py           # 文档上传→切片→embedding→Chroma 入库
│   └── retriever.py        # 检索（供植保员工具调用）
├── mock/
│   └── simulator.py        # Mock 设备模拟器（见第 12 章）
├── api/                    # REST 路由
│   ├── agents.py  workflows.py  tasks.py  devices.py
│   ├── sensor.py  knowledge.py  verify.py  reports.py
│   ├── settings.py  alerts.py
│   └── ws.py               # WebSocket /ws/dashboard
└── models/                 # SQLAlchemy 模型（对应第 6 章全部表）
```

## 7.2 LLM 接入层规格（REQ-F-001）

- 统一用 `openai` SDK：`base_url` 与 `api_key` 来自 settings（provider 切换即换 base_url）。
- GLM：`https://open.bigmodel.cn/api/paas/v4`，model `glm-4-flash`（免费档）。
- DeepSeek：`https://api.deepseek.com`，model `deepseek-chat`。
- 超时 60s；失败自动重试 1 次（换备用 provider）；连续 2 次失败 → **规则降级**：该 Agent 改用预置规则模板输出（见 20.2），并在对话剧场显示"⚠️ 模型降级中"徽章，恢复后自动切回。
- 每次调用记录 tokens_in/out 与 latency 到 agent_messages。

## 7.3 工具池（函数签名级定义，REQ-F-003）

工具是实现为 Python 函数的"Agent 的手"，全部注册进统一注册表，并通过 MCP Server（SSE 模式，`/mcp` 端点）对外暴露——这是赛题加分点。

| 工具名           | 签名                                                                                   | 绑定给                    | 说明                           |
| ---------------- | -------------------------------------------------------------------------------------- | ------------------------- | ------------------------------ |
| get_weather      | `(city: str, hours: int) -> {temp_range, rain_prob, frost_risk}`                     | weather                   | Mock 天气数据源（第 12 章）    |
| get_soil_status  | `(device_id: str) -> {soil_moisture, updated_at, trend}`                             | soil, scout               | 最近 3 点数据+趋势（升/平/降） |
| get_env_status   | `(device_id: str) -> {temperature_c, humidity_air, lux}`                             | scout                     | 最新环境读数                   |
| query_knowledge  | `(question: str, top_k: int = 3) -> [{title, chunk_text, score, doc_id}]`            | pest                      | Chroma 检索，返回带引用        |
| create_task      | `(type: str, payload: dict, priority: int, deadline_at: str = null) -> task_no`      | decision, verifier        | 写任务队列（进调度器）         |
| send_device_cmd  | `(device_id: str, action: str, params: dict) -> task_no`                             | **executor 独占**   | 经调度器下发 MQTT 指令         |
| verify_result    | `(task_no: str) -> {achievement, confidence, conclusion}`                            | verifier                  | 触发验证引擎                   |
| calc_achievement | `(baseline: float, target_low: float, target_high: float, measured: float) -> float` | verifier                  | 达成率计算（公式见 11.1）      |
| write_report     | `(run_id: int) -> report_id`                                                         | verifier                  | 汇总生成 Markdown 报告         |
| raise_alert      | `(level: str, message: str) -> alert_id`                                             | scout, executor, verifier | 写报警表+WS 推送               |

> 权限铁律：`send_device_cmd` 只出现在 executor 的 tools_json 里。若其他 Agent 的 LLM 输出请求调用它，AgentRunner 直接拒绝并在 tool_calls_json 里记录 `{"status": "denied", "reason": "permission"}`——这个"被拒绝的记录"本身就是权限分离的展示证据。

## 7.4 REST API 清单（前缀 `/api`）

| 方法                | 路径                                             | 说明                                                                   |
| ------------------- | ------------------------------------------------ | ---------------------------------------------------------------------- |
| GET/POST/PUT/DELETE | `/agents` `/agents/{key}`                    | Agent 配置 CRUD（改提示词即时生效）                                    |
| GET/POST/PUT/DELETE | `/workflows` `/workflows/{id}`               | 工作流 CRUD（dag_json 校验：无环、有唯一 start/end）                   |
| POST                | `/workflows/{id}/run`                          | 手动触发执行，返回 run_id                                              |
| GET                 | `/runs` `/runs/{id}`                         | 执行列表/详情（含节点轨迹、Agent 消息）                                |
| GET                 | `/tasks?status=&page=`                         | 任务队列分页                                                           |
| GET                 | `/devices` `/devices/{id}`                   | 设备列表与详情                                                         |
| POST                | `/devices/{id}/cmd`                            | 手动向设备发指令（设置页调试用）                                       |
| GET                 | `/sensor/latest`                               | 全部设备最新读数（大屏）                                               |
| GET                 | `/sensor/history?device_id=&metric=&from=&to=` | 历史曲线                                                               |
| POST                | `/knowledge/upload`（multipart）               | 上传 txt/md/pdf → 异步切片入库                                        |
| POST                | `/knowledge/search`                            | 检索测试                                                               |
| GET                 | `/knowledge`                                   | 文档列表与状态                                                         |
| POST                | `/verify/{task_no}`                            | 手动触发验证                                                           |
| GET                 | `/reports` `/reports/{id}`                   | 报告列表/详情                                                          |
| POST                | `/reports/generate?run_id=`                    | 生成报告                                                               |
| GET/PUT             | `/settings`                                    | 全局配置读写（mode 切换在此）                                          |
| GET                 | `/alerts`                                      | 报警列表                                                               |
| POST                | `/alerts/{id}/ack`                             | 确认报警                                                               |
| GET                 | `/docs`                                        | FastAPI 自动文档                                                       |
| WS                  | `/ws/dashboard`                                | 实时推送：telemetry / task_status / agent_message / node_state / alert |

WebSocket 推送消息统一格式：`{"type": "telemetry", "data": {...}, "ts": ...}`，type 全集：`telemetry / device_status / task_status / agent_message / node_state / run_status / alert / mode_changed`。

## 7.5 全局行为

- 启动时：初始化 DB（建表）→ 写入默认 Agent 提示词与默认工作流 → 启动 MQTT → 启动调度循环（每 1s）→ 启动 APScheduler（按 settings 的 cron 触发巡园工作流）。
- 全部异步（asyncio）；MQTT 回调通过 `asyncio.run_coroutine_threadsafe` 桥接到主循环。
- 日志：loguru，格式 `时间 | 级别 | 模块 | 消息`，同时写 `logs/backend.log`（轮转 10MB×5）。

---

# 8. 七个 Agent 规格

## 8.1 团队编制总表（REQ-F-002）

| # | agent_key | 姓名       | 职责                                   | 绑定工具                                                                | temperature | 权限特点               |
| - | --------- | ---------- | -------------------------------------- | ----------------------------------------------------------------------- | ----------- | ---------------------- |
| 1 | scout     | 巡园管家   | 数据汇总、异常初筛、发起巡园流程       | get_env_status, get_soil_status, raise_alert                            | 0.3         | 只读+报警              |
| 2 | weather   | 气象员     | 天气与霜冻风险                         | get_weather                                                             | 0.3         | 只读                   |
| 3 | soil      | 土壤师     | 墒情分析与趋势                         | get_soil_status                                                         | 0.3         | 只读                   |
| 4 | pest      | 植保员     | 病虫害/农艺风险，翻知识库              | query_knowledge                                                         | 0.4         | 只读（RAG）            |
| 5 | decision  | 灌溉决策官 | 汇总情报拍板，生成任务                 | create_task                                                             | 0.2         | 只能创建任务           |
| 6 | executor  | 执行管家   | 指令下发、盯 ack、超时重试             | send_device_cmd, raise_alert                                            | 0.2         | **唯一可触硬件** |
| 7 | verifier  | 验证审计官 | 复测、算达成率、出报告、不达标启动修正 | verify_result, calc_achievement, write_report, create_task, raise_alert | 0.3         | 裁判权                 |

## 8.2 系统提示词全文（首启写入 agents 表，设置页可改）

### scout（巡园管家）

```
你是「知秋」茶园平台的巡园管家，代号 scout。你负责在每次巡园开始时汇总茶园的实时状况。

你的工作：
1. 调用 get_env_status 和 get_soil_status 获取各区域最新环境与土壤数据。
2. 用不超过 150 字向团队播报当前状况，格式如下：
   【巡园播报】时间 HH:MM。A区：气温X℃ 空气湿度X% 光照Xlux 土壤湿度X%（趋势：升/平/降）。
3. 判断是否异常：土壤湿度<40% 为缺水预警；>85% 为渍涝预警；温度<4℃ 为霜冻预警；>38℃ 为高温预警。
   发现异常时追加一行：⚠️ 预警：<内容>，并调用 raise_alert(level, message) 记录。
4. 结尾必须给下游一句引导语，例如："请气象员、土壤师、植保员评估是否有作业需求。"

规则：你不负责决策，不下结论"要不要浇水"，只负责报数据和预警。语气简明专业。
```

### weather（气象员）

```
你是「知秋」平台的气象员，代号 weather。你负责提供未来天气对茶园作业的影响评估。

你的工作：
1. 调用 get_weather 获取目标区域未来 12 小时天气。
2. 用不超过 120 字输出评估，必须覆盖：
   - 降雨概率：≥60% 则明确建议"暂缓灌溉，等待自然降水"；
   - 霜冻风险：最低温<4℃ 时输出"⚠️ 霜冻风险"，并说明喷灌结冰风险；
   - 蒸发情况：最高温>32℃ 且湿度<50% 时提醒"水分蒸发快，灌溉时间宜选清晨或傍晚"。
3. 输出格式：【气象评估】未来12h气温X~X℃，降雨概率X%，霜冻风险X。结论：<利于灌溉/暂缓灌溉/注意时段>。

规则：只依据工具返回的数据说话，数据缺失时明确说"数据不可用"，禁止编造天气。
```

### soil（土壤师）

```
你是「知秋」平台的土壤师，代号 soil。你负责分析茶园土壤墒情。

你的工作：
1. 调用 get_soil_status 获取目标区域土壤湿度与趋势。
2. 按以下标准判断：
   - <30% 重度缺水（必须灌溉）；30-40% 轻度缺水（建议灌溉）；40-70% 适宜；>85% 渍涝（禁止灌溉）。
   - 趋势连续两点下降且当前<40%，视为"加速失水"。
3. 输出格式（≤120 字）：【墒情报告】A区土壤湿度X%，趋势X，评级：<重度缺水/轻度缺水/适宜/渍涝>。
   建议：<无需作业/建议灌溉/必须灌溉>，目标湿度区间 55%-65%。

规则：目标区间固定 55%-65%（茶树适宜区间），除非工作流上下文另行指定。禁止建议超出区间上限的目标。
```

### pest（植保员）

```
你是「知秋」平台的植保员，代号 pest。你负责农艺与植保层面的风险核查。

你的工作：
1. 针对当前场景（如"A区土壤湿度X%，计划灌溉"），调用 query_knowledge 检索农艺知识库。
2. 重点核查：① 该墒情下是否有常见病害风险（如茶饼病在高湿环境易发）；② 灌溉时段与农艺禁忌（如高温正午禁灌）；③ 当前是否有虫害防治窗口冲突。
3. 输出格式（≤150 字）：【植保核查】知识库检索到N条相关条目。
   - 引用[1]《条目标题》：<一句话要点>
   - 风险：<无/具体风险描述>
   - 建议：<无冲突/建议避开X时段/建议先X后X>
4. 你引用的每一条知识必须来自工具返回，并保留其编号，禁止编造引用。

规则：你的价值在于"有据可查"。宁可说"知识库中未检索到相关内容"，也不凭空给农艺建议。
```

### decision（灌溉决策官）

```
你是「知秋」平台的灌溉决策官，代号 decision。你是团队中唯一有权拍板的决策者，但你没有硬件权限——你只能通过创建任务让执行管家行动。

你的工作：
1. 汇总巡园管家、气象员、土壤师、植保员四方的结论（它们会在你的上下文里）。
2. 按以下决策树判断：
   - 土壤师评级=适宜 且 无预警 → 决策 none："本轮无需作业"。
   - 任何一方建议暂缓（如降雨概率≥60%、霜冻风险、渍涝）→ 决策 none，注明原因。
   - 缺水且无人反对 → 决策 irrigate，并制定方案。
3. 制定灌溉方案时确定：目标区间（默认55-65%）、单次时长（依据缺口大小：缺口<15%→20s；15-25%→30s；>25%→40s）、优先级（重度缺水=9，轻度=6）。
4. 调用 create_task(type="device_cmd", payload={action:"pump", duration_s:X, target_range:[55,65], baseline:当前值}, priority:P)。
5. 输出格式（≤150 字）：【决策】本轮决策：<irrigate/none/escalate>。
   方案：<对A区执行浇水X秒，目标湿度55-65%，优先级P>。
   依据：<一句话概括四方结论>。
   决策完成后移交给执行管家。

规则：决策必须给出一句话依据，引用至少两方 Agent 的结论。你的输出是责任记录，将存档供审计。
```

### executor（执行管家）

```
你是「知秋」平台的执行管家，代号 executor。你是全平台唯一有权操作硬件的 Agent。

你的工作：
1. 接到 device_cmd 任务后，核对参数合法性（duration_s∈[1,120]，目标设备在线）。
2. 调用 send_device_cmd 下发指令，然后跟踪回执：
   - 收到 received 回执 → 简短播报"设备已接收，执行中"；
   - 收到 finished 且 result=done → 播报"执行完成，实际浇水X秒"；
   - 超时（收到平台调度器通知）→ 按 2^n 秒退避重试，最多 3 次，重试时调用 raise_alert(warning)；
   - 3 次重试仍失败 → raise_alert(critical, "设备X连续失败已熔断")，任务转 dead，并在播报中说明。
3. 输出格式（≤100 字）：【执行反馈】任务task-xxx：<已下发/执行中/完成/重试第n次/已熔断>。设备状态：<在线/离线>。

规则：你不质疑决策内容，只保证执行到位与如实反馈。任何异常都必须留痕（raise_alert），不许隐瞒失败。
```

### verifier（验证审计官）

```
你是「知秋」平台的验证审计官，代号 verifier。你独立于决策链，是团队的"裁判"，运动员（决策官）说了不算，传感器数据说了算。

你的工作：
1. 灌溉执行完成并等待渗透期（默认 90 秒）后，通过 verify_result 获取复测数据。
2. 用 calc_achievement 计算达成率：实测值落在目标区间 [55,65] 内=100%；未达标按 (实测-基线)/(目标下限-基线) 折算，保留两位小数；超过上限按 100% 并注明"过浇提醒"。
3. 结合置信度（平台计算，三路证据加权）给出结论：
   - 达成率≥60% 且 置信度≥60% → success，闭环成功；
   - 达成率<60% → failed，你必须给出诊断与修正方案（见第3步）；
   - 置信度<60% → needs_human，说明哪路证据存疑。
4. 达成率<60% 时启动 Self-Loop 修正：
   - 诊断方向：缺口缩小了多少？渗透速度是否符合预期（单位时间湿度提升率）？是否存在读数异常（复测与执行间隔过短/过长）？
   - 修正策略：缺口仍>15% → 改为"分次灌溉"（如 20s×2 次，间隔 60s）；缺口≤15% → 追加单次短灌（10-15s）；数据可疑 → 通知巡园管家补测一次再判。
   - 调用 create_task 生成修正任务（trigger=selfloop），并输出【修正指令】。
5. 全部完成后调用 write_report 生成报告，输出（≤180 字）：
   【验证报告】任务task-xxx：基线X% → 复测X%，目标[55,65]，达成率X%，置信度X%。
   结论：<闭环成功/未达标已修正/转人工>。<一句话总结>。

规则：你的结论只依据数据与公式。达成率数字必须精确到小数点后两位，禁止四舍五入成整数糊弄。你是平台的公信力所在。
```

## 8.3 Agent 运行时行为（AgentRunner 统一实现）

1. **消息构造**：system = agents 表提示词；历史 = 本 run 内该 Agent 的对话（最多 10 条，超出摘要压缩）；user = 工作流节点注入的任务说明 + 上游结论。
2. **工具循环**：最多 6 轮工具调用，超过强制输出；每轮工具调用与返回都写入 tool_calls_json。
3. **输出解析**：要求 LLM 按【xxx】格式输出，后端用正则提取摘要入库；解析失败不影响流程（原文照存）。
4. **权限检查**：工具调用前查 tools_json 白名单，未授权一律 denied。
5. **并发**：气象员/土壤师/植保员三路并行（asyncio.gather），上下文互不可见，只有决策官能看到三方全部结论。

---

# 9. 工作流引擎规格（DAG）

## 9.1 DAG JSON Schema（REQ-F-004）

```json
{
  "wf_key": "patrol_irrigation",
  "name": "巡园浇水工作流",
  "nodes": [
    { "id": "n1", "type": "start", "name": "开始", "next": ["n2"] },
    { "id": "n2", "type": "agent", "agent_key": "scout", "name": "巡园播报",
      "input": "开始本轮巡园，目标区域：A区茶垄。", "next": ["n3"] },
    { "id": "n3", "type": "parallel", "name": "三方会诊", "branches": ["n4", "n5", "n6"], "next": ["n7"] },
    { "id": "n4", "type": "agent", "agent_key": "weather", "name": "气象评估",
      "input": "评估未来12小时天气对A区灌溉的影响。", "next": [] },
    { "id": "n5", "type": "agent", "agent_key": "soil", "name": "墒情分析",
      "input": "分析A区土壤墒情并评级。", "next": [] },
    { "id": "n6", "type": "agent", "agent_key": "pest", "name": "植保核查",
      "input": "核查当前墒情下灌溉的农艺风险。", "next": [] },
    { "id": "n7", "type": "agent", "agent_key": "decision", "name": "灌溉决策",
      "input": "汇总上述三方结论与本轮巡园播报，按决策树给出决策；若 irrigate 则创建浇水任务。",
      "next": ["n8"] },
    { "id": "n8", "type": "condition", "name": "决策分流",
      "expression": "context.last_decision == 'irrigate'",
      "branches": { "true": ["n9"], "false": ["n12"] } },
    { "id": "n9", "type": "agent", "agent_key": "executor", "name": "执行浇水",
      "input": "领取设备指令任务并执行，跟踪回执直到完成或熔断。", "next": ["n10"] },
    { "id": "n10", "type": "tool", "tool": "wait_penetration", "params": { "seconds": 90 },
      "name": "渗透等待", "next": ["n11"] },
    { "id": "n11", "type": "agent", "agent_key": "verifier", "name": "验证审计",
      "input": "对刚完成的浇水任务执行复测验证，不达标启动Self-Loop修正。",
      "next": ["n11b"] },
    { "id": "n11b", "type": "loop", "name": "Self-Loop",
      "max_iterations": 2,
      "exit_expression": "context.last_verification == 'success' or context.round >= 2",
      "body_next": "n9", "next": ["n13"] },
    { "id": "n12", "type": "agent", "agent_key": "verifier", "name": "无需作业归档",
      "input": "本轮决策为暂不作业，生成简要记录。", "next": ["n13"] },
    { "id": "n13", "type": "end", "name": "结束" }
  ],
  "edges": []
}
```

> 上例为**默认工作流全文**，首次启动写入 workflows 表。Self-Loop 以 `loop` 节点（`n11b`）实现，**先判后循环**：主链上的 `n11` 是首验（计第 1 轮），进入 `n11b` 先求值 `exit_expression`——首验已达 `success` 就直接走 `n13`，`body` 一次都不跑；未达标（或表达式依赖的字段暂时缺失，按未达标处理）时，引擎按验证层已算好的 `correction`（`split` / `topup` / `suspect_data`）落一张新任务（`trigger=selfloop`，带 `device_id`）并写 `feedback_logs`，再按 `body_next` 回到 `n9`，走「执行管家领修正单 → 渗透等待 → 复测验证」。
>
> `max_iterations` 是**总轮次**上限（默认 2，可配），与 `exit_expression` 里的 `context.round >= 2` 同口径：主链首验 1 轮 + 修正后 1 轮 = 最多 2 次验证、最多 1 次修正；跑满仍不达标按 11.4.3 转人工。**不取「2 次修正 / 3 次验证」**：第 3 轮的修正单会被建出来却没人执行，库里留一张会真浇水的孤儿单，报告也无法自证「修正后的结果」。
>
> 修正任务由引擎（`_apply_correction`）建，`loop` 节点只负责判定与回跳，不生成任务；`verifier` 的职责是用 `verify_result` 给出结论与修正方案。画布事件按到达顺序播放，`n11` 同一节点会出现两次（第 1 轮、第 2 轮），轮次徽章按 `context.round` 计。画布坐标存于节点 `position: {x, y}` 字段（此处省略，画布保存时自动写入）。
>
> 连线约定：**边只由节点上的 `next` / `branches` / `body_next` 显式声明，`edges` 恒为空数组**，不得用于表达拓扑（画布存布局即可，不要往这里写说明文字，否则 JSON 不合法）。`n11 → n11b → n13` 是 Self-Loop 的入口与出口：验证完进 loop 判定，达标走 `n13`，不达标由 loop 按 `body_next` 回到 `n9` 重新「执行 → 渗透 → 复测」（**不是回 `n11` 原地重验**——那样三轮验的是同一批读数，物理世界一动不动）。因此 `n11b` 必须被 `n11` 指向，否则可达性校验会判它为孤儿节点。

## 9.2 节点类型语义（nodes.py 实现依据）

| 类型      | 语义                                                                                              | 状态                 |
| --------- | ------------------------------------------------------------------------------------------------- | -------------------- |
| start     | 入口，写 context 起点                                                                             | done 即刻            |
| agent     | 调 AgentRunner，产出写入 context（key=agent_key）                                                 | running→done/failed |
| tool      | 执行注册表里的纯工具函数（如 wait_penetration 定时器）                                            | running→done        |
| condition | 对 context 求布尔表达式（安全沙箱：仅允许 context.* 与比较/逻辑运算，用 ast 白名单解析，禁 eval） | 路由                 |
| parallel  | 扇出 branches 并行执行，join 语义：全部完成才走 next                                              | fan-out              |
| loop      | 条件循环体，带 max_iterations 与退出表达式                                                        | 循环                 |
| end       | 终点，run 收口（success/needs_human）                                                             | 终态                 |

执行规则：**拓扑就绪检查**——节点在其全部前置完成/满足后才可执行；任一 agent 节点 failed → 默认重试 1 次，再失败则 run 标 failed（可配置"失败即转人工"）。

## 9.3 上下文（context.json）关键字段

`region`（目标区域）、`baseline`（执行前土壤湿度）、`last_decision`（irrigate/none）、`irrigation_params`、`last_verification`（success/failed/needs_human）、`round`（Self-Loop 轮次）、`weather_summary / soil_report / pest_check / patrol_brief`（四方结论）。

## 9.4 工作流验收标准

- [ ] 默认工作流通过校验（无环、单 start 单 end、agent_key 均存在）
- [ ] Mock 模式手动触发，全流程跑通 ≤ 5 分钟（含 90s 渗透等待）
- [ ] 决策为 none 时走 n12 分支；irrigate 时走 n9→n13
- [ ] 画布保存的布局坐标能正确回显

---

# 10. 调度器规格（动态调度）

## 10.1 调度循环（scheduler.py，每 1s 一轮）

```
while True:
    1. 扫描 tasks：pending → 打分入序
    2. 处理 dispatched/running 超时：超时任务 → timeout 状态 → 进重试逻辑
    3. 重试管理：retrying 任务按退避时间到期后 → 重新 pending
    4. 熔断检查：设备连续失败计数 → 触发/解除熔断
    5. 派发：按分数取 top 任务 → 找可用 Agent（空闲且绑定该工具）→ dispatched
    6. 心跳回写：Redis 在线状态刷进 devices 表
    sleep(1)
```

## 10.2 任务状态机

```
pending → dispatched → running → success
   ↑           │           │
   │           ▼           ▼
   └──── retrying ←── timeout / failed ──→ dead（重试耗尽）
                              │
                              └──→ needs_human（验证置信度不足时由验证器标记）
canceled：人工取消任何非终态任务
```

## 10.3 打分公式（scorer.py，REQ-F-014）

```
score = 0.4 × priority_normalized      # priority 1-10 → 0.1-1.0
      + 0.3 × urgency                  # 时间窗紧迫度：无 deadline=0.5；剩时间占比 = 剩余/总窗 → urgency = 1-占比
      + 0.2 × (1 - agent_load)         # 目标 Agent 当前并发数/上限（默认上限3）
      + 0.1 × device_online            # 目标设备在线=1，离线=0（离线任务自然沉底）
```

相同分数按 FIFO。**演示钩子**：设置页 `parallel_enabled` 开关——关闭时调度器每轮只派 1 个任务（串行模式），开启时并发派发（并行模式）。第 15 章剧本用同一工作流跑两种模式对比总耗时。

## 10.4 重试与熔断

- 重试：`delay = 2^retry_count × 2s`（2s/4s/8s），`max_retries=3`（可配）；device_cmd 类重试前必须先查设备在线状态，离线则挂起重试。
- 熔断（breaker.py）：单设备连续 3 次 timeout/failed → 熔断 300s；熔断期内该设备任务直接返回 rejected；熔解除 5 分钟自动解除，也可设置页手动解除。
- 每次状态变更：写 tasks 表 + WS 推送 task_status。

## 10.5 调度器验收标准

- [ ] 同一 run 内 3 个分析任务并行派发（parallel_enabled=true），总耗时明显小于串行（录屏计时）
- [ ] 手动让某设备断电 → 任务超时 → 自动重试 2 次期间设备恢复 → 任务成功（全程任务页可见轨迹）
- [ ] 连续制造 3 次失败 → 熔断触发，任务页出现熔断徽章与报警

---

# 11. 验证引擎规格（Self-Loop 核心）

## 11.1 达成率公式（achievement.py，REQ-F-016）

设基线值 `B`（执行前土壤湿度）、目标区间 `[L, H]`（默认 [55, 65]）、复测值 `M`：

```
若 L ≤ M ≤ H          → achievement = 100.00
若 M < L（未达标）      → achievement = max(0, (M - B) / (L - B)) × 100
若 M > H（超过上限）    → achievement = 100.00，并标注 over_irrigated = true
示例：B=38.5, L=55, M=45.0 → (45.0-38.5)/(55-38.5)=6.5/16.5=39.39%
示例：B=38.5, L=55, M=57.0 → 100.00%
```

> 复测值取执行完成 + 渗透等待（90s）后，土壤节点的**连续 3 次读数的中位数**（防单点抖动）。

## 11.2 三路置信度（confidence.py，REQ-F-017）

```
confidence = 0.5 × 数据质量分 + 0.3 × 规则交叉分 + 0.2 × 一致性分

数据质量分（0-1）：复测设备在线=0.4；3 次读数极差<5%=0.4（抖动小）；读数非跳变（与上一点差<20）=0.2
规则交叉分（0-1）：物理合理性——浇水后应上升，若 M>B 得 1.0，M≤B 得 0.0；
                   单位时间提升量与浇水时长正相关（提升% / 时长s 在 0.1-1.0 区间）得 1.0，否则 0.5
一致性分（0-1）：复测读数与该设备近 24h 均值偏差 <3σ 得 1.0，否则按偏差比例衰减
```

## 11.3 结论与分流

| 达成率 | 置信度 | 结论        | 后续动作                              |
| ------ | ------ | ----------- | ------------------------------------- |
| ≥60%  | ≥60%  | success     | 闭环成功，写报告                      |
| <60%   | ≥60%  | failed      | **触发 Self-Loop 修正**（11.4） |
| 任意   | <60%   | needs_human | 报警 + 界面红色"转人工"徽章，run 挂起 |

## 11.4 反馈修正（feedback.py，REQ-F-018）

1. 诊断（规则引擎，不调 LLM，保证 100% 可复现）：
   - 缺口 = L − M；若缺口 >15 → 策略 `split`（分次灌溉，duration=原时长×0.67，2 次，间隔 60s）
   - 若 0 < 缺口 ≤15 → 策略 `topup`（单次补灌 duration=10+缺口 s）
   - 若 M ≤ B（浇了没升）→ 策略 `suspect_data`（先触发 2 次 read_now 复核，再判定）
2. 写 feedback_logs（round、failure_reason、correction_json），生成新任务（trigger=selfloop），回到执行-验证循环。**建单只发生一次**：由工作流引擎 `_apply_correction` 按本节的 `correction` 落单并写 feedback_logs；验证层在工作流在场时不再自行建单（否则同一修正会建出两张单，其中一张没人认领、超时重试）。
3. 第 2 轮（修正后那一轮）结束仍 failed → run 标 `needs_human`（防无限循环），报告明示"2 轮验证仍未达标（含 1 次修正），转人工"。**跑完 ≠ 成功**：`last_verification` 为 `failed` 时 run 不得标 `success`。
4. **证据链要求**：报告页必须完整展示"第 1 轮基线/复测/达成率 → 诊断 → 修正 → 第 2 轮结果 → outcome 回填"，这是"反馈循环与优化"模块的满分答卷。

## 11.5 验证引擎验收标准

- [ ] 用 Mock 注入"第 1 轮 M=45（39.39%）→ 修正 → 第 2 轮 M=57（100%）"，报告页完整呈现两轮对照
- [ ] 达成率计算用单元测试覆盖 5 个边界（M<H、M=L、M∈区间、M>H、M<B）
- [ ] 置信度<60% 的情形（人为制造抖动数据）能触发转人工

---

# 12. Mock / Real 双模式

## 12.1 切换机制（REQ-F-019）

- settings.mode = `mock` | `real`，设置页大开关，切换即全平台生效并 WS 广播 mode_changed。
- 后端所有获取数据的路径统一走**数据源适配层**：Mock 时从模拟器内存读，Real 时从 sensor_data 表读真实设备数据。Agent 的工具函数无感知。
- 设备下发：Mock 模式下 send_device_cmd 直接送入模拟器（绕过 MQTT 也行，但**推荐仍走 MQTT**——模拟器就是订阅同一主题的进程，这样两种模式链路完全一致，切换零风险）。

## 12.2 模拟器规格（mock/simulator.py，也是开发期假设备）

单进程跑 3 个虚拟设备线程，行为与真固件完全一致（同样发 telemetry/status/ack）：

| 虚拟设备           | 行为模型                                                                                                                                                                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| mock-k10-field-01  | 温度=24±3 正弦漂移；空气湿度=60±10；光照按正弦昼夜曲线                                                                                                                                                                                                            |
| mock-esp32-soil-02 | **关键**：土壤湿度模型 `M(t+dt) = M(t) − dry_rate×dt + water_effect`；dry_rate 默认 0.05%/min（可配）；收到 pump 指令后按 `+0.35%/s × duration_s` 分两段注入（即时上升 60%，剩余 40% 在其后 60s 内缓慢渗透上升——模拟真实渗吸），使 30s 浇水约 +10.5% |
| mock-k10-act-03    | 收到 pump → 等待 duration_s → 回 ack done（模拟执行时间）                                                                                                                                                                                                         |

**故障注入 API**（仅 Mock，命令行或设置页触发）：

| 注入                                 | 效果                 | 演示用途                                       |
| ------------------------------------ | -------------------- | ---------------------------------------------- |
| `fault offline {device} {seconds}` | 设备静默             | 超时重试演示                                   |
| `fault ack_timeout {n}`            | 伪造 ack 超时        | 重试/熔断演示                                  |
| `fault dry_soil`                   | 土壤湿度强制降到 25% | 触发重度缺水决策                               |
| `fault stuck_moisture`             | 浇水后湿度不再上升   | 触发 Self-Loop 第 1 轮失败（演示两轮对照必备） |
| `fault sensor_jitter`              | 读数 ±15% 抖动      | 触发低置信度转人工                             |

> **关键设计**：`stuck_moisture` 是两轮对照演示的开关——第 1 轮注入它让验证失败并触发修正，关闭它后第 2 轮自然成功。整个 Self-Loop 演示 100% 可控、可复现、永不翻车。

## 12.3 Mock 天气数据源

get_weather 返回固定档位可切换的假数据：`sunny / cloudy / rainy / frost`。默认 sunny。演示"降雨暂缓灌溉"分支时切 rainy，决策官会走 none 分支。

---

# 13. 前端规格（六个页面）

技术栈：React 18 + Vite + TypeScript + Tailwind CSS + React Flow + ECharts。全局：左侧窄边栏导航（图标+文字），顶部状态条（模式徽章 MOCK/REAL、后端连接状态点、当前时间）。所有页面响应 WebSocket 实时刷新，禁用手动 F5。

## 13.1 P1 总控大屏 `/`（dashboard）

- **布局**：顶部 4 个指标卡（在线设备数、今日任务数、今日闭环成功率、平均达成率）；中部左侧茶园地图卡片（A 区地块示意，3 个设备点位，绿点呼吸=在线、灰=离线、红=报警，点位上方气泡显示实时读数）；中部右侧 24h 土壤湿度曲线（ECharts，Mock/Real 数据同源）；底部滚动报警条。
- **交互**：点设备点位 → 抽屉显示该设备详情与历史曲线；右上角醒目大按钮「开始巡园」→ 确认弹窗 → POST /workflows/{id}/run → 自动跳转画布页并高亮正在执行的 run。

## 13.2 P2 工作流画布 `/canvas`（评委看懂"编排"的核心页）

- **布局**：主区 React Flow 画布；左侧节点面板（agent/condition/parallel/loop 四类模板可拖入）；右侧属性面板（选中节点显示配置：agent_key、input、expression，可编辑保存）。
- **节点样式**：agent 节点=圆角卡片（头像 emoji + 姓名 + 状态徽章）；condition=菱形；parallel=分叉横条；loop=虚线圆角框（标注 max_iterations）。
- **执行动画（REQ-U-001，本页灵魂）**：节点 running=绿色呼吸光晕；done=边框变实心绿 + 打勾；failed=红色；并行节点同时呼吸。**连线数据流动画**：SVG dashed 边框 + CSS `stroke-dashoffset` 动画，执行中的路径上光点从上游流向下游。节点点击 → 弹出该节点 Agent 的发言与工具调用详情。
- **顶部**：工作流选择器 + 「运行」按钮 + 当前 run 的计时器 + 轮次徽章（第 1 轮 / 第 2 轮——Self-Loop 可视化）。

## 13.3 P3 Agent 对话剧场 `/chat`

- **布局**：微信群聊样式。每条消息：头像（emoji）+ 姓名 + 时间 + 内容气泡；工具调用以折叠块嵌在气泡内（展开可见调用参数与返回 JSON）；知识库引用渲染为带下划线的 [1][2] 编号，hover 显示原文摘要。
- **顶部**：run 选择器；右侧当前参与成员列表（7 个 Agent 头像，正在发言者高亮）。
- **特殊元素**：模型降级时气泡顶部黄条"⚠️ 模型降级输出"；被拒绝的权限调用显示灰色块"⛔ 权限不足：send_device_cmd（已拦截）"——权限分离的直观证据。

## 13.4 P4 任务中心 `/tasks`

- **布局**：筛选条（状态多选、类型、时间范围）+ 表格（任务号、类型、目标设备/Agent、优先级、分数、状态徽章、重试次数、耗时、创建时间）+ 点击行展开轨迹抽屉（pending→dispatched→running→…每次状态变更时间戳）。
- **状态徽章配色**：排队灰 / 执行中蓝闪 / 成功绿 / 重试橙 / 超时红 / 熔断深红 / 转人工紫。

## 13.5 P5 验证与报告 `/report`

- **布局**：顶部 run 选择器；主区达成率大圆环（ECharts，绿色渐变，中心大数字精确两位小数）+ 置信度小圆环；中部两轮对照表（轮次、基线、复测、达成率、诊断、修正策略——Self-Loop 证据链可视化）；底部报告 Markdown 渲染 + 「导出 PDF」（浏览器打印）+ 「生成日报」按钮。

## 13.6 P6 设置 `/settings`

- **布局**：分组表单卡。①运行模式：Mock/Real 大开关（滑动切换，当前模式高亮）；②模型服务：provider 下拉 + Key 输入 + 「测试连接」按钮（返回当前模型与延迟）；③Agent 管理：7 个 Agent 卡片列表，点开编辑提示词/工具/启停；④设备管理：设备列表 + 手动发指令调试器（选设备+action+参数+发送，显示 ack）；⑤故障注入（仅 Mock 显示）：5 个注入按钮；⑥调度参数：parallel_enabled 开关、max_retries、渗透等待秒数；⑦知识库管理：上传（拖拽区）、文档列表（处理状态）、检索测试框（输入问题→显示 top3 命中片段与分数）。

## 13.7 前端验收标准

- [ ] 六页全部无 console 报错，WS 断线自动重连（5s 间隔）
- [ ] 画布执行动画完整流畅（录屏 60fps 不掉帧）
- [ ] 移动端浏览器打开大屏页不横向滚动（响应式最低适配 iPad 竖屏）

---

# 14. UI 设计规范

| 项        | 规范                                                                                                                                        |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 风格      | 深色数字孪生大屏风；克制、专业，避免游戏感                                                                                                  |
| 背景      | `#0B1220`（主）/ `#111A2E`（卡片）/ `#1A2540`（卡片 hover）                                                                           |
| 主色      | 茶绿 `#34D399`（成功、强调、在线）                                                                                                        |
| 辅助色    | 蓝 `#3B82F6`（执行中）、琥珀 `#F59E0B`（警告/重试）、红 `#EF4444`（失败/报警）、紫 `#A78BFA`（转人工）、灰 `#64748B`（离线/禁用） |
| 文字      | 主 `#E2E8F0`，次 `#94A3B8`，弱 `#475569`                                                                                              |
| 字体      | 思源黑体 Noto Sans SC；数字用等宽 `DIN Alternate, monospace`                                                                              |
| 圆角/间距 | 卡片 12px，按钮 8px；页边距 24px，卡片间距 16px                                                                                             |
| 动效      | 数字滚动（MetricTile 用 rAF 插值 500ms）；呼吸光晕（box-shadow 2s 循环）；数据流（stroke-dashoffset 1s 线性循环）；页面切换 150ms fade      |
| 图表      | ECharts 统一主题：网格线 `#1E293B`，曲线主绿+辅蓝，禁用默认红蓝配色；仪表盘圆环 270° 起                                                  |
| 禁止      | emoji 当图标滥用（仅 Agent 头像允许）、纯白纯黑、闪烁超过 2Hz 的动画（防评委不适）                                                          |

---

# 15. 端到端演示剧本

## 15.1 主剧本：巡园浇水两轮对照（视频与现场演示的主线，总时长约 4 分钟）

| 步骤 | 操作                                                          | 预期画面                                                   | 用时 |
| ---- | ------------------------------------------------------------- | ---------------------------------------------------------- | ---- |
| 1    | 打开大屏，确认 Mock 徽章、设备在线                            | 指标卡、曲线、绿点呼吸                                     | —   |
| 2    | 设置页注入 `dry_soil`（土壤降到 ~25%）                      | 大屏曲线下探、报警条出现缺水预警                           | 10s  |
| 3    | 回大屏点「开始巡园」→ 跳转画布                               | 巡园管家节点点亮，发言出现                                 | 20s  |
| 4    | 三方会诊并行                                                  | 气象/土壤/植保三节点**同时**呼吸发光                 | 40s  |
| 5    | 决策官拍板 irrigate 30s                                       | 决策发言 + 任务徽章                                        | 20s  |
| 6    | 执行管家下发，`stuck_moisture` 提前已注入                   | 执行节点点亮，执行中                                       | 15s  |
| 7    | 渗透等待 90s                                                  | 画布上等待节点倒计时；切大屏看湿度曲线"小涨后停滞"         | 90s  |
| 8    | 验证官复测：达成率 39.39%，failed                             | **红色 39.39% 圆环**，诊断发言，【修正指令】分次灌溉 | 20s  |
| 9    | Self-Loop 第 2 轮：画布轮次徽章变"第 2 轮"（关闭 stuck 注入） | 执行→等待→验证 再跑一遍                                  | 120s |
| 10   | 复测 57% → 100%                                              | **绿色 100.00% 圆环**，"闭环成功"徽章弹跳            | 20s  |
| 11   | 报告页展示两轮对照表 → 导出 PDF                              | 证据链完整呈现                                             | 30s  |

> 第 1 轮"失败"不是演砸，是**设计好的教学演示**——评委看到失败→诊断→修正→成功，才真正理解 Self-Loop 的价值。视频里必须保留这个失败。

## 15.2 备选剧本 B：超时重试与熔断（1 分钟）

`fault offline k10-act-03 120s` → 触发浇水 → 任务超时 → 重试第 1 次（2s）失败 → 第 2 次（4s）失败 → 熔断徽章 + critical 报警 → 设备"恢复上线" → 熔断解除提示。全程任务中心轨迹抽屉展示状态机流转。

## 15.3 备选剧本 C：串行 vs 并行对比（30 秒）

`parallel_enabled=false` 跑三方会诊段（串行，约 3×20s）→ 开启 → 重跑（并行约 20s）→ 画布顶部计时器对比（如 61s vs 24s）。视频用分屏或倍速剪辑呈现。

## 15.4 备选剧本 D：真机浇水（Real 模式，决赛现场用）

切换 REAL 徽章 → 真实 K10 屏幕显示数据 → 决策 → 真水泵"咔哒"出水 → 杯中水位上升 → 复测（真实传感器）→ 达成率。中途评委可拔土壤传感器 → 平台报警 → 重连后自动恢复。

---

# 16. 需求编号总表与验收标准

> 给 Claude 下任务时引用编号。DoD 全部通过才算完成。

| 编号      | 需求                                             | DoD（验收标准）                                                  |
| --------- | ------------------------------------------------ | ---------------------------------------------------------------- |
| REQ-F-001 | LLM 接入层（GLM/DeepSeek 可切换+降级）           | 断网时自动降级为规则模板并在界面标注                             |
| REQ-F-002 | Agent 团队定义（7 Agent 配置化）                 | 设置页改提示词→下一轮生效；增删 Agent 不改代码                  |
| REQ-F-003 | 工具池 10 个函数 + 权限白名单 + MCP Server 端点  | 非 executor 调 send_device_cmd 被拒绝并留痕；`/mcp` 可列出工具 |
| REQ-F-004 | DAG 工作流引擎（6 种节点+校验+执行）             | 默认工作流 Mock 跑通；环图被拒绝保存                             |
| REQ-F-013 | 工作流画布（React Flow 拖拽+执行动画）           | 执行态动画流畅；节点点击看详情                                   |
| REQ-F-014 | 调度器（打分/并行/重试/熔断）                    | 10.5 三条全过                                                    |
| REQ-F-015 | 任务中心（状态机可视化+轨迹）                    | 9 种状态徽章正确                                                 |
| REQ-F-016 | 达成率公式 + 单元测试                            | 5 边界用例全过                                                   |
| REQ-F-017 | 三路置信度                                       | 低置信度触发转人工                                               |
| REQ-F-018 | 反馈修正 + 证据链（feedback_logs）               | 两轮对照在报告页完整呈现                                         |
| REQ-F-019 | Mock/Real 切换 + 模拟器 + 5 种故障注入           | 模拟器与真固件行为一致（同一 cmd 同样 ack）                      |
| REQ-F-020 | 知识库（上传→切片→Chroma→检索测试→引用标注） | 上传 PDF 后检索命中并返回引用                                    |
| REQ-F-021 | 六页前端 + WS 实时刷新                           | 13.7 三条全过                                                    |
| REQ-F-022 | 报告生成与导出                                   | 报告 Markdown 渲染正确，导出 PDF 成功                            |
| REQ-F-023 | Docker Compose 一键启动                          | 全新电脑 `docker compose up -d` 后 3 分钟内可访问              |
| REQ-H-001 | 三块板固件（遥测/心跳/指令/重连）                | 4.4 四条全过                                                     |
| REQ-H-002 | 土壤标定流程                                     | 干/湿标定后误差 <10%                                             |
| REQ-H-003 | Real 模式端到端                                  | 15.4 剧本走通                                                    |
| REQ-U-001 | 深色大屏 UI 规范落地                             | 色板/动效符合第 14 章表                                          |
| REQ-O-001 | 默认工作流+默认提示词+初始数据种子               | 首次启动自动写入，无需手工配置                                   |

---

# 17. 排期与四人分工（v1.1 重排）

> **团队 4 人**：队长（智能体+统筹）、队友 A（前端）、队友 B（后端基座）、队友 C（硬件）。
> 每人用「VSCode + Claude」在自己地盘内干活：把对应章节 + REQ 编号喂给 Claude，产出后按 DoD 验收。
> **材料线与代码线并行，材料不等代码。提交线：2026-11-15（缓冲日）。**

## 17.1 四人地盘与负责的 REQ

| 人                  | 地盘                                                                                                                          | 负责的 REQ                                                                                   |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 队长（智能体+统筹） | `backend/app/` 的 agents、workflow、orchestrator、verification、knowledge 五个子目录 + `core/llm.py`                      | F-001/002/003/004/014/016/017/018/020、F-022（报告生成后端半）、O-001（默认工作流+提示词半） |
| 队友 A（前端）      | `frontend/` 全部                                                                                                            | F-013、F-015（任务中心页）、F-021、F-022（渲染导出半）、U-001                                |
| 队友 B（后端基座）  | `backend/app/` 的 core（llm.py 除外）、api、models、devices、mock + 根目录 docker-compose.yml 与 .env.example + `deploy/` | F-019、F-023、O-001（设备种子半）、MQTT 接收入库（第 5 章）、API 全清单（7.4）               |
| 队友 C（硬件）      | `firmware/` 三工程 + 实体设备 + `docs/hardware_log.md`                                                                    | H-001/002/003、视频真机段素材（21.3）                                                        |

> 每人的具体开工手册见 `frontend/`、`backend/`、`firmware/`、`backend/app/agents/` 四份 README。

## 17.2 冲刺排期（四人并行，按 11.9 起算）

| 日期            | 队长（智能体线）                                     | 队友 A（前端线）                                    | 队友 B（基座线）                                               | 队友 C（硬件线）                                   |
| --------------- | ---------------------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------- | -------------------------------------------------- |
| D7-D8 11.9-10   | LLM 接入层 + 工具池 + 7 Agent 入库（F-001/002/003）  | 前端骨架 + 大屏页（U-001 半 + F-021 半）            | compose 六服务 + 建表 + MQTT 入库 + 模拟器（F-023 + F-019 半） | 装 PlatformIO；三板跑通 WiFi+MQTT+遥测（H-001 半） |
| D9-D10 11.11-12 | 工作流引擎 + 调度器（F-004 + F-014）                 | 画布页 + 任务中心（F-013 + F-015）                  | REST API 全清单 + WS 推送（7.4 全表）                          | K10 二号接水泵真浇水 + 土壤标定（H-002）           |
| D11 11.13       | 验证引擎 + 知识库 + 报告后端（F-016/017/018/020）    | 对话剧场 + 报告页 + 设置页（F-021 收尾 + F-022 半） | Mock/Real 切换收尾 + 一键启动打磨（F-019 收尾）                | Real 端到端走通 + 演示彩排（H-003）                |
| D12 11.14       | 全链路联调 + 方案书定稿                              | UI 打磨 + 界面录屏素材                              | 冻结修致命 bug + README 打磨                                   | 冻结 + 视频素材齐 + 彩排 3 遍                      |
| 11.15           | **提交（缓冲日）**：三件套终审、导出 PDF、提交 | —                                                  | —                                                             | —                                                 |

**材料节点**：方案书初稿不晚于 11.12（Claude 写 90%、队长改 10%）；PPT 初稿 11.13；视频粗剪 11.14 中午（分镜见 21.3）；三件套互查 11.14 晚；指导老师署名确认 11.14。

## 17.3 分工细则

- **队长（用户）**：智能体核心线 + 全局统筹——验收所有 REQ 的 DoD、契约守门（第 5/7 章改动必须经你）、审 PR、方案书与 PPT 主笔。
- **队友 A（前端）**：六个页面 + 执行动画；按第 14 章设计规范执行；每页先跑 Mock 数据自测，别等后端。
- **队友 B（后端基座）**：让平台「活着」——服务起得来、数据进得库、接口都通；模拟器行为与固件对齐（同一 cmd 同样 ack）。
- **队友 C（硬件）**：三板真实数据 + 真浇水；每天实测读数记入 `docs/hardware_log.md`（方案书实测数据来源）；视频真机段拍摄。
- **Claude（AI 助手）**：四个人各自指挥自己地盘内的 REQ；跨地盘改动必须队长批准；方案书、PPT 大纲、视频分镜由 Claude 代笔、队长定稿。

---

# 18. Git 与协作规范

> 完整规矩（分支模型、PR 流程、issue 用法、保密纪律）见仓库根目录 **TEAM.md**，以它为准。核心四条：

- **分支**：`main` 设保护只许 PR 合入（永远可跑）；每人用自己的 `feature/<模块>-<功能>` 分支干活。
- **提交频率**：每完成一个 REQ 或小功能即 commit；每天收工前必 push，PR 给队长 review 后合并。
- **commit 信息格式**：`<类型>(<模块>): <一句话>`，类型取 feat/fix/docs/test/chore。例：`feat(orchestrator): 实现打分公式与并行派发`。
- **Claude 改代码铁律**：让 Claude 动大手术前先 commit——改崩可回滚；AI 生成的代码自己看懂再提交。
- **文件禁区**：`.env`（真实 Key）永不上传；仓库只放 `.env.example`。

`.gitignore` 全文（直接复制到仓库根目录）：

```gitignore
# 环境与密钥
.env
*.key
# Python
__pycache__/
*.pyc
.venv/
venv/
# Node
node_modules/
dist/
# PlatformIO
.pio/
# 日志与数据
logs/
*.log
uploads/
chroma_data/
mysql_data/
# 系统
.DS_Store
Thumbs.db
```

---

# 19. 环境搭建指南

## 19.1 一次性安装（用户电脑，Windows/Mac 皆可）

1. **Docker Desktop**：官网下载安装，启动即可（WSL2 后端）。
2. **VSCode 插件三件**：Claude（Claude Code）、PlatformIO IDE、Python。
3. **Node.js ≥ 20**（前端本地调试用）。
4. **Git**：安装后 `git config --global user.name/user.email`。

## 19.2 API Key 申请（10 分钟，零成本起步）

1. 智谱开放平台 `bigmodel.cn`：注册 → 学生认证 → 创建 API Key（GLM-4-Flash 免费额度，开发全程够用）。
2. DeepSeek 开放平台 `platform.deepseek.com`：注册 → 充值 ¥10 → 创建 Key（备用）。

## 19.3 一键启动平台

```bash
git clone <仓库地址> && cd zhiqiu
cp .env.example .env        # 填入 API Key
docker compose up -d        # 启动 6 个服务
docker compose logs -f backend   # 看到 "startup complete" 即成功
# 浏览器打开 http://localhost:5173
```

## 19.4 烧录固件（队友 C）

1. VSCode → PlatformIO → Open Project → 选 `firmware/k10_field`；
2. 编辑工程内 `wifi_config.h`：填 WiFi 名称/密码/MQTT 服务器 IP（电脑局域网 IP）；
3. USB 连接板子 → PlatformIO 底栏 → Upload（K10 按住 BOOT 进下载模式，如报错）；
4. 三块板重复；串口监视器确认"MQTT connected"。

常见坑：K10 选板型 `esp32-s3-devkitc-1` + `Upload Speed 921600`；ESP32-E 选 `esp32dev`；CH340 驱动装好；板子用数据线不是充电线。

## 19.5 服务端口表

| 服务      | 端口 | 说明             |
| --------- | ---- | ---------------- |
| 前端      | 5173 | 浏览器入口       |
| 后端 API  | 8000 | /docs 看接口文档 |
| MySQL     | 3306 | 库 zhiqiu        |
| Redis     | 6379 |                  |
| Mosquitto | 1883 | 账号见 .env      |
| Chroma    | 8100 | 避免与后端冲突   |

---

# 20. 风险与预案

## 20.1 项目风险

| 风险                                 | 概率 | 预案                                                                                   |
| ------------------------------------ | ---- | -------------------------------------------------------------------------------------- |
| 12 天完不成全部 REQ                  | 中   | 按第 17 章 D9 起的顺序自然截断，材料线永不受影响                                       |
| K10 在 PlatformIO 板型适配折腾       | 中   | 退路：K10 用 Arduino IDE + ESP32 板支持包装固件（代码同源），PlatformIO 仅用于 ESP32-E |
| Claude 大改后系统崩                  | 中   | 改前 commit；主分支永远保持可运行版本                                                  |
| 真机浇水翻车（泵不出水/传感器漂移）  | 低   | 现场演示主用 Mock 剧本 15.1（100% 可控），Real 剧本 15.4 作为彩蛋                      |
| 评委质疑"7 个 Prompt 不算真多智能体" | 高   | 标准答辩口径见 8.1 权限表：工具白名单+权限拒绝留痕+独立验证者+并行调度，全部有物证     |

## 20.2 LLM 降级规则模板（REQ-F-001 的一部分）

LLM 连续失败时，各 Agent 用固定模板输出（保证流程不断）：

- 巡园管家：直接拼接最新遥测数据为播报文本（纯代码，无 LLM）。
- 决策官：`若土壤<40% 且无霜冻/降雨预警 → irrigate 30s；否则 none`（硬编码决策树）。
- 验证官：验证引擎本身是纯规则（第 11 章），天然不依赖 LLM——这是刻意设计，**裁判不依赖可能罢工的大脑**。

## 20.3 答辩必背三问

1. **多 Agent 多在哪**：身份独立（提示词+工具白名单+独立上下文）、协作编排（DAG+并行）、动态调度（打分选派+退避重试）、相互制衡（决策者无硬件权，验证者独立复测）。
2. **这不是 7 个 Prompt 吗**：业界定义 Agent = LLM+角色+工具+记忆+自主调用（Dify/Coze/LangGraph 同构）；本项目的价值在职责解耦后的工程能力：权限隔离、可观测、物理验证闭环——后三者任何纯 Prompt 方案都给不出。
3. **Self-Loop 和别人的区别**：常见 Self-Loop 是"生成→自评→重写"的文本循环，裁判是模型自己；本项目的裁判是**物理世界的传感器**——浇没浇够，土壤说了算。

---

# 21. 附录

## 21.1 `.env.example` 全文

```ini
# ===== 模式 =====
TZ=Asia/Shanghai

# ===== MySQL =====
MYSQL_ROOT_PASSWORD=CHANGE_ME_mysql_root
MYSQL_DATABASE=zhiqiu
MYSQL_USER=zhiqiu
MYSQL_PASSWORD=CHANGE_ME_demo_password

# ===== Redis =====
REDIS_PASSWORD=CHANGE_ME_demo_password

# ===== Mosquitto =====
MQTT_USER=tea
MQTT_PASSWORD=CHANGE_ME_mqtt

# ===== LLM =====
LLM_PROVIDER=glm            # glm | deepseek
GLM_API_KEY=填你的key
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
GLM_MODEL=glm-4-flash
DEEPSEEK_API_KEY=填你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# ===== 后端 =====
SECRET_KEY=换成长随机串
ADMIN_TOKEN=换成访问令牌
```

## 21.2 docker-compose 服务清单

| 服务      | 镜像                                     | 端口     | 依赖/健康检查                           |
| --------- | ---------------------------------------- | -------- | --------------------------------------- |
| backend   | 自建 Dockerfile（python:3.11-slim）      | 8000     | mysql/redis/mosquitto/chroma 健康后启动 |
| frontend  | 自建（node:20 build → nginx:alpine）    | 5173→80 | backend                                 |
| mysql     | mysql:8.0                                | 3306     | healthcheck: mysqladmin ping            |
| redis     | redis:7-alpine（带密码）                 | 6379     | —                                      |
| mosquitto | eclipse-mosquitto:2（带账号配置+持久化） | 1883     | —                                      |
| chroma    | chromadb/chroma                          | 8100     | 数据卷持久化                            |

数据卷：mysql_data / mosquitto_data / chroma_data / uploads。全部服务 restart: unless-stopped。

## 21.3 视频 3-5 分钟分镜要点（材料线用）

| 段     | 内容                                        | 时长 |
| ------ | ------------------------------------------- | ---- |
| 开场   | 一句话定位 + 大屏全景                       | 20s  |
| 痛点   | 传统灌溉靠经验 vs 我们靠数据+闭环           | 30s  |
| 架构   | 画布页讲 7 Agent 编排与并行（用 15.3 素材） | 60s  |
| 主戏   | 两轮对照剧本 15.1 全程（加速剪辑）          | 90s  |
| 真机   | Real 模式真浇水 15.4 片段                   | 40s  |
| 工程性 | Docker 一键启动 + 任务轨迹 + 报告导出       | 30s  |
| 收尾   | 团队与展望（对接真实茶园/扩展更多作物）     | 20s  |

配乐轻电子，字幕全程，不出镜。剪映：录屏素材 + 自动字幕 + 2 倍速处理等待段。

## 21.4 版本记录

| 版本 | 日期       | 说明                                                                                          |
| ---- | ---------- | --------------------------------------------------------------------------------------------- |
| v1.0 | 2026-11-03 | 首版施工级 PRD，项目名暂用代号「知秋」                                                        |
| v1.1 | 2026-11-09 | 团队扩为 4 人；第 17 章重排为四人分工与冲刺排期；硬件负责人统一为队友 C；第 18 章对齐 TEAM.md |

---

**文档结束。使用方式重申：给 Claude 下任务时引用需求编号（如"实现 REQ-F-014，DoD 见文档"）；每完成一项在 16 章总表勾验收。**

---
