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
| **统一查询口径** | `app.core.queries` | `soil_status(db, device_id=None)` → `{moisture, state: dry/ok/wet/unknown, target_range, trend_per_min, points, online}`；`env_status(db, device_id=None)` → `{readings: {temperature_c, humidity_air, lux, co2?}, online}`；`device_overview(db)`；`raise_alert(db, level, source, message)`（level ∈ info/warning/critical，写库+推 WS） | **工具池取数只准走这里**：`get_soil_status` / `get_env_status` / `raise_alert` 直接调用，Mock/Real 口径只有一份 |
| **工具池接线层** | `app.core.tool_impl` | `get_registry()` → 队长的注册表（9 个桩已换真实现）；`wire_into_app(app)` 挂 MCP | 组合根模式，见下节 |

### 工具池已接线（2026-11-10 实测，队长 `tools.py` 一行不用改）

`app/core/tool_impl.py` 在启动时把队长 `tools.py` 里 9 个 `ToolNotReady` 桩换成真实现，
**保留他的描述与参数 schema，只换 `fn`**。队长想自己接管时，删掉 `_WIRED` 里对应一行即可。

| 工具 | 真实现 | 数据/通道 |
| --- | --- | --- |
| `get_weather` | `tool_impl.get_weather` | settings 表 `weather_scenario` → 模拟器 `WEATHER_PRESETS`（**单一事实源**，改配置即时联动） |
| `get_soil_status` / `get_env_status` | `queries.soil_status` / `env_status` | `sensor_data` 最新点 + 趋势 |
| `send_device_cmd` | `command.send_cmd(issued_by="agent:executor")` | 唯一指令出口，白名单已预留 `agent:executor` |
| `create_task` | 直接插 `tasks` 表 | `new_task_no()`，status=pending |
| `raise_alert` | `queries.raise_alert` | alerts 表 + WS 广播 |
| `verify_result` / `write_report` / `query_knowledge` | `seams.verify_task` / `generate_report` / `search` | 队长的验证/报告/知识库，未就绪时错误带约定签名回填给 LLM |

**MCP Server 挂载**：`McpSseServer.build_app()` 自带 `/mcp/sse` 与 `/mcp/messages`，
必须用 `app.mount("/", ...)`（根挂载）；`mount("/mcp")` 会叠成 `/mcp/mcp/*`，
`include_router` 也挂不了（返回的是完整 FastAPI 应用）——队长 docstring 里那行已过时。

**已知待补**：`/mcp/messages` 目前无鉴权（比赛演示可接受，公网部署前需加 token）。

### 基座需要队长提供的（**只认 `app/seams.py` 这一个文件**）

基座不再直接 import 队长的模块。所有跨地盘调用都过 `backend/app/seams.py`
（门面/适配层）。它目前是「自动找 + 找不到就 503」：

```
HTTP 503
{"detail": "触发工作流尚未就绪（队长地盘）：app.workflow.service 导入失败（ModuleNotFoundError...）
           ｜约定 start_run(wf_id: int, trigger: str) -> {run_id}｜调用方 POST /api/workflows/{id}/run",
 "seam": "start_run", "code": "SEAM_NOT_READY"}
```

