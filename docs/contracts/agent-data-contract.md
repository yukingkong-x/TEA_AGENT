# agent-data-contract —— 给前端(A)的数据语义

> 读者:队友 A(前端)、B(后端数据源)、C(固件,只需第 5 章 cmd 语义,不读本文件)。
> 变更走契约流程:开 issue → 队长同意 → 改 PRD → contracts/README.md 流水账追加一行。
> 状态:2026-11-09 v1,其中「降级标记口径」待 11.9 站会 A/B 确认后转正。

---

## 1. Agent 标识(PRD 8.1)

7 个 Agent 的 `agent_key` 是跨端唯一键,WS 消息、API、数据库共用,**不许改名、不许换头像**:

| agent_key | 名称 | 头像 | 职责 |
| --------- | ---- | ---- | ---- |
| scout | 巡园管家 | 🌿 | 汇总环境/土壤数据出巡园播报 |
| weather | 气象员 | ⛅ | 天气预报与气象风险(霜冻/暴雨) |
| soil | 土壤师 | 🧪 | 土壤墒情分析 |
| pest | 植保员 | 🐛 | 病虫害核查与防治建议 |
| decision | 灌溉决策官 | ⚖️ | 唯一决策者:浇/不浇,单值输出 |
| executor | 执行管家 | 🔧 | 唯一有权下发设备指令的 Agent |
| verifier | 验证审计官 | 🛡️ | 达成率计算与三路置信度验证 |

## 2. Agent 输出格式(PRD 8.2)

每个 Agent 的输出以固定锚点开头,前端据此切分区块:

| agent_key | 输出锚点 |
| --------- | -------- |
| scout | 【巡园播报】 |
| weather | 【气象评估】 |
| soil | 【墒情报告】 |
| pest | 【植保核查】 |
| decision | 【决策】 |
| executor | 【执行反馈】 |
| verifier | 【验证报告】 |

## 3. 任务状态(PRD 10.2 + 11.3)

以 **PRD 10.2 与基座 `models/tasks.py` 的枚举**为准，共 9 态 + `needs_human`：

```
pending → dispatched → running → success
   ↑           ↓           ↓
   │           ▼           ▼
   └──── retrying ←── timeout / failed ──→ dead（重试耗尽）
                              │
                              └──→ needs_human（置信度 <60%，由验证器标记）
canceled：人工取消任何非终态任务
```

| 状态 | 徽章 | 说明 |
| ---- | ---- | ---- |
| `pending` | 排队（灰） | 已入库、等调度器打分派发 |
| `dispatched` | 已派发（蓝） | 已选中 Agent/设备，等 ack |
| `running` | 执行中（蓝闪） | 设备回执 running |
| `success` | 成功（绿） | 终态 |
| `failed` | 失败（红） | 进重试或终态 |
| `timeout` | 超时（红） | 超 `timeout_s` 未回执 |
| `retrying` | 重试（橙） | 退避中（2/4/8s）；设备离线时挂着不算失败 |
| `dead` | 熔断/耗尽（深红） | 重试用尽，或被熔断拒绝（`result.rejected=breaker_open`） |
| `needs_human` | 转人工（紫） | 置信度 <60%，等人工判 |
| `canceled` | 已取消（灰） | 人工取消 |

三条必须遵守：

- **没有 `queued`、`completed`、`waiting_tool`、`tool_done`** —— 这是早期草案的叫法，
  基座与 PRD 都不用；`queued` 就是 `pending`，`completed` 就是 `success`；
- **`degraded` 不是任务状态**，它是 Agent 节点/消息上的标记（见第 5 节），别混进状态机；
- `needs_human` 在 MySQL 枚举补齐前**可能以 `failed` + `result_json.verdict="needs_human"` 出现**，
  徽章判 `result_json.verdict` 兜住（见第 9 节）。

## 4. run 上下文(PRD 9.3)

工作流引擎产生的 run 记录含:task_id、agent_key、输入上下文、上游结论块、工具调用记录(tool_calls)、耗时与 token 用量。前端「过程回放」按 tool_calls 数组顺序渲染,每条记录结构:

```json
{"id": "call_xxx", "name": "get_weather", "arguments": {"city": "杭州"}, "status": "ok | denied", "result": "…"}
```

**权限拒绝展示(REQ-F-003 展示证据)**:某 Agent 调用非绑定工具时,记录为 `{"status": "denied", "reason": "permission"}`,前端在时间线上渲染「越权调用被拦截」标签——这条留痕本身就是权限分离的演示点。

