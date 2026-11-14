"""工具池接线层（队友 B 地盘）——队长 tools.py 里 ToolNotReady 桩的真身。

设计原则（PRD 7.3 / 12.1）：
- 队长的 tools.py 一行不改：启动时 wire() 把"待接入"桩逐一换成真实现（组合根模式）；
  将来队长想把这些函数挪回他地盘，删掉 wire() 里对应一行即可，其余不受影响；
- 取数/写库只走基座自己的层（queries / registry / command / models / seams），
  Mock/Real 口径不分叉；跨地盘能力（验证/报告/知识库）走 seams，未就绪时抛
  SeamNotReady，由 base.py 作为工具错误回填给 LLM（拒绝留痕）；
- get_weather 读 settings 表 weather_scenario 键（单一事实源），档位表复用
  模拟器的 WEATHER_PRESETS——气象员说的天气和模拟器实际跑的天气永远是同一份。

对外入口：
- get_registry()      带接线的全局工具注册表（单例，MCP / Runner 共用）
- wire_into_app(app)  在 main.py 里挂 MCP Server（队友 A / 评测方可用任意 MCP 客户端连）
"""
from __future__ import annotations

import threading
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select

from .. import seams
from ..db import session_scope
from ..devices import command
from ..models.tasks import Task
from .ids import new_task_no
from .queries import env_status, raise_alert as push_alert, soil_status
from .runtime_settings import get_value


# ─────────────────────────── 报警来源（跨地盘的身份传递）───────────────────────────
# 为什么用 ContextVar 而不是参数：LLM 的工具 schema 里没有 source 时传不进来，所以
# 「谁报的警」由 runner 在调用工具前隐式放进上下文。队长在 base.py 的 _execute_tool 里
# set(self.agent_key) / finally reset(token)，本层负责读。
#
# **变量本体在队长的 app/agents/context.py**，这里直接复用同一个对象——如果两边各建一个
# ContextVar，即使同名也不是同一份存储：他 set 的我永远读不到，source 会静默退化成 "agent"。
# agents/context.py 是只依赖标准库的叶子模块（不 import tools），所以 core → agents.context
# 不会形成 core ↔ agents 循环（真正会循环的是 core → agents.tools）。
try:  # pragma: no cover - 正常部署下必命中
    from ..agents.context import CURRENT_AGENT_KEY
    from ..agents.context import current_agent_source as _source_from_context
except ImportError:  # 独立跑 core 单测、没有 agents/ 时的兜底（行为保持一致）
    CURRENT_AGENT_KEY = ContextVar("current_agent_key", default="")
    _source_from_context = None

# source 的命名空间本身（不是 key）：LLM 的 enum 里含 "system"，直接透传，
# 不能再补成 agent:system——那等于把系统报警冒充成 agent 报警。
_SOURCE_NAMESPACES = {"agent", "system", "user"}


def current_agent_key() -> str | None:
    """当前执行上下文里的 agent_key（scout/decision/executor/verifier...），无则 None。"""
    return CURRENT_AGENT_KEY.get() or None


def _source_from_context_or_default() -> str:
    """缺省来源：优先用队长的 current_agent_source()，没有 agents/ 时按同一规则自算。"""
    if _source_from_context is not None:
        return _source_from_context()
    key = CURRENT_AGENT_KEY.get()
    return f"agent:{key}" if key else "agent"


def normalize_alert_source(source: str | None) -> str:
    """把来源统一成 `agent:{key}` / `system:{what}` 形态（PRD 6.11）。

    接受四种写法，都不歧义：
    - None / 空串       → 读 ContextVar；取不到落 "agent"（LLM 直调时的历史值）
    - "verifier"        → "agent:verifier"（裸 key 自动补前缀，防调用方写成半截）
    - "agent:verifier"/"system:safety" → 原样（已带命名空间）
    - "agent"/"system"  → 原样（命名空间本身，不能再补成 agent:system）
    """
    if source is None or not str(source).strip():
        return _source_from_context_or_default()
    text = str(source).strip()
    if ":" in text or text in _SOURCE_NAMESPACES:
        return text
    return f"agent:{text}"


# ─────────────────────────── 工具实现（签名与队长 tools.py 的 OpenAI schema 对齐）───────────────────────────

