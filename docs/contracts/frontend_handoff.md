# 给队友 A 的前后端对接清单

> 2026-11-14 · 后端 `feature/backend-base`（`9891eac`）实测口径 · 写给前端 `feature/frontend-dashboard`
>
> 下面每条结论都来自后端代码/实测，不是推测。带「复现」的可以直接验。

## 0. 先说结论：不是后端缺接口

后端 34 条 `/api` 路由 + 1 条 WS 全部就绪，字段、枚举、分页格式已冻结。

前端目前（`origin/feature/frontend-dashboard` @ `1932c71`）：**只有一条 WS 连接，REST 一条都没接**，
`src/data/*.ts` 仍是写死快照。所以「接不上」不是缺接口，是缺一层 **API client + 类型映射**。

另外你已经接上的那条 WS 有 4 个问题（见 1.1），**现在实际上一条消息都收不到**——
不是后端没发，是前端没处理。建议先修它，后面所有实时效果都挂在这条线上。

---

## 1. 三条必须先修的（会直接崩 / 功能静默失效）

### 1.1 WS 接了但没通：`VITE_WS_URL` 无兜底、无 `onmessage`、无心跳

`src/shell/ShellContext.tsx` 现状：

```ts
const url = import.meta.env.VITE_WS_URL
if (!url) return                        // ← ① 仓库里没有 .env，这里直接 return
socket = new WebSocket(url)
socket.onopen = () => setLink('open')
socket.onclose = ...                    // ← ② 全程没有 onmessage
                                        // ← ③ 没有 20s ping
```

三个后果，逐个说：

**① 没配环境变量就静默不连。** 仓库里没有 `.env` / `.env.example`（我查过
`origin/feature/frontend-dashboard`），所以任何人 clone 下来 `link` 永远是 `closed`，
控制台一句话都没有——最难查的那种。改成带兜底：

```ts
const url =
  import.meta.env.VITE_WS_URL ??
  `ws://${location.hostname}:8000/ws/dashboard`
```

（后端 WS 路径是 `/ws/dashboard`，**不带 `/api` 前缀**；dev 环境不需要 token，
`ENFORCE_AUTH=true` 时走 `?token=xxx`。）

**② 没有 `onmessage`，等于白连。** 后端连上就推首帧 `mode_changed{hello:true}`，
之后遥测/任务/报警全走这条线。加上：

```ts
socket.onmessage = (ev) => {
  const msg = JSON.parse(ev.data) as { type: string; data: any; ts: number }
  listeners.forEach((fn) => fn(msg))    // 用一个 ref 数组把订阅分发出去
}
```

**③ 不发心跳。** 后端 `while True: await ws.receive_text()` 只在等你的消息，
不发也能连（TCP 不会自己断），但掉线检测要 30~60s 才发现，NAT/代理可能提前掐。
每 20s 发一次：

```ts
const ping = window.setInterval(() => socket?.readyState === 1 && socket.send('{"type":"ping"}'), 20_000)
```

**④ `mode` 是本地假状态。** 现在 `useState<RunMode>('mock')` 硬编码，后端实际
可能是 `real`，顶部状态条会一直显示错。应该取首帧里的值：

```ts
if (msg.type === 'mode_changed') setMode(msg.data.mode)   // data.mode 是 'mock' | 'real'
```

### 1.2 `src/lib/useCountUp.ts` 被 `.gitignore` 吞了 —— 任何人 clone 后构建必失败

```
$ git check-ignore -v frontend/src/lib/useCountUp.ts
.gitignore:17:lib/    frontend/src/lib/useCountUp.ts
$ git ls-files frontend/src/lib          # 空：从未被跟踪
$ git ls-tree -r --name-only origin/feature/frontend-dashboard -- frontend/src/lib
                                          # 空：远端没有这个文件