## 5. LLM 降级标记口径(REQ-F-001 → 20.2)

- LLM 连续 2 次失败进入规则降级,所有 Agent 输出**第一行**固定为:

```
⚠️ 模型降级中
```

- 前端约定:**收到以该行开头的文本 → 顶部显示「模型降级中」徽章**;该行之后才是规则模板正文,正常渲染。
- 自动恢复:探针成功即退出降级,后续消息不再带前缀,徽章自动消失。
- 边界:若未来真实 LLM 输出恰好以该串开头,视为降级文本(接受此误判,换取实现简单)。

## 6. 报警来源 source(PRD 6.11)

`alerts.source` 的落库形态统一 **`agent:<agent_key>`**，前端直接展示，不要自己拼前缀、也不要从文案里猜：

| source 取值 | 含义 | 前端展示 |
| ----------- | ---- | -------- |
| `agent:scout` … `agent:verifier` | 7 个 Agent 主动上报 | 取第 1 节的「头像 + 名称」，如 🛡️ 验证审计官 |
| `agent` | 历史数据 / 运行时取不到身份的兜底 | 显示「平台」，不要出现 `agent` 字样 |
| `system` | 平台自身（设备离线、指令超时、接缝降级） | 显示「系统」 |

- `source` 是 `raise_alert` tool schema 的**可选**字段，LLM 可以不传：缺省由运行时按当前 Agent 自动填充（`agents/context.py` 的 ContextVar）。
- 缺 `agent:` 前缀的取值一律按「平台」兜底渲染，不报错、不空白。

## 7. 画布执行事件(REQ-F-013)

工作流引擎每推进一个节点推一条事件（WS），前端据此类点亮画布。

**只有两类 WS 消息**，与基座 `core/ws_manager.WS_TYPES`（PRD 7.4 白名单）一致。
用「类型 + 阶段字段」两元组区分开始与结束，一个 handler 就能处理：

| type | 阶段字段 | 时机 | 字段 |
| ---- | -------- | ---- | ---- |
| `run_status` | `status="running"` | 一轮执行开始 | `run_id` `wf_key` `trigger` `node_count` `status` |
| `node_state` | `state="started"` | 节点开始 | `run_id` `node_id` `node_type` `name` `agent_key` |
| `node_state` | `state="finished"` | 节点结束 | `run_id` `node_id` `node_type` `name` `agent_key` `status` `output` `error` `degraded` `duration_ms` `tool_calls` `tokens_in` `tokens_out` |
| `run_status` | `status="success"` \| `"failed"` | 一轮执行结束 | `run_id` `status` `rounds` `duration_ms` `error` |

真实样本（跑一次默认工作流，14 节点共 28 条事件，`data` 里**不会有空对象**）：

```json
{"type": "run_status", "data": {"run_id": 1, "wf_key": "patrol_irrigation", "trigger": "manual",
  "node_count": 14, "status": "running"}, "ts": 1794624925}
{"type": "node_state", "data": {"run_id": 1, "node_id": "n2", "node_type": "agent", "name": "巡园播报",
  "agent_key": "scout", "status": "done", "output": "【巡园播报】A区平均湿度 33%…", "error": "",
  "degraded": false, "duration_ms": 812, "tool_calls": [], "tokens_in": 0, "tokens_out": 0,
  "state": "finished"}, "ts": 1794624925}
{"type": "run_status", "data": {"run_id": 1, "status": "success", "rounds": 1,
  "duration_ms": 7314, "error": ""}, "ts": 1794624932}
```

约定：

- **`state` 与 `status` 不是一回事**：`state` 只出现在 `node_state` 上（`started`/`finished`），
  `status` 只表达结果（节点 `running`/`done`/`failed`/`skipped`，run `running`/`success`/`failed`）。
  按 `state` 点亮/熄灭节点，按 `status` 决定红绿；
- **没走到的分支节点不会有任何事件**（如决策为 none 时 `n9/n10/n11` 全程静默），前端保持默认态，不要自己补动画；
- **Self-Loop 会让同一个 `node_id` 出现多次** `state=started`/`finished`（验证官每轮都跑）。画布按到达顺序播，**不要按 `node_id` 去重**，轮次用 `run_status` 结束事件的 `rounds` 或事件出现次数区分；
- `degraded=true` 的 agent 节点按第 5 节显示降级徽章；
- `tool_calls` 与 `tokens_*` 是对话剧场折叠块的原料，画布不需要；
- 顺序保证：`run_status` 的 `running` 一定第一个、`success`/`failed` 一定最后一个，每个 `state=started` 都有配对的 `state=finished`（含 end 节点）——据此可以让「卡在进行中」的节点永远有归宿；
- **事件是扁平字段 + 基座信封**：引擎产出的字段与 `type` 同级，WS 上看到的才是 `{type, data, ts}` 三层。不要在前端再去 `data.data`。

