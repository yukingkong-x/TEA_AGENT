"""DAG 校验（PRD 9.1 / REQ-F-004 验收：无环、单 start 单 end、agent_key 存在）。

工作流引擎本体归队长（workflow/engine.py）；这里只做「保存前必须拦住环图」这一道闸，
避免前端在画布上拖出一个环就把库写脏。引擎若提供自己的校验函数，workflows.py 会优先用它。
"""
from __future__ import annotations

from typing import Any, Iterable

NODE_TYPES = {"start", "agent", "tool", "condition", "parallel", "loop", "end"}


def _children(node: dict[str, Any]) -> list[str]:
    """普通后继边（不含 loop 的 body_next 回边）。"""
    out: list[str] = []
    nxt = node.get("next")
    if isinstance(nxt, str):
        out.append(nxt)
    elif isinstance(nxt, list):
        out.extend([x for x in nxt if isinstance(x, str)])
    branches = node.get("branches")
    if isinstance(branches, list):
        out.extend([x for x in branches if isinstance(x, str)])
    elif isinstance(branches, dict):
        for value in branches.values():
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, list):
                out.extend([x for x in value if isinstance(x, str)])
    return out


def validate_dag(dag: dict[str, Any], known_agents: Iterable[str] | None = None) -> list[str]:
    """返回错误列表；空列表表示通过。"""
    errors: list[str] = []
    nodes = dag.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["dag.nodes 必须是非空数组"]

    ids: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"第 {index} 个节点不是对象")
            continue
        node_id = node.get("id")
        node_type = node.get("type")
        if not node_id:
            errors.append(f"第 {index} 个节点缺少 id")
            continue
        if node_id in by_id:
            errors.append(f"节点 id 重复：{node_id}")
        by_id[node_id] = node
        ids.append(node_id)
        if node_type not in NODE_TYPES:
            errors.append(f"节点 {node_id} 的 type={node_type} 非法（允许 {sorted(NODE_TYPES)}）")
        if node_type == "agent" and not node.get("agent_key"):
            errors.append(f"agent 节点 {node_id} 缺少 agent_key")

    starts = [i for i in ids if by_id[i].get("type") == "start"]
    ends = [i for i in ids if by_id[i].get("type") == "end"]
    if len(starts) != 1:
        errors.append(f"必须有且只有一个 start 节点，当前 {len(starts)} 个（{starts}）")
    if len(ends) != 1:
        errors.append(f"必须有且只有一个 end 节点，当前 {len(ends)} 个（{ends}）")

    # 引用完整性
    for node_id, node in by_id.items():
        for child in _children(node):
            if child not in by_id:
                errors.append(f"节点 {node_id} 的 next/branches 指向不存在的节点 {child}")
        body = node.get("body_next")
        if isinstance(body, str) and body not in by_id:
            errors.append(f"loop 节点 {node_id} 的 body_next 指向不存在的节点 {body}")

    if known_agents is not None:
        known = set(known_agents)
        if known:  # agents 表为空时跳过（队长首启写入之前）
            for node_id, node in by_id.items():
                if node.get("type") == "agent":
                    key = node.get("agent_key")
                    if key not in known:
                        errors.append(f"节点 {node_id} 引用了未定义的 agent_key={key}")

    # 环检测（DFS 三色标记，忽略 loop 的 body_next 回边）
    color: dict[str, int] = {}

    def walk(node_id: str, stack: list[str]) -> None:
        color[node_id] = 1
        stack.append(node_id)
        for child in _children(by_id.get(node_id, {})):
            if child not in by_id:
                continue
            if color.get(child) == 1:
                cycle = " → ".join(stack[stack.index(child) :] + [child])
                errors.append(f"检测到环：{cycle}")
            elif color.get(child, 0) == 0:
                walk(child, stack)
        color[node_id] = 2
        stack.pop()

    for node_id in ids:
        if color.get(node_id, 0) == 0:
            walk(node_id, [])

    # 可达性（从 start 出发）
    if starts:
        seen: set[str] = set()
        queue = [starts[0]]
        while queue:
            cur = queue.pop()
            if cur in seen or cur not in by_id:
                continue
            seen.add(cur)
            node = by_id[cur]
            queue.extend(_children(node))
            body = node.get("body_next")
            if isinstance(body, str):
                queue.append(body)
        unreachable = [i for i in ids if i not in seen]
        if unreachable:
            errors.append(f"以下节点从 start 不可达：{unreachable}")

    return errors
