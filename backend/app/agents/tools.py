"""REQ-F-003:工具池(PRD 7.3)——统一注册表 + 权限白名单 + OpenAI 函数 schema。

- 10 个 Agent 工具 + 1 个工作流工具 wait_penetration(PRD 9.1/9.2);
- 权限铁律:send_device_cmd 仅 executor 的绑定表里有,can_use 之外的一律拒绝
  (拒绝留痕由 AgentRunner 完成,PRD 7.3);
- 通过 MCP Server(SSE /mcp)对外暴露,见 mcp_server.py;
- 依赖他人地盘的工具显式抛 ToolNotReady(11.13 前逐个接入,勿静默造假数据)。

接入点(给队友 B):get_soil_status / get_env_status 走数据源适配层(REQ-F-019,
PRD 12.1),raise_alert 写 alerts 表 + WS 推送。
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.agents.prompts import AGENTS, AgentSpec


class ToolNotReady(RuntimeError):
    """工具已注册但依赖的地盘尚未接入。"""

    def __init__(self, name: str, reason: str):
        super().__init__(f"工具 {name} 待接入:{reason}")
        self.tool_name = name


class ToolNotFoundError(KeyError):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Any]


class ToolRegistry:
    """统一工具注册表:注册 / 检索 / 白名单 / OpenAI schema / 执行。"""

    def __init__(self, bindings: dict[str, AgentSpec]):
        self._bindings = bindings
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, description: str, parameters: dict, fn: Callable[..., Any]) -> None:
        self._tools[name] = ToolSpec(name=name, description=description, parameters=parameters, fn=fn)

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def can_use(self, agent_key: str, tool_name: str) -> bool:
        """PRD 7.3 权限白名单:工具必须已注册,且在 agent 的绑定表里。"""
        spec = self._bindings.get(agent_key)
        return bool(spec and tool_name in spec.tools and tool_name in self._tools)

    def to_openai_schemas(self) -> list[dict]:
        """openai SDK tools 参数的函数 schema 列表。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def invoke(self, name: str, arguments: dict) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(name)
        result = tool.fn(**arguments)
        if inspect.isawaitable(result):
            result = await result
        return result


# ─────────────────────────── 纯规则工具 ───────────────────────────

def calc_achievement(baseline: float, target_low: float, target_high: float, measured: float) -> float:
    """PRD 11.1 达成率公式(REQ-F-016 的公式本体,提前随工具池落地)。"""
    if target_low <= baseline:
        raise ValueError(f"target_low({target_low}) 必须大于 baseline({baseline})")
    if target_low <= measured <= target_high:
        return 100.0
    if measured > target_high:
        return 100.0  # over_irrigated 标注由验证引擎负责(REQ-F-016)
    return round(max(0.0, (measured - baseline) / (target_low - baseline)) * 100, 2)


async def wait_penetration(seconds: int) -> dict:
    """PRD 9.1 工作流工具节点:渗透等待定时器。"""
    await asyncio.sleep(seconds)
    return {"waited_s": seconds}


# ─────────────────────────── Mock 天气数据源(PRD 12.3)───────────────────────────
# 固定档位可切换:演示"降雨暂缓灌溉"分支时切 rainy。接入模拟器/设置页时复用 set_weather_profile。

WEATHER_PROFILES: dict[str, dict] = {
    "sunny": {"temp_range": [14, 26], "rain_prob": 10, "frost_risk": False},
    "cloudy": {"temp_range": [12, 22], "rain_prob": 30, "frost_risk": False},
    "rainy": {"temp_range": [11, 18], "rain_prob": 70, "frost_risk": False},
    "frost": {"temp_range": [1, 8], "rain_prob": 20, "frost_risk": True},
}
_weather_profile = "sunny"


def get_weather(city: str, hours: int = 12) -> dict:
    return {**WEATHER_PROFILES[_weather_profile], "city": city, "hours": hours}


def set_weather_profile(name: str) -> None:
    if name not in WEATHER_PROFILES:
        raise ValueError(f"未知天气档位: {name},可选 {list(WEATHER_PROFILES)}")
    global _weather_profile
    _weather_profile = name


