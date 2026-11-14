# run 归属（run_id）+ 建单派发目标（assigned_device）修复交接

> 对应正本 `497342e`。我只动自己地盘的 `core/ devices/ models/ tests/`，
> `agents/ workflow/ verification/ knowledge/ orchestrator/` 一行没碰（正本为准）。

## 一、你提的两个问题的处理

### 1. create_task 不写 run_id

**机制**：新增叶子模块 `core/run_context.py`

```python
CURRENT_RUN_ID: ContextVar[int | None]      # 变量本体
current_run_id() -> int | None              # 读
set_current_run_id(run_id) / reset_current_run_id(token)   # 引擎起跑时 set / finally reset
```

- `core/tool_impl.create_task()` 落库时写 `run_id = 参数 or current_run_id()`
- `devices/command.send_cmd()` 执行管家自建的单同样写 `run_id = current_run_id()`
  （原来硬编码 `run_id=None`，所以 run 19 的真执行单 task-0012 是 NULL）
- 验证记录不用改：`verification/wiring._save_verification` 本来就从 task 读 run_id，
  任务有了它自然就有了（实测 verif 12 → run=23）

**为什么放叶子模块**：`devices/command.py` 也要读，而 `tool_impl` 反过来要 import `command`，
变量放 tool_impl 会形成循环导入。

**你需要加的一行**（`workflow/engine.py` 的 `start_run._drive()`，有它就不依赖下面的兜底）：

```python
async def _drive() -> None:
    from app.core.run_context import set_current_run_id, reset_current_run_id
    token = set_current_run_id(run_id)
    try:
        result = await engine.run(dag, run_id=run_id, trigger=trigger, init_context=init_context)
        _deps.update_run(run_id, result.status, result.context, result.error)
    except Exception as exc:
        _deps.update_run(run_id, "failed", {}, f"{type(exc).__name__}: {exc}")
    finally:
        reset_current_run_id(token)
```

**兜底（已经生效，所以你不加也能跑）**：ContextVar 为空时，若库里**恰好只有一条**
`status='running'` 的 run 就认它；0 条或多条都不猜，记 NULL 并打 warning。
挂错 run 比记 NULL 更难排查，所以不猜。

> ⚠️ 这条兜底依赖「僵尸 running 清干净」。我在库里发现**三条**僵尸 running（不是一条）：
> #10（12:18 起）、#14（12:25 起）、#16（12:29 起），都已收敛为 `failed` + `context.error` 留痕。

### 2. create_task 要能落 assigned_device

`core/tool_impl._resolve_task_device()`：建单时把 `payload.device_id` 解析成真实 id 写进
`Task.assigned_device`，并把解析结果**回写** `payload.device_id`（执行管家拿到的就是真 id）。

- 解析走 `core/device_match.py`：`mock-k10-act-03` 精确命中；`"A区"` 这类指代按 `role=actuator`
  解析（`device_cmd` 的目标必然是泵/阀，不显式给 role 会解析成土壤探头）
- 解析不到时**原样保留**并打 warning：任务列表里至少看得出「想发给谁」，比 NULL 好查
- 设备表为空（真机还没登记）时不硬造 id

### 3. 顺带修掉的一个自查 bug（重要）

改了 assigned_device 之后，执行管家的「任务认领」判据失效了：
原来靠 `assigned_device IS NULL` 区分「建了没发」，现在建单就有值 → 认领不到 → 又建一张新单。
run 19 实测就是 task-0011（反复超时→dead）+ task-0012（真执行）两张。

新判据：`command.send_cmd` 每次真下发写一条 `event="dispatch"` 轨迹，
认领时排除「已有 dispatch 轨迹」的单（`core/tool_impl._pending_device_cmd`）。
`event` 是 String 列、`orchestrator/events.build` 不校验取值，所以没改你的 events.py。

run 23 实测：一张单 `task-0014`，轨迹 `pending→dispatched → dispatch → running → success`。

## 二、实测证据（run 23，真模型 glm-4-flash）

```
run 23 success 12:56:20 -> 12:59:26
task task-20261114-0014 success run=23 dev=mock-k10-act-03
  task_status pending->dispatched  by=scheduler
  dispatch    dispatched->dispatched by=scheduler   ← 真下发凭据
  task_status dispatched->running  by=device ack
  task_status running->success     by=device ack
verif 12 task-20261114-0014 run=23 success ach=94.85
GET /api/runs/23 → run success, tasks[1] = task-0014(run=23), messages 7
```

## 三、演示前清掉的脏数据

| 对象 | 处理 |
|---|---|
| task-20261114-0005/0006/0007/0008（dead / dispatched 卡住） | 删除任务 + 其轨迹（15/15/15/11 条） |
| run #10 / #14 / #16（僵尸 running） | 收敛为 `failed`，`context.error="zombie: 后端重启/进程中断…"`，agent_messages 保留 |
| task-20261114-0011 / 0013（重复建单留下的死单） | 删除任务 + 轨迹 + 对应验证记录（verif 8/9/10/11 全是 0.00 假数据） |
| task-20261114-0012（run 19 的真执行单，run_id 为 NULL） | 回填 `run_id=19` |
| run #21 / #22（12:55 重启窗口里的瞬时失败：`runner_scout.py` 当时正被覆盖） | 删除（无任务、无报告） |

没动：真机 `k10-act-03` / `esp32-soil-02` 全部数据、run 17/18/19/20/23、task-0009/0010/0012/0014。

## 四、还剩一件建议你做的事

`send_device_cmd` 的 schema（`agents/tools.py`）里没有 `task_no`，执行管家永远拿不到任务号，
只能靠上面那套「认领」。稳妥的做法是加一个可选参数，让引擎把 `context["last_task_no"]`
直接递给它：

```python
registry.register("send_device_cmd", "下发设备指令(executor 独占)",
                  {"type": "object",
                   "properties": {"device_id": {"type": "string"},
                                  "action": {"type": "string"},
                                  "params": {"type": "object"},
                                  "task_no": {"type": "string"}},   # ← 新增，可选
                   "required": ["device_id", "action", "params"]},
                  ...)
```

基座侧 `send_device_cmd(device_id, action, params, task_no=None)` 已经支持，认领逻辑继续兜底。

## 五、我改了哪些文件

```
backend/app/core/run_context.py                     新增（ContextVar + 兜底）
backend/app/core/tool_impl.py                       create_task 写 run_id/assigned_device；认领改用 dispatch 事件
backend/app/devices/command.py                      send_cmd 写 run_id；轨迹补 event="dispatch"
backend/app/models/task_events.py                   事件取值注释补 dispatch
backend/tests/test_create_task_attribution.py       新增 9 例
backend/tests/test_send_cmd_attribution.py          新增 2 例
backend/tests/test_executor_attach.py               判据改成 dispatch 事件（5 例）
```

全量测试：`110 passed`（宿主 3.13 / 容器 3.11 同源）。
