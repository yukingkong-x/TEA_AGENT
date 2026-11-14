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
from datetime import datetime
from typing import Any

from loguru import logger

from .. import seams
from ..db import session_scope
from ..devices import command
from ..models.tasks import Task
from .ids import new_task_no
from .queries import env_status, raise_alert as push_alert, soil_status
from .runtime_settings import get_value


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


def send_device_cmd(device_id: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """唯一指令出口（PRD 7.3 权限铁律：issued_by=agent:executor，白名单已预留）。"""
    with session_scope() as db:
        return command.send_cmd(db, device_id, action, params, issued_by="agent:executor")


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


def raise_alert(level: str, message: str, source: str = "agent") -> dict[str, Any]:
    """写 alerts 表 + WS 推送（level 白名单在 queries.push_alert 里校验）。

    source 必须能区分发起方（PRD 6.11）：verifier 那条校验失败报警要落
    `agent:verifier`、安全阀要落 `system:safety`，否则大屏上所有报警都长一个样，
    演示时没法说明"这条是验证不通过自动报的"。
    工具 schema 里没有 source 参数（队长 tools.py 只有 level/message），
    LLM 调用走默认值；runner 直接调用时请显式传自己的身份。
    """
    with session_scope() as db:
        return push_alert(db, level, source, message)


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