def get_weather(city: str = "A区茶园", hours: int = 24) -> dict[str, Any]:
    """统一天气源：settings 表 weather_scenario → 模拟器档位表。"""
    from ..mock.simulator import WEATHER_PRESETS

    scenario = str(get_value("weather_scenario", "sunny") or "sunny")
    preset = WEATHER_PRESETS.get(scenario, WEATHER_PRESETS["sunny"])
    return {"city": city, "hours": hours, "scenario": scenario, **preset}


def get_soil_status(device_id: str | None = None) -> dict[str, Any]:
    """土壤湿度三态 + 目标区间 + 趋势（device_id 缺省时自动解析 A 区土壤设备）。"""
    with session_scope() as db:
        return soil_status(db, device_id)


def get_env_status(device_id: str | None = None) -> dict[str, Any]:
    """空气温湿度 + 光照最新读数。"""
    with session_scope() as db:
        return env_status(db, device_id)


def _pending_device_cmd(action: str) -> str | None:
    """找一张「已经建好但还没真正下发」的同动作 device_cmd 任务，返回它的 task_no。

    为什么需要：决策官建单（tasks 一行 pending）+ 调度器把它标成 dispatched，
    但**真正下发**只有执行管家调 send_device_cmd 这一条路。而 send_device_cmd 的
    schema（队长 PRD 7.3）里没有 task_no，执行管家拿不到任务号时只能自己造一张新单——
    于是库里出现两张单：一张永远超时（实测 task-0005 dispatched → 60s timeout → 重试
    → 再超时），另一张才是真执行的。轨迹页面上看起来像「下了两条指令，一条石沉大海」。

    只在「唯一候选」时自动认领，多个候选就不猜（返回 None，走原逻辑新建）。
    """
    # 刻意不按 created_at 做时间窗过滤：`created_at` 是库端默认值（CURRENT_TIMESTAMP），
    # 它的时区跟着数据库走，而这里是 Python 的 now()——两者一个 UTC 一个东八区时，
    # 刚建出来 3 秒的单会被判成「8 小时前」直接筛掉（实测 MySQL 上就是这样静默失效的）。
    # 状态本身就够判别了：没人下发的单会停在 pending/dispatched，60s 后被调度器转
    # timeout → retrying，自然离开候选集。
    with session_scope() as db:
        rows = db.scalars(
            select(Task)
            .where(
                Task.type == "device_cmd",
                Task.status.in_(("pending", "dispatched")),
                # 关键判别：真下发过的任务一定带 assigned_device（send_cmd 里写的）。
                # 调度器却会把 pending 直接标成 dispatched 而不写设备，所以「dispatched
                # 且 assigned_device 为空」= 建了单但没人真正下发，正是要认领的那一张。
                Task.assigned_device.is_(None),
            )
            .order_by(Task.id.desc())
            .limit(5)
        ).all()
    hits = [row for row in rows if str((row.payload_json or {}).get("action") or "pump") == action]
    if not hits:
        return None
    chosen = hits[0]
    logger.info("执行管家未带 task_no，认领最近一张未下发的 device_cmd 单 {}", chosen.task_no)
    return chosen.task_no


def send_device_cmd(
    device_id: str,
    action: str,
    params: dict[str, Any] | None = None,
    task_no: str | None = None,
) -> dict[str, Any]:
    """唯一指令出口（PRD 7.3 权限铁律：issued_by=agent:executor，白名单已预留）。

    task_no 给了就复用那一单（回执、轨迹、超时重试全部挂到同一张单上）；
    没给且平台侧恰好有一张同动作的待执行单，就认领它（见 _pending_device_cmd）。
    """
    target = task_no or _pending_device_cmd(action)
    with session_scope() as db:
        return command.send_cmd(
            db, device_id, action, params, issued_by="agent:executor", task_no=target,
        )


def create_task(
    type: str,
    payload: dict[str, Any] | None = None,
    priority: int = 5,
    deadline_at: str | None = None,
) -> dict[str, Any]:
    """创建任务写入调度队列（decision / verifier 用）。"""
    deadline = datetime.fromisoformat(deadline_at) if deadline_at else None
    with session_scope() as db:
        task = Task(
            task_no=new_task_no(),
            type=type,
            payload_json=payload or {},
            priority=int(priority),
            status="pending",
            deadline_at=deadline,
        )
        db.add(task)
        db.flush()
        return {
            "task_no": task.task_no,
            "type": task.type,
            "priority": task.priority,
            "status": task.status,
        }


