# contracts —— 契约变更记录

契约本体在 PRD 第 5 章（MQTT 报文）和第 7 章（REST API / 工具池），这里是变更流水账。

想改契约的流程：**开 issue → 队长同意 → 改 PRD → 在这里追加一行**。

格式：`日期 ｜ 改了哪条 ｜ 谁同意的`，一行一条，最新的放最上面。

---

| 日期 | 改了哪条 | 谁同意的 |
| ---- | -------- | -------- |
| 2026-11-14 | 新增调度事件 `task_status`(WS):`{task_no,run_id,from,to,reason,retry_count,score,assigned_agent,assigned_device}`,另 `result.rejected=breaker_open`。**`tasks.status` 枚举缺 `needs_human`**(PRD 10.2/11.3 要),补之前前端按 `result_json.verdict` 判转人工徽章 | 队长定,B 补枚举 |
| 2026-11-14 | 知识库检索口径:`search` 返回 `{title, chunk_text, score, doc_id, chunk_index}`,`score` 为稀疏余弦(0~1),有 **0.03 噪声地板**,空数组=未检索到属正常结果;`ingest` 返回体增 `backend`(`chroma+local`/`local`)与 `chars`,原 `chunk_count`/`chroma_ids` 不变 | 队长定,A 照此渲染引用 |
| 2026-11-14 | 新增 `app.knowledge.loader.delete(doc_id)`:`DELETE /api/knowledge/{id}` 目前只删 MySQL 记录,向量库会留孤儿块(检索仍命中已删文档)。请 B 在删除接口里补一行 `seams`/`loader.delete` 调用 | 队长提,B 执行 |
| 2026-11-14 | `GET /api/devices` 默认行为回退:缺省 `is_mock=None` 返回**全量**,只有显式 `true`/`false` 才过滤(`all` 等价缺省)。理由:演示现场 Mock 与真机可能同时在跑,按 mode 过滤会丢信息;契约默认值不许悄悄变 | 队长定,B 执行 |
| 2026-11-14 | 报警 `source` 口径:落库形态统一 `agent:<key>`(PRD 6.11)。`raise_alert` 的 tool schema 新增可选 `source`(enum = 7 个 agent_key + `system`),缺省由 `agents/context.py` 的 ContextVar 按当前 Agent 自动填充;`verification/` 引擎为确定性判定,直连调用不经 LLM | 队长定 |
| 2026-11-14 | PRD 9.1 默认 DAG 修订:连线改为 `n11 → n11b → n13`(原 `n11 → n13` 让 Self-Loop 的 `n11b` 无入边,可达性校验判它孤儿);同时修 `edges` 尾逗号语法错误,`edges` 恒为 `[]`,边只由 `next`/`branches`/`body_next` 声明 | 队长 |
| 2026-11-09 | 新增「LLM 降级标记口径」:降级输出以 `⚠️ 模型降级中` 前缀标记,前端据此前缀显示降级徽章;详见 agent-data-contract.md | 队长提,待 11.9 站会 A/B 确认 |
