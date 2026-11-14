"""PRD 9.1 默认工作流（唯一权威副本）。

为什么放生产代码而不是只放测试：PRD 写的是「首次启动写入 workflows 表」，但基座
`seed.py` 没有建工作流，画布不保存一次就没有任何 run 可跑。这里给启动流程一个
`ensure_default_workflow()`，让「一键启动」在空库上也能直接跑通。

`tests/test_dag.py` 里有一条用例逐字比对 PRD 9.1 的 JSON 与这份定义——改了 PRD
不同步这里就会 fail，反之亦然。
"""
from __future__ import annotations

from loguru import logger

WF_KEY = "patrol_irrigation"
WF_NAME = "巡园浇水工作流"


def default_dag() -> dict:
    """PRD 9.1 默认工作流（含 11.14 的连线修订：n11 → n11b → n13）。"""
    return {
        "wf_key": WF_KEY,
        "name": WF_NAME,
        "nodes": [
            {"id": "n1", "type": "start", "name": "开始", "next": ["n2"]},
            {"id": "n2", "type": "agent", "agent_key": "scout", "name": "巡园播报",
             "input": "开始本轮巡园,目标区域:A区茶垄。", "next": ["n3"]},
            {"id": "n3", "type": "parallel", "name": "三方会诊",
             "branches": ["n4", "n5", "n6"], "next": ["n7"]},
            {"id": "n4", "type": "agent", "agent_key": "weather", "name": "气象评估",
             "input": "评估未来12小时天气对A区灌溉的影响。", "next": []},
            {"id": "n5", "type": "agent", "agent_key": "soil", "name": "墒情分析",
             "input": "分析A区土壤墒情并评级。", "next": []},
            {"id": "n6", "type": "agent", "agent_key": "pest", "name": "植保核查",
             "input": "核查当前墒情下灌溉的农艺风险。", "next": []},
            {"id": "n7", "type": "agent", "agent_key": "decision", "name": "灌溉决策",
             "input": "汇总上述三方结论与本轮巡园播报,按决策树给出决策;若 irrigate 则创建浇水任务。",
             "next": ["n8"]},
            {"id": "n8", "type": "condition", "name": "决策分流",
             "expression": "context.last_decision == 'irrigate'",
             "branches": {"true": ["n9"], "false": ["n12"]}},
            {"id": "n9", "type": "agent", "agent_key": "executor", "name": "执行浇水",
             "input": "领取设备指令任务并执行,跟踪回执直到完成或熔断。", "next": ["n10"]},
            {"id": "n10", "type": "tool", "tool": "wait_penetration", "params": {"seconds": 90},
             "name": "渗透等待", "next": ["n11"]},
            {"id": "n11", "type": "agent", "agent_key": "verifier", "name": "验证审计",
             "input": "对刚完成的浇水任务执行复测验证,不达标启动Self-Loop修正。",
             "next": ["n11b"]},
            {"id": "n11b", "type": "loop", "name": "Self-Loop", "max_iterations": 2,
             "exit_expression": "context.last_verification == 'success' or context.round > 2",
             "body_next": "n11", "next": ["n13"]},
            {"id": "n12", "type": "agent", "agent_key": "verifier", "name": "无需作业归档",
             "input": "本轮决策为暂不作业,生成简要记录。", "next": ["n13"]},
            {"id": "n13", "type": "end", "name": "结束"},
        ],
        "edges": [],
    }


def ensure_default_workflow() -> int | None:
    """幂等：库里没有 patrol_irrigation 就写一份。返回 wf_id（失败返回 None）。"""
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.workflows import Workflow
    from app.workflow.dag import validate_dag

    dag = default_dag()
    errors = validate_dag(dag)          # 模板自己都不合法就别写进库
    if errors:
        logger.error("默认工作流未通过自检，未写入：{}", errors)
        return None

    with session_scope() as db:
        existing = db.scalar(select(Workflow).where(Workflow.wf_key == WF_KEY))
        if existing is not None:
            return int(existing.id)
        row = Workflow(wf_key=WF_KEY, name=WF_NAME, dag_json=dag, version=1, enabled=True)
        db.add(row)
        db.flush()
        logger.info("已写入默认工作流 {}（wf_id={}，{} 个节点）", WF_KEY, row.id, len(dag["nodes"]))
        return int(row.id)
