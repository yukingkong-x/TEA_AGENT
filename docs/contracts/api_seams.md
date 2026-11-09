# 跨地盘接口接缝（api_seams）与实现偏差记录

> 维护人：队友 B（后端基座）
> 用途：基座线跟智能体线（队长）、前端线（队友 A）的对接点全写在这里。**改这里之前先开 issue**。
> 契约本体仍然是 PRD 第 5、7 章；本文件只记录「PRD 没写死、但代码必须先定下来」的部分。

---

## 一、基座给队长提供的（队长直接 import / 调函数）

| 能力 | 位置 | 签名 | 说明 |
| --- | --- | --- | --- |
| 数据库会话 | `app.db` | `session_scope()` / `get_db()` / `SessionLocal` | 线程里用 `session_scope()`，路由里 `Depends(get_db)` |
| 全部 14 张表模型 | `app.models` | `from app.models import Device, Task, ...` | 一表一文件，字段照 PRD 第 6 章 |
| **唯一指令下发通道** | `app.devices.command` | `send_cmd(db, device_id, action, params, *, task_no=None, issued_by="api:manual") -> dict` | `issued_by` 白名单：`agent:executor` / `api:manual` / `system:*`；其他人调直接 `PermissionError` |
| 回执完成钩子 | `app.devices.command` | `register_finish_handler(fn)` | `fn(event: dict)`，event 含 `task_no / device_id / result / detail`。**验证引擎挂在这里** |
| 指令超时钩子 | `app.devices.command` | `register_timeout_handler(fn)` | event 含 `task_no / device_id / action / overdue_s`。**重试/熔断策略挂在这里** |
| 设备在线判定 | `app.devices.registry` | `online_state(device_id)` / `list_states(db)` | 45s / 120s 三态口径只在这里算 |
| WS 广播 | `app.core.ws_manager` | `manager.publish_threadsafe(type, data)`（线程）/ `await manager.broadcast(...)`（协程） | type 全集见 PRD 7.4 |
| 运行期配置 | `app.core.runtime_settings` | `get_value(key, default)` / `set_many({...})` / `get_mode()` | mode、阈值、调度参数都在这里，带 Redis 缓存 |
| Mock 天气数据源 | `app.mock.simulator` | `get_weather(city="A区茶园", hours=24) -> {temp_range, rain_prob, frost_risk, scenario}` | PRD 7.3 的 `get_weather` 工具直接调它 |
| 任务号生成 | `app.core.ids` | `new_task_no()` / `new_msg_id()` | Redis INCR，按天归零 |
| API Key 加解密 | `app.core.crypto` | `encrypt/decrypt/mask` | settings 表里的 `llm_api_key` 已加密 |

### 基座需要队长提供的（**签名请按这个来，否则我这边只能 503**）

`app/api/_common.py::delegate()` 按下面的路径去找，找不到就返回
`503 {"detail": "依赖模块 xxx 尚未就绪（队长 地盘）"}`，前端据此显示「模块未就绪」。

| 能力 | 约定位置 | 约定签名 | 谁在用 |
| --- | --- | --- | --- |
| 触发一次工作流 | `app.workflow.service.start_run` | `start_run(wf_id: int, trigger: str) -> {"run_id": int}` 或 `int` | `POST /api/workflows/{id}/run`（画布页的「执行」按钮） |
| DAG 校验（可选） | `app.workflow.engine.validate_dag` | `validate_dag(dag: dict) -> list[str]`（空列表=通过） | 保存工作流时；没提供就用我写的 `api/_dag.py` 兜底 |
| 手动验证 | `app.verification.service.verify_task` | `verify_task(task_no: str) -> dict{achievement, confidence, conclusion}` | `POST /api/verify/{task_no}` |
| 生成报告 | `app.verification.report.generate_report`（备选 `app.reports.generator.generate_report`） | `generate_report(run_id: int) -> int`（返回 report_id） | `POST /api/reports/generate?run_id=` |
| 知识库入库 | `app.knowledge.loader.ingest` | `ingest(path: str, doc_id: int) -> {"chunk_count": int, "chroma_ids": [...]}` | `POST /api/knowledge/upload`（后台线程里跑，别阻塞） |
| 知识库检索 | `app.knowledge.retriever.search` | `search(question: str, top_k: int) -> [{title, chunk_text, score, doc_id}]` | `POST /api/knowledge/search` |

> 这五处如果队长想换名字，改 `api/*.py` 里的一行 `delegate("...", "...")` 即可，不用动别的。

---

## 二、基座给队友 A 提供的（REST / WS 清单）