def raise_alert(level: str, message: str, source: str | None = None) -> dict[str, Any]:
    """写 alerts 表 + WS 推送（level 白名单在 queries.push_alert 里校验）。

    source 必须能区分发起方（PRD 6.11）：verifier 那条校验失败报警要落
    `agent:verifier`、安全阀要落 `system:safety`，否则大屏上所有报警都长一个样，
    演示时没法说明「这条是验证不通过自动报的」。

    source 缺省（None）时读 ContextVar CURRENT_AGENT_KEY——由队长的 AgentRunner
    在 _execute_tool 里 set(self.agent_key)，所以 LLM 通过工具调用发的报警也能带上
    真实身份，不需要改工具 schema、也不需要 LLM 自己填。
    verification/ 这类确定性判定直连调用时显式传 "agent:verifier" 即可（更可靠，
    不依赖调用栈上下文）。
    """
    who = normalize_alert_source(source)
    logger.debug("报警来源：{}（level={}）", who, level)
    with session_scope() as db:
        return push_alert(db, level, who, message)


def verify_result(task_no: str) -> dict[str, Any]:
    """手动验证 → 走 seams（队长的验证引擎，未就绪时 SeamNotReady 透传）。"""
    return seams.verify_task(task_no)


def write_report(run_id: int) -> dict[str, Any]:
    """生成报告 → 走 seams（队长的报告后端）。"""
    report_id = seams.generate_report(run_id)
    return {"run_id": run_id, "report_id": report_id}


def query_knowledge(question: str, top_k: int = 4) -> list[dict[str, Any]]:
    """知识库检索 → 走 seams（队长的 RAG retriever）。"""
    return seams.search(question, top_k)


# ─────────────────────────── 接线（组合根）───────────────────────────

_WIRED = (
    ("get_weather", get_weather),
    ("get_soil_status", get_soil_status),
    ("get_env_status", get_env_status),
    ("send_device_cmd", send_device_cmd),
    ("create_task", create_task),
    ("raise_alert", raise_alert),
    ("verify_result", verify_result),
    ("write_report", write_report),
    ("query_knowledge", query_knowledge),
)


def wire(tool_registry: Any) -> list[str]:
    """把桩换成真实现：保留队长的描述与参数 schema，只换 fn。返回换掉的名单。"""
    replaced: list[str] = []
    for name, fn in _WIRED:
        spec = tool_registry.get(name)
        if spec is None:
            logger.warning("工具池接线跳过：{} 不在注册表里（队长改了工具名？）", name)
            continue
        tool_registry.register(name, spec.description, spec.parameters, fn)
        replaced.append(name)
    return replaced


_lock = threading.Lock()
_registry: Any = None


def get_registry() -> Any:
    """全局单例：队长 build_default_registry() + 本层 wire()。Runner / MCP 共用。"""
    global _registry
    if _registry is None:
        with _lock:
            if _registry is None:
                from ..agents.tools import build_default_registry

                reg = build_default_registry()
                replaced = wire(reg)
                logger.info("工具池接线完成：{} 个工具接入真实现（{}）",
                            len(replaced), ", ".join(replaced))
                _registry = reg
    return _registry


def wire_into_app(app: Any) -> None:
    """在 FastAPI 应用上挂 MCP Server（SSE 模式，赛题加分项）。

    路径说明：mcp_server.build_app() 自带 /mcp/sse 与 /mcp/messages 两个路由，
    因此用根挂载（mount("/")）而不是 mount("/mcp")——后者会叠出 /mcp/mcp/*。
    主应用的路由（/api、/docs、/ws）先注册、优先匹配，不受影响。
    注意：不能 include_router（build_app 返回的是完整 FastAPI 应用，队长
    docstring 里的笔误，以这里为准）。
    """
    from ..agents.mcp_server import McpSseServer

    server = McpSseServer(get_registry())
    app.mount("/", server.build_app())
    logger.info("MCP Server 已挂载：/mcp/sse（事件流） + /mcp/messages（JSON-RPC）")