```

但 `src/components/MetricTile.tsx:2` 是 `import { useCountUp } from '../lib/useCountUp'`。

**后果**：你本机能跑（文件在本地），一 push 别人 clone 下来 `npm run build` 直接
`Cannot find module '../lib/useCountUp'`。CI/评测机也过不去。**你已经推了 2 个提交，
这两个提交在干净环境里都是编译不过的。**

**修法**（两处都要）：

```gitignore
# .gitignore 第 17 行的 lib/ 是 Python venv 的规则，误伤了 src/lib。
# 改成根锚定（只忽略仓库根的 lib/），或加一条否定：
!/frontend/src/lib/
```

```bash
git add -f frontend/src/lib/useCountUp.ts
```

改完用 `git ls-files frontend/src/lib` 确认有输出。

### 1.3 时间字符串在 Safari / iPad 上是 `Invalid Date`

后端所有时间字段格式统一为 `"2026-11-14 09:30:00"`（**空格分隔**，由
`isoformat(sep=" ")` 生成）。这是 MySQL 原生格式，Chrome 容忍，但 **Safari 的
`new Date("2026-11-14 09:30:00")` 直接返回 `Invalid Date`**。

**这个坑现在被 mock 数据掩盖了**：你 `src/data/tasks.ts` 里写的是
`'2026-11-11T08:14:22+08:00'`（带 `T`，Safari 能解析），但 `formatClock(iso)` 和
`TasksPage.tsx` 的 `inRange(iso)` 都是裸 `new Date(iso)`——**换成后端真实格式的那一刻就全部炸**。

涉及字段：`sensor/latest.ts`、`sensor/history.points[].ts`、`tasks[].created_at /
updated_at / deadline_at`、`alerts[].created_at`、`runs[].started_at / finished_at`、
`agents[].updated_at`。

演示如果投 iPad 或 Safari，大屏时间栏全是 `Invalid Date`。**前端加一层解析**就行：

```ts
// src/lib/time.ts
/** 后端统一 "YYYY-MM-DD HH:mm:ss"；Safari 不认空格分隔，必须换成 T。 */
export function parseTs(s: string | null | undefined): Date | null {
  if (!s) return null
  return new Date(s.includes('T') ? s : s.replace(' ', 'T'))
}
```

`formatClock` / `inRange` 里的裸 `new Date(iso)` 全部换成 `parseTs(iso)`。
**不要用 `dayjs(s)` 直接吃原串**——它内部也是 `new Date`，Safari 一样挂。

> 为什么不让后端改成 ISO+T：这是全站 19 处序列化 + 已冻结的契约，改动会同时波及你已写的
> 代码和队长的联调基线。演示前一周改契约风险大于前端加一个 3 行函数。等提交后可以统一。

---

## 2. 四处类型对不上（不崩，但会显示错/空白）

### 2.1 设备：前端 `Device` 与后端 `state_dict` 字段完全不同

前端（`src/data/snapshot.ts`）：
`{ id, name, role: '环境'|'土壤'|'浇水', status, place, reading, detail[], series[], x, y }`

后端 `GET /api/devices` 每项：
```json
{ "device_id": "k10-field-01", "name": "巡园员一号", "role": "field",
  "location": "A区茶垄", "is_mock": false, "online": true,
  "last_seen": "2026-11-14 09:30:00", "state": "online" }
