# TEA_AGENT

# 茶园多智能体编排平台

> **一句话**：7 个 AI 智能体协作管茶园——决策 → 真实浇水 → 传感器复测 → 达成率验证 → 自动修正，用真实物理闭环证明 Agent 的决策在现实世界有效。
>
> 「茶博士」为本项目正式名称（曾用临时代号「知秋」），代码内部标识 zhiqiu 沿用不改，不影响任何技术内容。

**参赛**：2026 第五届"未来杯"创新大赛 · Agent 编排创新应用赛题
**排期**：11.9 四线开工 ｜ 11.14 冻结 ｜ **11.15 提交线**

---

## 1. 这是什么

- **感知**：茶园里的三块板（行空板 K10 ×2 + ESP32-E ×1）定时上报土壤湿度、空气温湿度、光照；
- **决策**：7 个各司其职的智能体（巡园管家、气象员、土壤师、植保员、灌溉决策官、执行管家、验证审计官）由 DAG 工作流引擎编排协作，决定要不要浇水；
- **执行**：指令真的下发到水泵，水真的浇下去；
- **验证**：传感器复测土壤湿度，验证引擎算出"达成率"，没达标就自动生成修正任务再来一轮。

数据流一条线，最后在网页汇合：

```
硬件（队友C）→ 后端（队友B）→ 智能体（队长）→ 前端（队友A）→ 评委/茶农看到的网页
```

## 2. 核心亮点（对着赛题评分点）

| 亮点                   | 说明                                                                  |
| ---------------------- | --------------------------------------------------------------------- |
| 7 个真智能体           | 每个都有独立提示词与工具权限，权限分离——只有执行管家能下水泵指令    |
| 工作流编排             | DAG 默认工作流 + 动态调度：按数据打分决定谁上场，支持并行、重试、熔断 |
| Self-Loop 物理闭环     | 决策 → 执行 → 复测 → 达成率 → 修正，赛题核心考点                  |
| 结果验证               | 三路置信度 + 达成率报告（红/黄/绿圆环）                               |
| 真实硬件               | MQTTX 里能看到真报文，水是真浇的                                      |
| Mock / Real 双模式     | 没带板子也能一键演示全套流程                                          |
| MCP Server（SSE /mcp） | 工具池对外暴露，赛题加分项                                            |
| Docker 一键启动        | 新电脑 `docker compose up -d`，3 分钟内页面可访问                   |

技术栈一句话：React 18 + Vite + React Flow + ECharts ｜ FastAPI + MySQL 8 + Redis 7 ｜ GLM-4-Flash（主）+ DeepSeek（备）+ Chroma RAG ｜ 行空板 K10 / ESP32-E ｜ MQTT（Mosquitto）+ Docker Compose。

## 3. 团队与分工

| 岗位                  | 谁         | 地盘                                                                                              |
| --------------------- | ---------- | ------------------------------------------------------------------------------------------------- |
| 队长 · 智能体 + 统筹 | __________ | `backend/app/` 的 agents / workflow / orchestrator / verification / knowledge + `core/llm.py` |
| 队友A · 前端         | __________ | `frontend/`                                                                                     |
| 队友B · 后端基座     | __________ | `backend/app/` 其余子目录 + `docker-compose.yml` + `deploy/`                                |
| 队友C · 硬件         | __________ | `firmware/` 三个工程 + 实体设备                                                                 |

协作规矩 → [TEAM.md](TEAM.md)；需求与接口契约 → [PRD](PRD_茶园多智能体平台_需求文档_v1.md)。

## 4. 目录结构

```
├── frontend/       前端六页（大屏/画布/对话/任务/报告/设置）    ← 队友A
├── backend/app/    FastAPI 后端
│   ├── core/  api/  models/  devices/  mock/                  ← 队友B
│   └── agents/  workflow/  orchestrator/  verification/  knowledge/   ← 队长
├── firmware/       k10_field / esp32_soil / k10_act 三个工程   ← 队友C
├── deploy/         compose 配套配置                            ← 队友B
├── docs/           contracts（契约变更）/ meeting（站会）/ material（资料）/ hardware_log.md（实测）
├── TEAM.md         协作手册——新人必读
├── README.md       本文件
└── PRD_茶园多智能体平台_需求文档_v1.md   施工总纲（需求编号即任务）
```

## 5. 快速开始

```bash
# 1. 配置：复制 .env.example 为 .env，填 MySQL/Redis/MQTT 密码和 LLM key
# 2. 一键启动六个服务（前端 / 后端 / MySQL / Redis / Mosquitto / Chroma）
docker compose up -d
# 3. 打开
#    前端大屏  http://localhost:5173
#    后端接口  http://localhost:8000/docs
```

各模块的开发手册（动手前先看自己那本）：

- 前端 → [frontend/README.md](frontend/README.md)
- 后端 → [backend/README.md](backend/README.md)
- 智能体 → [backend/app/agents/README.md](backend/app/agents/README.md)
- 硬件 → [firmware/README.md](firmware/README.md)

## 6. 当前进度

- [X] PRD v1.1 施工级定稿（21 章，需求编号 + 排期）
- [X] TEAM.md 协作手册 + 四个模块开工手册
- [X] 仓库骨架 + 分支 / PR 规矩
- [ ] 11.9-10 四线并行动工（各自任务对照 PRD 17.2）
- [ ] 11.13 Real 模式端到端 + 彩排
- [ ] 11.14 冻结 + 方案书 / PPT / 视频定稿
- [ ] 11.15 提交

---