> 历史坑（已修，记下来防复发）：引擎原本发 `node_started`/`node_finished`/`run_started`/`run_finished`，
> 不在 `WS_TYPES` 白名单里，每条事件都会打一条「未知 WS 消息类型」告警，且给 A 的文档写的是
> `node_state`/`run_status`，两边对不上、前端匹配不上。现在统一以基座白名单为准，
> `engine.WS_TYPE_OF` 单点翻译，并有测试 `test_event_names_match_base_ws_whitelist` 钉住。


## 8. 知识库检索结果与引用(REQ-F-020)

`POST /api/knowledge/search` 与植保员工具 `query_knowledge` 返回同一种结构：

```json
{"title": "茶小绿叶蝉防治.md", "chunk_text": "……", "score": 0.2306, "doc_id": 2, "chunk_index": 0}
```

| 字段 | 说明 |
| ---- | ---- |
| `title` | 文档名（取自上传文件名），**引用块标题直接用这个**，不要加路径 |
| `chunk_text` | 命中的原文片段，渲染时原样显示，不要截断成一行 |
| `score` | 稀疏余弦相似度，`0~1`，越大越相关。实测同主题 0.07~0.25、无关 0.00~0.02 |
| `doc_id` | 对应 `knowledge_docs.id`，点引用要能跳到文档 |
| `chunk_index` | 块序号，从 0 开始；同一文档可能命中多块，**不要按 doc_id 去重** |

约定：

- **空数组 = 未检索到，这是正常结果**，不是错误。前端显示「知识库中未检索到相关内容」的空态；植保员也必须照此回答，禁止编造；
- 后端有 0.03 的噪声地板：低于此分的命中已被过滤，所以前端**不要**再显示"相关度 2%"这种条目；
- 引用编号 `[1][2]` 由**前端按返回顺序**生成（1 开始，不跳号），hover 显示 `chunk_text` 原文摘要；
- 分数不要归一化成百分比再显示两位小数——`0.23` 就是 `0.23`，转了反而暴露精度噪声。

**存储后端可观测**：`ingest` 返回体里的 `backend` 取值为 `chroma+local`（Chroma 容器可用，双写）或 `local`（Chroma 不可达，仅本地索引）。两种都能检索，功能一致；设置页若要显示"向量库：Chroma / 本地"，用这个字段，不要按容器是否存在猜。


## 9. 任务调度事件 task_status(REQ-F-014)

调度器每次改任务状态推一条 WS 消息（`manager.publish_threadsafe("task_status", data)`）：

```json
{"type": "task_status",
 "data": {"task_no": "task-20261114-0007", "run_id": 12,
          "from": "pending", "to": "dispatched", "reason": "dispatch",
          "retry_count": 0, "score": 0.71,
          "assigned_agent": "executor", "assigned_device": "k10-act-03"},
 "ts": "2026-11-14T10:31:02"}
```

| 字段 | 说明 |
| ---- | ---- |
| `from` / `to` | 状态机的边。**任务页轨迹直接画这两个值**，不要自己推 |
| `reason` | 机器可读的原因，见下表；前端不要按 reason 分支渲染，只用于排查 |
| `retry_count` | 已在退避中的重试次数（0 表示首次执行） |
| `score` | 派发时才有：PRD 10.3 的打分（2 位小数） |
| `result.rejected` | 熔断拒绝时才有：`breaker_open`，附带 `retry_after_s` |

`reason` 全集：`dispatch` / `timeout_{n}s` / `retry_armed` / `retry_due` / `retry_hold_offline`
/ `retries_exhausted` / `breaker_open` / `rejected_breaker_open`。

约定：

- **`needs_human` 暂不在 MySQL 枚举里**（基座 `tasks.status` 只有 9 态）。验证器判出转人工时，
  当前落 `failed` + `result_json.verdict="needs_human"`；等基座补枚举后改为直写 `needs_human`。
  前端「转人工」紫色徽章**先按 `result_json.verdict` 判**，别等枚举；
