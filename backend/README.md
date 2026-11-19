# 后端模块 · 开工手册（队友 B）

> 一句话：让平台"活着"——服务起得来、数据进得库、接口都通、一键能启动。你是全队的数据中枢。
> 你的规格书：PRD 第 5 章（MQTT 契约）、第 6 章（数据库 14 张表）、第 7 章（后端规格）、第 12 章（Mock/Real）、第 21 章（compose 配置）。冲突以 PRD 为准。
> 团队规矩：先读仓库根目录的 `TEAM.md`。

---

## 你管什么 / 不管什么

- **管**：`backend/app/` 里的 `core/`（llm.py 除外）、`api/`、`models/`、`devices/`、`mock/`；根目录 `docker-compose.yml`、`.env.example`；`deploy/` 配套配置
- **不管**：`backend/app/` 的 `agents/`、`workflow/`、`orchestrator/`、`verification/`、`knowledge/`——那是队长的智能体地盘；他要新表/新接口，开 issue 给你
- **不管**：`frontend/`、`firmware/`

## 技术栈与环境准备（一次性）

| 要装           | 说明             |
| -------------- | ---------------- |
| Docker Desktop | 六个服务全靠它起 |
| Python 3.11    | 本地调试用       |
| VSCode + Git   | 全队一致         |

技术栈（已锁定）：FastAPI + SQLAlchemy + MySQL 8 + Redis 7 + paho-mqtt（Mosquitto）+ Chroma。

## 你的任务（对照 PRD 17.2 排期表"队友 B"一列）

| 日期     | 任务                                                       | 对应 REQ                              |
| -------- | ---------------------------------------------------------- | ------------------------------------- |
| 11.9-10  | compose 六服务 + 14 张表建模 + MQTT 订阅入库 + Mock 模拟器 | REQ-F-023 + REQ-F-019 半              |
| 11.11-12 | REST API 全清单 + WebSocket 推送                           | PRD 7.4 全表                          |
| 11.13    | Mock/Real 切换收尾 + 5 种故障注入 + 一键启动打磨           | REQ-F-019 收尾                        |
| 收尾     | 修致命 bug + README 打磨                               | REQ-F-023 验收：新电脑 3 分钟内可访问 |

## 对接关系

- **从 C 拿**：MQTT 上行报文（主题 `tea/device/{id}/telemetry | status | ack`，报文格式 = PRD 5.2~5.4；要改必须经队长）
- **给 A**：全部 REST/WS 接口——字段一处都不能对不上，改了在群里喊
- **给队长**：`models/` 数据表 + `devices/command.py`（全平台唯一的指令下发通道）
- **给全队**：`docker compose up -d` 一键起全家桶；端口表 = PRD 19.5（前端 5173 / 后端 8000 / MySQL 3306 / Redis 6379 / Mosquitto 1883 / Chroma 8100）

## 今天第一步（D7 就干这个）

1. 写 `docker-compose.yml` 六服务：backend（python:3.11-slim 自建）/ frontend 占位 / mysql:8.0 / redis:7（带密码）/ mosquitto:2（带账号）/ chroma——全部挂数据卷、restart: unless-stopped（清单照抄 PRD 21.2）
2. SQLAlchemy 建 14 张表（PRD 第 6 章逐张照抄）
3. `core/mqtt_client.py`：订阅 telemetry → 写 sensor_data 表
4. `mock/simulator.py`：假设备按第 5 章报文格式发数据——它也是开发期全队的假设备，行为要跟固件一致（同一 cmd 同样 ack）

## Git 速记

```bash
git switch -c feature/backend-compose    # 你的分支
# commit 格式：feat(models): 建 14 张表
git push → GitHub 开 PR → 等队长 review 合并
```

- 禁止直接 push main；`.env`（真 Key / 真密码）永不进仓库，只提交 `.env.example`
- AI 生成的代码先看懂再提交，PR 里注明你验证了什么

## 卡住了

群里 @ 队长，当天必须有人回；卡超过半天直接语音。

---

## 实际运行手册（2026-11-09 基座线落地后更新）

### 一键启动

```bash
cp .env.example .env      # 只需填 LLM key，其余默认值可直接跑
docker compose up -d --build
# 后端 http://localhost:8000/docs   （前端 5173 要等队友A的 Dockerfile，用 --profile ui）
```

- 宿主机 MySQL 是 **3307**（躲开本机已装的 MySQL），容器内仍是 3306
- 容器里跑不通网络时：`docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple backend`
- Chroma 在 compose 里是 `required: false`，镜像大、网络差也不会拖住平台启动

### 已落地的东西（对照 PRD）

| PRD | 落点 |
| --- | --- |
| 6.1~6.14 十四张表 | `app/models/`（一表一文件，启动 `create_all` 自动建） |
| 5.1~5.5 MQTT 契约 | `app/core/mqtt_client.py`（QoS1 订阅、双通道 cmd、ack 两阶段、seq/msg_id 幂等） |
| 5.5 在线三态 | `app/devices/registry.py`（45s / 120s，离线写 alerts + WS 广播） |
| 5.3/5.4 指令通道 | `app/devices/command.py`（**唯一**下发出口，`issued_by` 白名单，duration 上限 120s） |
| 7.4 REST 全清单 | `app/api/*.py`（含 `/ws/dashboard` 八种推送类型） |
| 12.2 Mock 模拟器 | `app/mock/simulator.py`（三虚拟设备 + 五种故障注入 + 四档天气） |
| 12.1 Mock/Real | `app/core/runtime_settings.py` + `POST /api/settings/mode`（切换即起停模拟器并广播） |
| 21.2 六服务 compose | `docker-compose.yml` + `deploy/` |
| O-001 设备种子 | `app/seed.py`（3 台真设备 + 10 个配置键，幂等） |

### 常用自测命令

```bash
# 单元测试（不需要任何外部服务）
.venv/Scripts/python.exe -m pytest tests -q

# 看链路是否通
curl http://localhost:8000/api/health
curl http://localhost:8000/api/devices/mqtt

# 手动浇水 5 秒（Mock）
curl -X POST http://localhost:8000/api/devices/mock-k10-act-03/cmd \
  -H "Content-Type: application/json" -d '{"action":"pump","params":{"duration_s":5}}'

# 故障注入（演示两轮对照）
curl -X POST http://localhost:8000/api/devices/fault -d '{"fault":"stuck_moisture"}' -H "Content-Type: application/json"
curl -X DELETE http://localhost:8000/api/devices/fault
```

### 还没接的地方

跨地盘调用的约定全写在 [`docs/contracts/api_seams.md`](../docs/contracts/api_seams.md)：
队长提供 `app.workflow.service.start_run` / `app.verification.service.verify_task` /
`app.verification.report.generate_report` / `app.knowledge.loader.ingest` / `app.knowledge.retriever.search`
五个函数，没落地前对应接口返回 503（不是 500，前端能显示「模块未就绪」）。

