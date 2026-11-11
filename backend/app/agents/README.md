# 智能体模块 · 开工手册（队长）

> 一句话：平台的"智能"全在这里——7 个 Agent 协作、DAG 工作流编排、动态调度、Self-Loop 验证闭环。**这是赛题评分的核心。**
> 你的规格书：PRD 第 7.2/7.3（LLM 层与工具池）、第 8 章（7 个 Agent）、第 9 章（工作流引擎）、第 10 章（调度器）、第 11 章（验证引擎）、第 20.2（降级模板）。冲突以 PRD 为准。
> 团队规矩：先读仓库根目录的 `TEAM.md`。

---

## 你管什么 / 不管什么

- **管**：`backend/app/` 里的 `agents/`、`workflow/`、`orchestrator/`、`verification/`、`knowledge/`，以及 `core/llm.py`
- **不管**：`api/`、`models/`、`devices/`、`mock/`（队友 B 的地盘）；要新表 / 新接口 → 开 issue 找 B；`devices/command.py` 是唯一的指令下发通道，你只调用、不修改
- **不管**：`frontend/`、`firmware/`
- **额外职责**：全队 PR 的 review 人；契约（PRD 第 5、7 章）的守门人；进度与材料的统筹

## 技术栈与环境准备

| 要装                 | 说明                                                               |
| -------------------- | ------------------------------------------------------------------ |
| Python 3.11 + venv   | 本地跑智能体线                                                     |
| GLM API Key          | 智谱 bigmodel.cn，学生认证，GLM-4-Flash 免费档够开发用（PRD 19.2） |
| DeepSeek Key（备用） | 充 ¥10 即可；主模型连续失败自动切换                               |

LLM 接入统一走 openai SDK 兼容模式：超时 60s、失败切备用、连续 2 次失败触发**规则降级**并在界面显示"⚠️ 模型降级中"徽章（PRD 7.2 + 20.2）。

## 你的任务（对照 PRD 17.2 排期表"队长"一列）

| 日期     | 任务                                                              | 对应 REQ                             |
| -------- | ----------------------------------------------------------------- | ------------------------------------ |
| 11.9-10  | LLM 接入层 + 工具池 10 个函数 + 7 个 Agent 提示词入库             | REQ-F-001 / 002 / 003                |
| 11.11-12 | DAG 工作流引擎 + 调度器（打分 / 并行 / 重试 / 熔断）              | REQ-F-004 + REQ-F-014                |
| 11.13    | 验证引擎（达成率 / 三路置信度 / 反馈修正）+ 知识库 RAG + 报告后端 | REQ-F-016 / 017 / 018 / 020 / 022 半 |
| 11.14    | 全链路联调 + 方案书定稿 + 材料终审                                | 15.1 主剧本跑通                      |

**权限铁律（REQ-F-003）**：`send_device_cmd` 只能出现在 executor 的工具表里——其他 Agent 调用直接拒绝并留痕，这个"被拒绝的记录"本身就是权限分离的展示证据（PRD 7.3）。

**默认工作流与 7 段提示词**：PRD 8.2 已写好全文，首启写入 agents 表（REQ-F-002：设置页改提示词 → 下一轮生效，不用改代码）。

## 对接关系

- **从 B 拿**：`models/` 数据表、`devices/command.py` 下发通道；他没建好的表，开 issue 催
- **给 A**：六页要的一切数据语义——agent_key 与头像（8.1）、任务 9 种状态（10.2）、run 上下文（9.3）、达成率字段（11.1）
- **给 C**：`cmd` 指令语义（5.3：pump / relay_off / read_now / calibrate_dry / calibrate_wet）
- 工具池通过 **MCP Server（SSE `/mcp`）** 对外暴露——赛题关键词，加分项，别忘了

## D7 已完成（11.9，F-001/002/003 落地）

- `core/llm.py`：主备切换 / 60s 超时 / 连续 2 次失败规则降级 / 探针自动恢复
- `agents/prompts.py`：PRD 8.2 的 7 段提示词逐字入库（`to_db_rows()` 首启写 agents 表）
- `agents/base.py`：AgentRunner（消息构造 → LLM → 工具循环 → 权限拦截留痕）
- `agents/tools.py`：11 个工具 + 权限白名单 + 达成率公式（PRD 11.1）
- `agents/mcp_server.py`：MCP Server（SSE `/mcp`，JSON-RPC 2024-11-05）
- `agents/fallback.py`：PRD 20.2 降级模板；`runner_{key}.py` × 7：薄工厂
- 64 个测试全绿（`tests/` 下 7 个文件）

## 本地跑测试

```powershell
# 在仓库根目录执行；venv 在 backend/.venv
$env:PYTHONPATH = "$PWD\backend"
& backend\.venv\Scripts\python.exe -m pytest "$PWD\backend\app\agents\tests" -v -o asyncio_default_fixture_loop_scope=function
```

（`-o` 参数是 pytest-asyncio 警告的临时解法，等 B 建好 `backend/pytest.ini` 后去掉。）

## 工具接线状态（9 个工具等真数据）

已通：`calc_achievement`、`wait_penetration`
待接（调用会抛 `ToolNotReady`，**不造假数据**）：

| 工具 | 等谁 |
| ---- | ---- |
| get_weather | B:settings.weather_scenario + core/tool_impl.wire() 启动时覆盖(已由 B 接线) |
| get_soil_status / get_env_status | B:models/ 数据源适配层(11.12 前) |
| create_task / send_device_cmd | F-014 调度器(11.11-12);send_device_cmd 仅 executor 可调 |
| verify_result | F-016 验证引擎(11.13) |
| write_report | F-022 报告(11.13) |
| query_knowledge | F-020 知识库(11.13) |
| raise_alert | B:alerts 告警通道 |

## Git 速记

```bash
git switch -c feature/agents-runner    # 你的分支
# commit 格式：feat(orchestrator): 实现打分公式
git push → GitHub 开 PR → 找一个队友交叉 review 后合并
```

- 你自己也不许直接 push main（保护分支对所有人一视同仁，规矩才立得住）
- `.env` 不进仓库；AI 生成代码先看懂再提交

## 卡住了

四个人一起看。**队长卡住不说话全队停摆，这是大忌**——你有卡点必须第一个说出来。