**队长侧只有两种接法，任选一种，基座 api/*.py 一行都不用改：**

- **接法 1（零改动）**：模块路径 + 函数名跟下表一致，落地即生效。
- **接法 2（想用别的名字）**：直接改 `app/seams.py` 里对应函数的两行，例如

  ```python
  def verify_task(task_no: str):
      from app.verification.engine import check_task   # 你真正的实现
      return check_task(task_no)
  ```

| 接缝 key | 默认找哪里 | 约定签名 | 谁在用 |
| --- | --- | --- | --- |
| `start_run` | `app.workflow.service.start_run` | `start_run(wf_id: int, trigger: str) -> {"run_id": int}` 或 `int` | `POST /api/workflows/{id}/run`（画布「执行」按钮） |
| `validate_dag` | `app.workflow.engine.validate_dag`（备选 `validate`） | `validate_dag(dag: dict) -> list[str]`，空=通过 | 保存工作流；**没提供或抛错就用基座本地闸门 `api/_dag.py`** |
| `verify_task` | `app.verification.service.verify_task` | `verify_task(task_no: str) -> {achievement, confidence, conclusion}` | `POST /api/verify/{task_no}` |
| `generate_report` | `app.verification.report.generate_report`（备选 `app.reports.generator.generate_report`） | `generate_report(run_id: int) -> int`（report_id） | `POST /api/reports/generate?run_id=` |
| `ingest` | `app.knowledge.loader.ingest` | `ingest(path: str, doc_id: int) -> {"chunk_count": int, "chroma_ids": [...]}` | `POST /api/knowledge/upload`（后台线程跑，别阻塞） |
| `search` | `app.knowledge.retriever.search` | `search(question: str, top_k: int) -> [{title, chunk_text, score, doc_id}]` | `POST /api/knowledge/search` |

> 参数名怎么写都行：`seams` 会先读函数签名，签名认不出才退化成按位置传参，
> **不会靠 `try/except TypeError` 重试**——那样 `start_run` 会建出两条 run。
>
> 体检：`GET /api/health` 的 `seams` 字段一眼看出六项谁 ready 谁 not_ready；
> 启动日志也有一行「跨地盘接缝：就绪 [...] / 缺失 [...]」。


---

## 二、基座给队友 A 提供的（REST / WS 清单）

前缀 `/api`，全部 GET 无鉴权；写操作在 `ENFORCE_AUTH=true` 时才校验 `X-Admin-Token`。

| 页面 | 接口 |
| --- | --- |
| 大屏 | `GET /api/sensor/latest`、`GET /api/devices`（见下注）、`GET /api/alerts`、`WS /ws/dashboard` |
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

> **`GET /api/devices` 的分组约定（给 A，2026-11-14 修订）**
> **缺省返回全量 6 台（3 真机 + 3 台 `mock-*`），与 PRD 原文一致，没有变过**——
> 11-14 当天曾短暂改成「按当前模式过滤」，已回退，你按 `is_mock` 字段自己分组即可。
> 原因：演示现场常见 Mock 与真机同时在跑（真板子在烧、模拟器也开着），后端按模式筛两头都丢信息；
> 且契约默认值变更必须走 issue（PRD 3.1），不能悄悄变。
> 需要后端替筛时用查询参数（这三个值之外的输入返回 400）：
> - `?is_mock=true` / `?is_mock=1` → 只要 Mock
> - `?is_mock=false` / `?is_mock=0` → 只要真机
> - `?is_mock=all` → 全量，等同缺省
>
> 每台设备都带 `is_mock`、`online`、`state`（online/suspect/offline）三个字段，前端分组不必猜测。

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
| 10 | 5.4 幂等去重 `device_id+seq` | seq 去重键带上报文里的 `boot_id`（本次开机的随机标识），TTL 120s | 设备/模拟器重启后 seq 归零重计：原实现（TTL 3600、不含 boot_id）会让重启后 1 小时内的遥测全被当成重复静默丢弃——真机重启同样会踩。QoS1 秒级重复由 120s TTL 覆盖，`msg_id` 去重不变 |
| 11 | （PRD 未写）土壤模型加残余含水量下限 12% | 蒸发在接近下限时线性放缓，湿度不再无限下降 | 隔夜跑 14 小时会把湿度耗到 0%，第二天演示全是 0.0；真实土壤束缚水也蒸发不掉 |
| 12 | （PRD 未写）`GET /api/sensor/history` 的 `limit` 语义 | 取**最新** N 个点（先倒序取再反转） | 此前升序+limit 返回窗口里最老的 N 个点，前端曲线和 `get_soil_status` 会拿到几小时前的旧数据 |
| 13 | （运维注意）宿主机休眠会导致遥测断流 | 演示脚本预演前有数据龄体检；`scripts/demo_rehearsal.py` 遇陈旧数据自动等待新鲜点 | Windows 睡眠会暂停 Docker VM；演示前确认 `soil_age` < 70s（见第 0 幕） |
| 14 | 9.1 默认工作流里 `n11b`（Self-Loop 的 loop 节点）没有任何入边 | `validate_dag` 把 loop 视为「环绕 `body_next` 的结构标记」：body 可达即 loop 可达，且 loop 的 `next` 继续参与扩散；非 loop 节点仍必须从 start 可达 | 照普通顶点判可达性会把 PRD 原文 DAG 判成非法（`n11b` 不可达）→ 画布一保存默认工作流就 400 → PRD 9.4 第一条验收不成立。回归用例：`tests/test_base_logic.py::test_dag_prd_default_workflow_passes` |
| 15 | 5.3 指令下发 | `send_cmd` 内部先 `db.commit()` 再 `publish()`，提交责任收进函数；调用方再 commit 一次无害 | 设备 ack 是毫秒级回来的，在 paho 线程用另一个 session 查 Task。只 flush 不提交时对方看不见 → `task=None` → 只广播不落库 → 任务永远卡 dispatched，超时后补一条假的「指令超时」报警。回归用例：`tests/test_command_flow.py` |
| 16 | 6.14 设置页写 `llm_api_key` | `set_many` 加硬闸：空值不改、值含 `*` 或以 `enc:` 开头一律跳过并 warning | `GET /api/settings` 返回 `sk-a****wxyz`，前端把整张表单原样 PUT 回来是最常见写法；掩码当明文再加密落库 → LLM 全线 401 且极难排查。不能只靠「空串=不改」 |
| 17 | 7.4 `GET /api/devices` 返回全部设备 | **缺省返回全量**（沿用 PRD 原文）；只有显式 `?is_mock=true/false` 才过滤，`all` 等同缺省 | 曾一度把缺省改成「按当前 mode 过滤」，队长 review 判定为契约默认值悄悄变更（违反 PRD 3.1）：演示现场 Mock 与真机常同时在跑（真板子在烧、模拟器也开着），两个方向都在丢信息，且前端大屏按「6 台」写死。**已回退**，要再改必须走 issue。回归用例：`tests/test_device_list.py` |
| 20 | 6.11 `alerts.source` 区分发起方 | 缺省值读 `ContextVar CURRENT_AGENT_KEY`（队长 `base.py` 在 `_execute_tool` 里 set/reset），格式 `agent:{key}`；显式传参优先，裸 key 自动补 `agent:` 前缀 | LLM 的工具 schema 只有 `level`/`message`，传不进 source；靠 runner 的调用上下文隐式带入，既不改 schema 也能落对身份。verification 这类确定性判定直连调用时显式传 `agent:verifier`（更可靠，不依赖上下文）。已知边界：丢线程池执行不会继承 ContextVar，需 `copy_context().run(...)` |
| 18 | 5.2 遥测 `ts` 直接用上报值 | `abs(ts-now) > 300s` 时改用服务器时间并记 warning | 固件无 RTC / 掉电回到 1970 是常见故障：脏 ts 会污染曲线、让 `sweep_offline` 立刻判离线、趋势计算全废 |
| 19 | 5.5 新设备登记 | `ensure_device` 建新设备时 `online=False, last_seen=None`（不预置在线） | device_id 打错一个字，下发一次指令就凭空造出一台「在线」设备，120s 后再补一条假离线报警；让它等自己的心跳转在线 |
| 20 | 12.2 Mock/Real 切换 | 切 Real 时 `deactivate_mock_devices()` 把 `is_mock` 设备置离线、清 `last_seen` 与报警标记 | 只停模拟器线程不够：`mock-*` 还留在表里，120s 后 `sweep_offline` 连发 3 条假离线报警，演示切真机时大屏突然冒 3 条红点 |

---

## 四、还没做的（等队长/队友 C 的输入）

- `app/api/verify.py`、`knowledge.py`、`reports.py` 三处 503 依赖队长落地（见上表）
- 6 个接缝目前全 `not_ready`：队长的 `workflow/`、`verification/`、`knowledge/` 三个目录尚未提交；
  他的 `agents/`（工具池 + Runner + MCP）已实测可跑，接线层见上节
- `/mcp/messages` 无鉴权（内部工具池，公网部署前需加 token 或限制来源）
- 报告 PDF 导出（F-022 另一半）在前端，后端只出 Markdown
- Real 模式端到端（REQ-H-003）要等队友 C 三板同网段，基座侧已就绪
- `docs/contracts/` 里没有 MQTT 契约变更：报文严格照 PRD 第 5 章实现

## 五、环境验证记录

| 日期 | 项 | 结果 |
| --- | --- | --- |
| 2026-11-14 | 容器内全量测试 `docker compose run --rm --no-deps backend pytest -q` | **55 passed in 3.67s**，容器 Python **3.11.18**（镜像 python:3.11-slim） |
| 2026-11-14 | 宿主 venv 交叉验证（Python 3.13） | 55 passed —— 与容器的 3.11 无差异，说明代码未踩版本特性 |
| 2026-11-14 | 依赖跨版本可解析性 `pip install --dry-run --python-version 3.11 --only-binary=:all:` | 50 个包全部有 wheel，无源码编译依赖 |
| 2026-11-14 晚 | 六接缝接线后容器内全量测试 | **71 passed**，容器 Python 3.11.18（宿主 3.13 同结果） |
| 2026-11-14 晚 | 启动实测 `/api/health` | `status: ok`，`seams` 六项全 `ready`，调度器 1s 一轮，默认工作流 1 条（连续重启两次不重复写） |
| 2026-11-14 晚 | 老库枚举升级 | 启动日志 `tasks.status 枚举已补齐：needs_human`；二次重启无该行（幂等） |
| 2026-11-14 晚 | 指令→回执→终态 | `pump 30s` 下发后 `dispatched→running→success`，`result_json` 落 `executed_s=30.0`、`moisture_gain=10.5` |
| 2026-11-14 晚 | 触发执行 `POST /api/workflows/3/run` | 返回 `run_id`，run 状态 `success`，context 里 6 个 agent 输出齐全（无 key 走规则降级） |
| 2026-11-14 晚 | 掩码回传保护（实测） | 写入真 key → PUT 回 `sk-r****1234` → 库里明文仍是原 key |
| 2026-11-14 深夜 | `task_events` 建表（老库自动补） | MySQL `desc task_events` 10 列齐全，`run_id` = `bigint`、`id` = `bigint auto_increment` |
| 2026-11-14 深夜 | 指令→回执→轨迹端到端 | `pump 6s` → 轨迹 3 行：`null→dispatched(dispatch,human)` → `dispatched→running(ack,device)` → `running→success(ack,device)`，`at` 均为 `2026-11-14T11:17:0x` |
| 2026-11-14 深夜 | `GET /api/tasks/{task_no}/events` | `{items:[...], total:3}`，`id` 升序、`from/to` 可直画；任务号打错 → 404 |
| 2026-11-14 深夜 | 密钥三态（实测三连） | 写入 → `sk-t****7890`；PUT 空串 → 值不变、日志「跳过敏感配置」；PUT `null` → 清空 + WARNING「敏感配置已被清空」 |
| 2026-11-14 深夜 | 全量测试（容器 Python 3.11.18 / 宿主 3.13） | **84 passed**，两条环境同结果；新增 `tests/test_task_events.py` 11 例 |


## 六、六接缝接线后的基座侧改动（2026-11-14 晚）

队长把 `workflow/` `verification/` `orchestrator/` `knowledge/` 全部落地后，基座只需接线；
以下是这一轮动的全部内容，逐条注明理由。

### 6.1 `app/bootstrap.py`：三行接线，但**不用顶部 import**

```python
_install("工作流引擎",   ".workflow.wiring",       "install")
_install("验证引擎",     ".verification.wiring",   "install")
_install("任务调度器",   ".orchestrator.wiring",   "start_scheduler")
# stop_all() 里先 _install(... "stop_scheduler")
```

队长给的写法是模块顶部 `from .workflow.wiring import install`。我改成函数内 `importlib` +
`try/except`，原因只有一个：**顶部 import 缺模块会让 `app.main` 直接导入失败**，连
`/api/health` 都打不开，现场只能看到容器重启循环。放这里，缺模块只表现为该接缝 503 +
health 里 `not_ready`，还能从日志里看到原因。三个 install/start 自身幂等，重复调用无副作用
（已实测连续重启两次，默认工作流仍只有 1 条）。

顺序：引擎（含首启写默认工作流）→ 验证（要读任务/样本）→ 调度器（1s 一跑，最后开）。

### 6.2 `tasks.status` 补 `needs_human` + 老库自动 ALTER

`create_all` 只建表不改列，**已经存在的库改 models 不生效**。`db.init_db()` 里加
`_sync_enum_column()`：查 `information_schema` 比对枚举值，缺才 `ALTER`，非 MySQL 静默跳过。
演示机上是老库，不补会报 `Data truncated for column 'status'`——而且只在验证器转人工那一刻出现。

配套：`POST /api/verify/{task_no}` 现在**把验证结论落成任务终态**
（`success/failed/needs_human`）。理由：验证引擎是依赖注入式的、不碰 ORM，如果没有这一层，
任务会一直停在 `running`，60s 后被调度器判超时 → 重试 → 再超时，形成一轮假重试。
`result_json` 是**合并**写入，不覆盖已有的 ack 明细。

### 6.3 `DELETE /api/knowledge/{doc_id}` 清向量

先 `app.knowledge.loader.delete(doc_id)` 再删记录（反过来会留下"记录没了、向量还在"的孤儿，
检索仍会命中，且没有接口能再清）。向量清理失败不阻断删除，返回 `vectors_removed: "failed"`
并在日志留痕——记录是用户明确要删的，不该因为向量库抖动而删不掉。

### 6.4 设备 ack 刷新 `tasks.updated_at`

`handle_ack` 末尾显式写 `updated_at`。调度器用 `updated_at + timeout_s` 判超时；只改 status 时
若状态恰好没变（重复的 `received→running`），SQLAlchemy 不发 UPDATE、`onupdate` 不触发，
真机慢但一直在回执的任务会被误判超时。已用用例 `test_ack_refreshes_updated_at_even_when_status_unchanged`
钉住（去掉这行赋值立刻红）。

### 6.5 `POST /api/workflows/{id}/run` 改 async

队长 `start_run` 靠 `asyncio.get_running_loop().create_task()` 把执行放后台；同步 `def` 路由跑在
线程池里、没有运行中的事件循环，于是退化成 `asyncio.run()`——**在请求线程里把整条工作流跑完**。
没有 LLM key 时是 0.1s 的规则降级，看不出来；一旦配了 key，14 个节点要一两分钟，前端点「运行」
就是个挂死请求（画布也不动）。改成 `async def` + 预检丢 `asyncio.to_thread`，
实测响应 **0.05s** 返回 `run_id`，执行在后台推进（run 状态随后变 `success`）。
守它的用例：`test_run_endpoint_stays_async`。

---

## 七、任务轨迹（REQ-F-015）与两个契约口径（2026-11-14 深夜）

### 7.1 `task_events` 表 + `GET /api/tasks/{task_no}/events`

表按队长给的 model 原样落 `models/task_events.py`（`run_id` **BigInteger**，与 `tasks.run_id` 一致；
`event` 用 String 不用 Enum——Enum 加值要 ALTER 老库，`tasks.status` 上已经踩过一次）。
`create_all` 只负责建**缺的表**，所以老库启动时这张表会被自动补上（实测 MySQL 里 10 列齐全）。

接口：`?limit=100`（1~500），**按 `id` 升序**，`at` 用 `isoformat(timespec="seconds")`；
`total` 是该任务事件**总数**、不受 limit 影响；任务不存在 404，存在但没事件返回空数组。
为什么不按 `created_at` 排序：ack 与状态变更常常落在同一秒，按时间排会乱序。

### 7.2 设备指令链自己落轨迹（**补一个覆盖缺口**）

队长 `orchestrator/wiring._emit` 只在**调度器**改状态时记轨迹。而 `devices/command.py`
是另一条独立链路：它自己把 `pending→dispatched→running→success` 改完、自己广播
`task_status`，从不经过调度器。实测后果：`POST /api/devices/{id}/cmd` 跑完一次浇水，
任务状态正常但轨迹 **0 行**——而「设置页点一下浇水 → 任务列表点开看轨迹」是演示里被点最多的路径。

补法：新增 `app/core/task_trail.py::record(db, ...)`，在 `send_cmd` / `handle_ack` /
`sweep_ack_timeouts` 三处跟着**同一个事务**写一行。三条约束：

- 拼装与去重**复用** `orchestrator.events.build / is_duplicate`（口径与调度器侧完全一致，
  不另写一套），模块缺失时静默降级、只警告一次；
- 用 `db.begin_nested()`（SAVEPOINT）包住插入：轨迹写失败只丢这一行，
  调用方「改状态」的事务照常提交——轨迹是加分项，不能让浇水指令跟着失败；
- 重复回执（`running→running`）由 `is_duplicate` 丢掉，不会刷成几百行。

顺带把 `task_status` 的 WS 载荷补上 `from` / `to` / `reason`：契约第 9 节要求
「任务页轨迹直接画 from/to，不要前端自己推」，之前只发了 `status`。

### 7.3 全站时间改成带 `T` 的 ISO

19 处 `isoformat(sep=" ", timespec="seconds")` → `isoformat(timespec="seconds")`，
REST 现在统一 `2026-11-14T11:17:01`（Safari 可解析）。有一条测试扫全部 `app/**/*.py` 兜底，
防止改一次忘一处。**WS 信封的 `ts` 与 `telemetry.ts` 仍是数字 epoch 秒**，两套量纲不要混。

### 7.4 `llm_api_key` 三态：`null` 清空 / `""` 不改 / 含 `*` 跳过

`_secret_write_guard` 升级成 `_secret_action`（`write` / `clear` / `skip`），
路由层原来「空串就 pop」的特判删掉，策略只留一处。`null` 落空串（不加密空串），
`GET /api/settings` 于是显示空输入框；清空时打一条 WARNING（「LLM 将走规则降级」），
否则「Key 什么时候没的」永远查不到。实测三态见下方验证记录。

### 7.5 已修问题不再列在这里

`workflow/wiring._emit` 取扁平载荷、事件名不在 `WS_TYPES` 白名单这两条已由队长 `9553948` 修掉
（`engine.WS_TYPE_OF` 单点翻译 + 守卫测试），原先记在 6.5 的整段已删——**已修的坑留在文档里
比不写更危险**，下一个人会照着旧结论排查。