```

差异点，逐条：

| 前端 | 后端 | 说明 |
|---|---|---|
| `id` | `device_id` | 改名 |
| `role: '环境'/'土壤'/'浇水'` | `role: field / soil / actuator` | **中文映射到英文枚举**，要做词典 |
| `status` | `state` | 值域 `online / suspect / offline`（**没有 `alarm`**） |
| `place` | `location` | 改名 |
| `reading` | — | 后端不拼这个串，自己从 `metrics` 取 |
| `detail[]` | — | 后端不给，自己从 `GET /api/sensor/latest` 的 `metrics` 拼 |
| `series[]` | — | 走 `GET /api/sensor/history` |
| `x / y` | — | 布局坐标只在前端，后端不存（`dag_json.edges` 才存画布坐标） |

`reading` / `detail` / `series` 都改由接口现取，别再写死。`status: 'alarm'` 这个值后端
永远不返回，用 `alerts` 里的 `critical` 自己叠加。

**还有一个 Mock 演示必踩的坑：设备 id 带前缀。**

| 环境 | 三台设备 id |
|---|---|
| 真机（seed，PRD 4.1） | `k10-field-01` / `esp32-soil-02` / `k10-act-03` |
| Mock（模拟器） | `mock-k10-field-01` / `mock-esp32-soil-02` / `mock-k10-act-03` |

你现在 `src/data/snapshot.ts` 里写的是**真机 id**。演示大概率跑 Mock，那时候按
`k10-field-01` 去 `find()` 会返回 `undefined`，页面直接白。

**不要靠 id 前缀猜**，用 `role` 定位（`field` / `soil` / `actuator` 各一台），
id 只用来做 key：

```ts
const byRole = (list: DeviceDto[], role: string) => list.find((d) => d.role === role)
```

如果确实要区分真机与 mock，用 `is_mock` 字段，别解析 id 字符串。

### 2.2 任务类型枚举

前端 `TaskRow.type`：`'device_cmd' | 'alert' | 'verify'`
后端 `Task.type`：`agent_call | device_cmd | verify | report | selfloop`

- `alert` **后端永远不产生**（报警不是任务），删掉这个分支
- 缺 `agent_call` / `report` / `selfloop` 三个，要补，否则这几类任务在任务中心渲染成空白行

### 2.3 任务状态枚举

前端 `TaskStatus` 有 `needs_human`，后端 `TASK_STATUS` 9 个值里**没有**它：
`pending / dispatched / running / success / failed / timeout / retrying / dead / canceled`

`needs_human` 那条分支是死的（PRD 里没有这个状态流转）。其余 9 个都对得上。

### 2.4 任务轨迹 `trace` 没有后端数据源

前端 `TaskRow.trace: {status, at}[]`。后端**没有 `task_events` 表**（14 张表里没有），
任务只存当前 `status`，不存状态变迁历史。

两个选择，建议第 1 个：

1. **前端本地累积**：订阅 WS `task_status`，把同一个 `task_no` 的事件攒进内存 Map。
   刷新后只剩当前状态——演示时别刷新就行。
2. 我加一张 `task_events` 表（约半天，要在 11.15 提交线之前挤进去，且会改 14 张表的
   既定契约）。除非评委明确要求"轨迹可回溯"，否则不值得。

---

## 3. 画布：必须写一个双向转换器（这是最容易卡住的地方）

前端用 React Flow：`{ id, type, position: {x, y}, data: { name, kind, agentKey, ... } }`
后端 `dag_json`：**没有坐标，用显式 next 连边**。以下是 PRD 9.1 默认工作流的真实结构
（`tests/fixtures/prd_default_dag.json`，可直接当样例）：

```json
{
  "wf_key": "patrol_irrigation",
  "name": "巡园浇水工作流",
  "nodes": [
    { "id": "n1", "type": "start", "name": "开始", "next": ["n2"] },
    { "id": "n2", "type": "agent", "agent_key": "scout", "name": "巡园播报",
      "input": "开始本轮巡园，目标区域：A区茶垄。", "next": ["n3"] },

    { "id": "n3", "type": "parallel", "name": "三方会诊",
      "branches": ["n4", "n5", "n6"], "next": ["n7"] },          // ← parallel: 数组

    { "id": "n8", "type": "condition", "name": "决策分流",
      "expression": "context.last_decision == 'irrigate'",
      "branches": { "true": ["n9"], "false": ["n12"] } },        // ← condition: 字典

    { "id": "n10", "type": "tool", "tool": "wait_penetration",
      "params": { "seconds": 90 }, "name": "渗透等待", "next": ["n11"] },

    { "id": "n11b", "type": "loop", "name": "Self-Loop",
      "max_iterations": 2,
      "exit_expression": "context.last_verification == 'success' or context.round > 2",
      "body_next": "n11", "next": ["n13"] },                     // ← body_next 不是 next

    { "id": "n13", "type": "end", "name": "结束" }
  ],
  "edges": []
}
```

字段对照：

| React Flow | dag_json | 注意 |
|---|---|---|
| `node.id` | `node.id` | 全局唯一 |
| `node.data.kind` / `node.type` | `node.type` | 只认 7 个：`start/agent/tool/condition/parallel/loop/end` |
| `node.data.name` | `node.name` | |
| `node.data.agentKey` | `node.agent_key` | **蛇形！最容易错的一处** |
| `node.data.input` | `node.input` | agent 节点的提示词 |
| `node.data.expression` | `node.expression` | condition 的判定表达式 |
| `node.data.maxIterations` | `node.max_iterations` | loop 节点 |
| （loop 退出条件） | `exit_expression` | loop 节点，别和 `expression` 混 |
| `node.data.tool` | `node.tool` + `node.params` | tool 节点的工具名与参数 |
| 单出口连线 | `next: ["nX"]` | **统一写成数组**（校验器也接受裸字符串） |
| parallel 的分支 | `branches: ["n4","n5","n6"]` | **数组** |
| condition 的分支 | `branches: { "true": [...], "false": [...] }` | **字典**，两种别写反 |
| loop 的 body 连线 | `body_next: "n11"` | **不是 next**；next 是 loop 的出环边 |
| `node.position` | —— | 后端不收。存 `dag_json.edges`（队长改完是 `[]`）或你本地 `zhiqiu.canvas.layout` |

> `parallel` 的 `branches` 是数组，`condition` 的是字典——这两种节点在画布上长得像，
> 但序列化结构完全不同。校验器对两种都做了兼容（`_children()` 里分别处理 list 和 dict），
> 但**引擎执行时按 PRD 语义读**，写反了就是并行变单路。

**保存前必须过校验**：`PUT /api/workflows/{id}` 会跑 DAG 校验，不通过返回 400：

```json
{ "detail": { "message": "dag_json 校验失败", "errors": ["以下节点从 start 不可达：['n11b']"] } }
```

拦住的情况：环、多个 start/end、`agent_key` 不在 agents 表、引用不存在的节点、
`type` 非法。**画布上拖出一个回边就会 400**，请把 `detail.errors` 直接渲染到画布顶部，
不然用户只看到"保存失败"。

### 关于 `n11b`（loop 节点）

PRD 9.1 的默认工作流里 `n11b` 没有任何入边，队长已确认会改成
`n9 → n10 → n11 → n11b → n13`（loop 显式接进主链）。两种形态后端校验器**都能过**
（loop 按"环绕 body 的结构标记"处理），所以你照旧画就行，不用为它特判。

另外 PRD 9.1 那段 JSON 有个尾逗号（`"edges": [ "...", ]`），标准解析器会挂——
队长在改，你**不要照 PRD 抄**，用 `GET /api/workflows/{id}` 拿到的实际数据为准。

---

## 4. 契约速查（照抄，别猜）

Base URL：`http://localhost:8000`（**不需要 vite proxy**，后端 CORS 已放行
`localhost:5173` / `127.0.0.1:5173` / `localhost:4173`）。

