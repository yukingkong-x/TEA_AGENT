"""REQ-F-002 runner_{key}.py 冒烟测试:7 个工厂的键名与规格绑定正确。"""
import importlib

import pytest

from app.agents.prompts import AGENTS
from app.agents.tools import build_default_registry

FILES = {
    "scout": "runner_scout",
    "weather": "runner_weather",
    "soil": "runner_soil",
    "pest": "runner_pest",
    "decision": "runner_decision",
    "executor": "runner_executor",
    "verifier": "runner_verifier",
}


@pytest.mark.parametrize("agent_key,module_name", sorted(FILES.items()))
def test_build_runner_binds_correct_agent(agent_key, module_name):
    # 断点:某个 runner 文件绑错 agent_key / 规格(复制粘贴错位)→ 本测试失败
    mod = importlib.import_module(f"app.agents.{module_name}")
    runner = mod.build_runner(llm=None, registry=build_default_registry())
    assert runner.agent_key == agent_key
    assert runner.spec is AGENTS[agent_key]
    assert runner.spec.tools == AGENTS[agent_key].tools