前缀 `/api`，全部 GET 无鉴权；写操作在 `ENFORCE_AUTH=true` 时才校验 `X-Admin-Token`。

| 页面 | 接口 |
| --- | --- |
| 大屏 | `GET /api/sensor/latest`、`GET /api/devices`、`GET /api/alerts`、`WS /ws/dashboard` |
| 画布 | `GET /api/workflows`、`PUT /api/workflows/{id}`、`POST /api/workflows/{id}/run`、`GET /api/runs/{id}` |
| 对话剧场 | `GET /api/runs/{id}`（含 `messages`）、WS `agent_message` |
| 任务中心 | `GET /api/tasks?status=&page=`、`GET /api/tasks/{task_no}`、WS `task_status` |
| 报告页 | `GET /api/verify`、`GET /api/reports`、`GET /api/reports/{id}`、`POST /api/reports/generate?run_id=` |
| 设置页 | `GET/PUT /api/settings`、`POST /api/settings/mode?mode=`、`GET/POST/PUT/DELETE /api/agents`、`GET /api/knowledge` |
| 演示开关（新增） | `POST /api/devices/fault`、`DELETE /api/devices/fault`、`POST /api/devices/weather`、`GET /api/devices/mock` |
| 调试 | `GET /api/devices/mqtt`（MQTT/Redis 链路统计）、`GET /api/health` |

WS 消息统一：`{"type": "...", "data": {...}, "ts": 1730700000}`，type ∈
`telemetry / device_status / task_status / agent_message / node_state / run_status / alert / mode_changed`。
连接建立后立刻收到一帧 `mode_changed`（`data.hello=true`），前端用它点亮顶部状态条；客户端每 20s 发 `{"type":"ping"}` 保活。

分页统一：`{ items, total, page, page_size, pages }`。

---

## 三、实现偏差与取舍（相对 PRD 原文，已选更稳的一边）

| # | PRD 原文 | 实现 | 原因 |
| --- | --- | --- | --- |
| 1 | 7.5「全部异步（asyncio）」 | HTTP 路由用同步 `def`（Starlette 线程池），DB 用同步 SQLAlchemy+PyMySQL；只有 WS 与 lifespan 是 async | PRD 3.2 锁的是 PyMySQL（同步驱动）；3 设备量级下同步更简单、没有异步 DB 的坑。MQTT 回调本就在 paho 线程里 |
| 2 | 6.2「sensor_data 分区按月或按 id 范围」 | 不分区，只建 `(device_id, metric, ts)` 索引 | 量级（3 设备×30s ≈ 3 万行/天）不需要；分区表 `create_all` 建不出来，赛期引分区风险大于收益 |
| 3 | 7.1 `config.py` 读 .env 与 settings 表 | 静态配置在 `config.py`，运行期配置在 `core/runtime_settings.py`（settings 表 + Redis 缓存） | 启动前连不上库，import 期查表会让服务起不来 |
| 4 | 21.2 backend 依赖 chroma 健康后启动 | chroma 改为 `required: false` | Chroma 镜像 1GB+，网络差时会把整个平台拖住；只有 RAG 用得到它 |
| 5 | 21.1 `.env.example` 里有行内注释 | 注释独立成行 | docker `env_file` 会把 `# ...` 当成变量值，`LLM_PROVIDER=glm  # glm | deepseek` 会解析失败 |
| 6 | 12.2 模拟设备名 `mock-*` | 照做（`mock-k10-field-01` 等 3 台，`is_mock=true`） | 与真设备 id 不冲突；前端可用 `is_mock` 分组显示 |
| 7 | 5.2 遥测 `metrics` 允许缺键 | 非数值指标跳过并告警（不允许错型） | 与 PRD「允许缺键不允许错型」一致 |
| 8 | 6.14 `llm_api_key` 加密存 | Fernet（SECRET_KEY 派生）+ `enc:` 前缀，接口读一律掩码 | SECRET_KEY 换掉后旧 key 解不开，设置页需重填 |
| 9 | 7.4 `GET /docs` | FastAPI 自带 `/docs`（不在 `/api` 下） | 与框架默认一致，PRD 行文里的 `/docs` 本来就是根路径 |

---

## 四、还没做的（等队长/队友 C 的输入）

- `app/api/verify.py`、`knowledge.py`、`reports.py` 三处 503 依赖队长落地（见上表）
- 报告 PDF 导出（F-022 另一半）在前端，后端只出 Markdown
- Real 模式端到端（REQ-H-003）要等队友 C 三板同网段，基座侧已就绪
- `docs/contracts/` 里没有 MQTT 契约变更：报文严格照 PRD 第 5 章实现
