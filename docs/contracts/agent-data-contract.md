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

## 3. 任务状态(PRD 10.2,9 态)

任务在以下 9 种状态间流转,前端状态徽章与文案以此为准:

`pending → queued → running → waiting_tool → tool_done → completed / failed / canceled / degraded`

- `degraded` 是本平台特色:LLM 降级期间产生的任务结果,用第 5 节的降级标记区别于正常结果。

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