| 接口 | 返回 |
|---|---|
| `GET /api/sensor/latest` | `[{ device_id, name, role, is_mock, online, metrics: {temperature_c, humidity_air, lux, soil_moisture}, ts }]` |
| `GET /api/sensor/history?device_id=&metric=&from=&to=&limit=` | `{ device_id, metric, from, to, count, points: [{ts, value}] }`（**已按时间升序**，直接画） |
| `GET /api/devices?is_mock=` | `[state_dict]`（见 2.1）。**缺省返回全量 6 台**；`true`/`false` 才过滤，`all` 等同缺省 |
| `GET /api/alerts?level=&acknowledged=&page=&page_size=` | 分页，item = `{id, level, source, message, acknowledged, created_at}` |
| `POST /api/alerts/{id}/ack` | 认领一条报警，返回同结构 |
| `GET /api/tasks?status=&type=&run_id=&assigned_device=&page=` | 分页，item = `{id, task_no, run_id, type, payload, priority, score, status, assigned_agent, assigned_device, retry_count, timeout_s, deadline_at, result, created_at, updated_at}` |
| `GET /api/workflows` / `GET /api/workflows/{id}` | `{ id, wf_key, name, version, enabled, dag_json, updated_at }` |
| `GET /api/agents` | `[{ id, agent_key, name, avatar, system_prompt, tools_json[], model, temperature, enabled, updated_at }]` |
| `GET /api/settings` | `{ mode, llm_ready, items: [{ key, value, description }] }`——**`items` 是数组不是对象** |
| `GET /api/health` | `{ status, db, redis, mqtt, mode, simulator, ws_clients, llm_ready, seams: {...}, version, ts }` |

分页统一 `{ items, total, page, page_size, pages }`。

### 两个坑

**`GET /api/settings` 的敏感值是掩码**（`sk-a****wxyz`）。PUT 时**不要把整张表单原样回传**：
后端虽然加了硬闸（含 `*` 或 `enc:` 开头的值会被跳过并 warning），但那是兜底，不是让你依赖它。
正确做法——只提交用户真正改过的字段：

```ts
const dirty = Object.fromEntries(
  Object.entries(form).filter(([k, v]) => v !== original[k] && !String(v).includes('*'))
)
if (Object.keys(dirty).length) await api.put('/settings', { values: dirty })
```