- 熔断拒绝落 `dead`（不是 `rejected`），显示「熔断拒绝 · 剩余 Ns」用 `result.retry_after_s`；
- `retry_hold_offline` 的事件里 `from == to == "retrying"`，这是「挂着等设备」，不是 bug，
  前端不要重复播一条"重试"动画。
## 10. 验证结果与证据链(REQ-F-016/017/018)

`POST /api/verify/{task_no}`（工具 `verify_result` 同源）：

```json
{"task_no": "task-20261114-0007", "verification_id": 31, "verdict": "failed",
 "achievement": 39.39, "gap": 15.61, "over_irrigated": false,
 "confidence": 72.5, "measured": 45.0, "baseline": 38.5, "round_no": 1,
 "confidence_detail": {"data_quality": 1.0, "rule_cross": 1.0, "consistency": 0.5,
                       "reasons": ["复测读数偏低 12.3%，与近 24h 均值偏差 2.4σ"]},
 "correction": {"strategy": "topup", "duration_s": 25.61, "times": 1, "interval_s": 0},
 "note": "…"}
```

量纲约定（之前工程里 0-1 与 0-100 混用过，这里钉死）：

| 字段 | 量纲 | 说明 |
| ---- | ---- | ---- |
| `achievement` / `gap` | 0-100（%） | 达成率与缺口，PRD 11.1 的百分数 |
| `confidence` | **0-100** | PRD 11.3 的 60% 阈值即 60.0；DB `verifications.confidence` 同量纲 |
| `confidence_detail.*` | 0-1 | 三路原始分（0.5/0.3/0.2 权重加权后 ×100 才是上面那项） |
| `correction.duration_s` | 秒 | 修正动作时长；`times=0` 表示无需作业 |

约定：

- `verdict` 三值：`success` / `failed` / `needs_human`。**`needs_human` 的判定优先于达成率**
  （浇水后读数大跌时先怀疑数据，而不是继续补水）；
- `reasons` 是给人看的解释，报告页与任务详情直接列，不要改写成别的措辞；
- `correction` 为 `null` 表示本轮无需修正（已成功 / 已转人工 / 轮次用尽）。


## 11. 任务轨迹 task_events(REQ-F-015)

PRD 986 行要求「点击行展开轨迹抽屉（pending→dispatched→running→…**每次状态变更时间戳**）」。
`tasks` 表只有 `created_at`/`updated_at`，中间态推不出来；`task_status` 的 WS 推送又只在
内存里，刷新即失。所以每次状态变更落一行 `task_events`。

**接口** `GET /api/tasks/{task_no}/events?limit=100`（B 实现）：

```json
{"items": [
  {"id": 31, "event": "task_status", "from": "pending", "to": "dispatched",
   "reason": "dispatch", "actor": "scheduler", "at": "2026-11-14T10:31:02", "payload": {"score": 0.71}},
  {"id": 34, "event": "task_status", "from": "dispatched", "to": "running",
   "reason": "ack", "actor": "device", "at": "2026-11-14T10:31:03", "payload": null}
 ], "total": 6}
```

| 字段 | 说明 |
| ---- | ---- |
| `from` / `to` | 状态机的边，**直接画**，不要自己推下一跳 |
| `reason` | 机器可读原因（全集见第 9 节）；只用于排查，不要按它分支渲染 |
| `actor` | 谁触发的：`scheduler` / `device` / `verifier` / `human` |
| `at` | **`isoformat()` 带 `T`**，不要用 `isoformat(sep=" ")`——Safari 会把带空格的串解析成 `Invalid Date` |
| `payload` | 原始事件载荷，`_truncated=true` 时只剩状态字段（长文本在 `agent_messages` 里） |

约定：

- 按 `at` **升序**画时间轴（接口已按 id 升序返回，直接用）；
- **不要按 `from`/`to` 相同的相邻行去重**——后端已经去过重了（`retry_hold_offline`
  每 tick 发一条，设备离线 5 分钟就是 300 行）。前端看到重复就是后端 bug，报给 B；
- 状态徽章配色用第 3 节那张表，与任务列表保持一致；
- 轨迹最后一行不一定是终态（任务还在跑），不要用最后一行反推任务当前状态，**要读 `task.status`**。

> 落库侧：`orchestrator/events.py` 拼装 + `orchestrator/wiring._emit` 写入，
> 表未建时静默跳过（加分项缺表不能让调度停摆）。
