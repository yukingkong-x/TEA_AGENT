"""PRD 20.2 规则降级模板(REQ-F-001 的一部分)。

LLM 连续 2 次失败后,Agent 改用纯规则模板输出,保证流程不断:
- 巡园管家:直接拼接最新遥测数据为播报文本(纯代码,无 LLM);
- 决策官:硬编码决策树(土壤<40% 且无霜冻/降雨预警 → irrigate 30s;否则 none);
- 验证官:验证引擎本身是纯规则(第 11 章),天然不依赖 LLM;
- 其余 Agent:明确标注降级,不编造内容。

DEGRADED_PREFIX 是"⚠️ 模型降级中"徽章的数据口径:AgentRunner 把该前缀写入
agent_messages.content,前端识别前缀渲染黄条(见 docs/contracts/agent-data-contract.md)。
"""
from __future__ import annotations

import time
from typing import Callable

from app.agents.prompts import AGENTS

# 降级输出前缀(前端据此显示「⚠️ 模型降级中」徽章,PRD 7.2)
DEGRADED_PREFIX = "⚠️ 模型降级中\n"


def scout_fallback(env_status: dict, soil_status: dict, now_text: str = "") -> str:
    """巡园管家降级:纯数据拼接播报(PRD 20.2)。"""
    if not now_text:
        now_text = time.strftime("%H:%M")
    return (
        f"【巡园播报】时间 {now_text}。A区:"
        f"气温{env_status['temperature_c']}℃ 空气湿度{env_status['humidity_air']}% "
        f"光照{env_status['lux']}lux "
        f"土壤湿度{soil_status['soil_moisture']}%(趋势:{soil_status.get('trend', '平')})。\n"
        f"(规则降级输出:纯数据拼接,无模型判断)"
    )


def decision_fallback(
    soil_moisture: float,
    has_rain_alert: bool = False,
    has_frost_alert: bool = False,
) -> str:
    """决策官降级:硬编码决策树(PRD 20.2)。"""
    if soil_moisture < 40 and not has_rain_alert and not has_frost_alert:
        return (
            "【决策】本轮决策:irrigate。\n"
            "方案:对A区执行浇水30秒,目标湿度55-65%,优先级9。\n"
            "依据:规则模板(模型降级)——土壤<40% 且无霜冻/降雨预警。"
        )
    return (
        "【决策】本轮决策:none。\n"
        "方案:本轮无需作业。\n"
        "依据:规则模板(模型降级)——墒情不缺水或存在预警。"
    )


def generic_fallback(agent_key: str) -> str:
    """其余 Agent 降级:明确标注,不编造内容。"""
    name = AGENTS[agent_key].name if agent_key in AGENTS else agent_key
    return f"【模型降级】{name} 本轮以规则模板输出,等待模型恢复。"


# agent_key → 降级模板函数(入参 context dict,由 AgentRunner 注入)
FALLBACKS: dict[str, Callable[[dict], str]] = {
    "scout": lambda ctx: scout_fallback(
        ctx.get("env_status") or {"temperature_c": "-", "humidity_air": "-", "lux": "-"},
        ctx.get("soil_status") or {"soil_moisture": "-", "trend": "平"},
    ),
    "decision": lambda ctx: decision_fallback(
        soil_moisture=ctx.get("soil_moisture", 100.0),
        has_rain_alert=ctx.get("has_rain_alert", False),
        has_frost_alert=ctx.get("has_frost_alert", False),
    ),
}
