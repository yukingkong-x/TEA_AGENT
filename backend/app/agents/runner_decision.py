"""decision(灌溉决策官)Runner 工厂。"""
from app.agents.base import AgentRunner
from app.agents.prompts import AGENTS


def build_runner(llm, registry, **kwargs) -> AgentRunner:
    return AgentRunner(agent_key="decision", llm=llm, registry=registry, spec=AGENTS["decision"], **kwargs)