# ─────────────────────────── 待接入工具(显式抛错,勿造假数据)───────────────────────────

def _not_ready(name: str, reason: str):
    def stub(**kwargs):
        raise ToolNotReady(name, reason)
    return stub


def build_default_registry(bindings: Optional[dict[str, AgentSpec]] = None) -> ToolRegistry:
    """按 PRD 7.3 注册全部工具;bindings 默认取 AGENTS(PRD 8.1)。"""
    registry = ToolRegistry(bindings=bindings or AGENTS)
    _obj = {"type": "object"}
    registry.register("get_weather", "获取目标区域未来天气(Mock 档位数据源)",
                      {"type": "object",
                       "properties": {"city": {"type": "string"}, "hours": {"type": "integer"}},
                       "required": ["city"]},
                      get_weather)
    registry.register("get_soil_status", "获取土壤湿度、更新时间与趋势",
                      {"type": "object",
                       "properties": {"device_id": {"type": "string"}},
                       "required": ["device_id"]},
                      _not_ready("get_soil_status", "等待队友 B 数据源适配层(REQ-F-019)"))
    registry.register("get_env_status", "获取空气温湿度与光照",
                      {"type": "object",
                       "properties": {"device_id": {"type": "string"}},
                       "required": ["device_id"]},
                      _not_ready("get_env_status", "等待队友 B 数据源适配层(REQ-F-019)"))
    registry.register("query_knowledge", "检索知识库,返回带引用的条目",
                      {"type": "object",
                       "properties": {"question": {"type": "string"},
                                      "top_k": {"type": "integer"}},
                       "required": ["question"]},
                      _not_ready("query_knowledge", "REQ-F-020 知识库(11.13)"))
    registry.register("create_task", "创建任务写入调度队列",
                      {"type": "object",
                       "properties": {"type": {"type": "string"},
                                      "payload": {"type": "object"},
                                      "priority": {"type": "integer"},
                                      "deadline_at": {"type": "string"}},
                       "required": ["type", "payload", "priority"]},
                      _not_ready("create_task", "REQ-F-014 调度器(11.12)"))
    registry.register("send_device_cmd", "下发设备指令(executor 独占)",
                      {"type": "object",
                       "properties": {"device_id": {"type": "string"},
                                      "action": {"type": "string"},
                                      "params": {"type": "object"}},
                       "required": ["device_id", "action", "params"]},
                      _not_ready("send_device_cmd", "等待 devices/command.py(队友 B)+ REQ-F-014"))
    registry.register("verify_result", "对任务触发复测与达成率验证",
                      {"type": "object",
                       "properties": {"task_no": {"type": "string"}},
                       "required": ["task_no"]},
                      _not_ready("verify_result", "REQ-F-016 验证引擎(11.13)"))
    registry.register("calc_achievement", "按公式计算达成率(0-100)",
                      {"type": "object",
                       "properties": {"baseline": {"type": "number"},
                                      "target_low": {"type": "number"},
                                      "target_high": {"type": "number"},
                                      "measured": {"type": "number"}},
                       "required": ["baseline", "target_low", "target_high", "measured"]},
                      calc_achievement)
    registry.register("write_report", "汇总执行过程生成 Markdown 报告",
                      {"type": "object",
                       "properties": {"run_id": {"type": "integer"}},
                       "required": ["run_id"]},
                      _not_ready("write_report", "REQ-F-022 报告后端(11.13)"))
    registry.register("raise_alert", "写报警表并 WS 推送",
                      {"type": "object",
                       "properties": {"level": {"type": "string",
                                                "enum": ["info", "warning", "critical"]},
                                      "message": {"type": "string"}},
                       "required": ["level", "message"]},
                      _not_ready("raise_alert", "等待 alerts 表与 WS 推送(队友 B)"))
    registry.register("wait_penetration", "渗透等待定时器(工作流 tool 节点)",
                      {"type": "object",
                       "properties": {"seconds": {"type": "integer"}},
                       "required": ["seconds"]},
                      wait_penetration)
    return registry