**`GET /api/health` 的 `ts` 是带 `T` 的 ISO 格式**，而其他接口是空格分隔——两处不一致，
用 1.2 的 `parseTs()` 兼容两种情况（函数里已经判了 `includes('T')`）。

---

## 5. WS：写了 8 种事件，目前只有 5 种真的会来

连接：`ws://localhost:8000/ws/dashboard`，连上后**立刻推一帧**
`{"type":"mode_changed","data":{"hello":true,...}}`，用它点亮顶部状态条。
客户端每 20s 发 `{"type":"ping"}` 保活。

统一信封：`{ "type": "...", "data": {...}, "ts": 1730700000 }`

| type | 现在会来吗 | data |
|---|---|---|
| `telemetry` | ✅ | `{ device_id, metrics: {...}, rssi, ts, seq }` —— `ts` 是**数字 epoch 秒**，不是字符串 |
| `device_status` | ✅ | 同 `state_dict`（见 2.1） |
| `task_status` | ✅ | `{ task_no, status, type: "device_cmd", assigned_device, action? }` |
| `alert` | ✅ | `{ id, level, source, message }` —— **注意没有 `created_at`**，前端自己打时间戳 |
| `mode_changed` | ✅ | 首帧 `{ mode, clients, hello: true }`；后续切换 `{ mode, previous }` |
| `pong` | ✅ | 你发 ping 的回包 `{ clients: N }`（协议回包，不计入上述 8 种业务事件） |
| `node_state` | ❌ 等队长 | 画布节点高亮用，调度器落地后才有 |
| `agent_message` | ❌ 等队长 | 对话剧场用，Runner 落地后才有 |
| `run_status` | ❌ 等队长 | 执行进度用，同上 |

**这三种现在一条都不会来，别以为自己接错了。** 先把另外 5 种接通、页面能跑，
等队长 runner 落地后这三个才有数据；届时我会在群里说一声。

> **2026-11-14 晚更新：画布的三种事件"半通"，别急着接。**
> 队长引擎已经会发 `node_started` / `node_finished` / `run_started` / `run_finished`，
> 但（a）名字和上面这张表不一致，（b）载荷恒为空 `{}`（引擎发扁平结构，接线层按
> `{type,data}` 取）。实测跑完一次工作流，`agent_messages` 表 0 行。
> 已报给队长修；**修好之前画布高亮仍按本地模拟做**，接上去只会拿到空对象。
> 详见 `docs/contracts/api_seams.md` 第 6.5 节。

画布节点高亮建议先做**本地模拟**（点"运行"后按 1.2s 一个节点自己走），否则演示时
画布是静的，观感很差。

---

## 6. 503 不是坏了，是"对面还没写完"

`POST /api/workflows/{id}/run`、`POST /api/verify/{task_no}`、`POST /api/reports/generate`、
`/api/knowledge/*` 这四类接口依赖队长的 `workflow/ verification/ knowledge/`。他没落地前返回：

```json
HTTP 503
{ "detail": "触发工作流尚未就绪（队长地盘）：...｜约定 start_run(wf_id, trigger) -> {run_id}｜...",
  "seam": "start_run", "code": "SEAM_NOT_READY" }
```

**前端请按 `code === 'SEAM_NOT_READY'` 显示「该模块开发中」，不要弹通用报错、更不要白屏。**
其余接口（传感器、设备、任务、报警、设置、agents）全部可用，不受影响。

想在设置页显示"哪块没接上"，直接读 `GET /api/health` 的 `seams`，值是
`ready` 或 `not_ready`（6 个 key：`start_run / validate_dag / verify_task /
generate_report / ingest / search`）。

---

## 7. 建议的落地顺序（半天量级）

1. `src/api/client.ts`：`ApiError` 带 `status`/`code`/`detail`，统一处理 503 与分页
2. `src/lib/time.ts`：`parseTs()`（1.2）
3. `src/api/types.ts`：照第 3、4 节的字段写 TS 类型（别用 `any`，字段名错了编译期就能发现）
4. 大屏：`sensor/latest` + `devices` + `alerts` + WS 5 种 → 最快出效果
5. 任务中心：`tasks` 分页 + `task_status` 本地累积 trace
6. 画布：双向转换器 + 400 错误渲染（第 3 节）
7. 设置页：`settings` 的 dirty 提交 + `agents` 列表 + `health.seams` 状态条

卡在字段上直接找我，我这边能立刻给出某一个接口的真实响应。
