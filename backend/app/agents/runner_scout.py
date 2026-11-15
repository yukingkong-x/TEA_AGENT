"""scout(巡园管家)Runner 工厂。"""
from app.agents.base import AgentRunner
from app.agents.prompts import AGENTS


def build_runner(llm, registry, **kwargs) -> AgentRunner:
    return AgentRunner(agent_key="scout", llm=llm, registry=registry, spec=AGENTS["scout"], **kwargs)
