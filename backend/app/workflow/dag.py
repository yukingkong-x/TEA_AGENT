"""REQ-F-004:DAG 结构校验(PRD 9.1 / 9.2)。

本模块是**权威实现**:后端 `seams.validate_dag()` 优先调用它,引擎不可用时才回落到
`app/api/_dag.py` 的本地闸门(队友 B 维护)。两边判定必须一致,差异以本模块为准。

职责边界:
- 只做「图」与「节点语义」的静态校验,不碰数据库、不调 LLM;
- 表达式只校验**语法与算子白名单**(PRD 9.2 要求 ast 白名单、禁 eval),
  不校验变量是否存在——`context.*` 的取值只有运行期才有。

设计取舍:
- loop 节点允许没有入边(结构豁免)。PRD 9.1 的默认 DAG 里 `n11b` 就是这种形态:
  它环绕 `body_next` 标明的节点,靠 `body_next` 可达性判定是否可达。虽然已把默认连线
  改成 `n11 → n11b` 让语义更直白,豁免仍保留——画布用户先拖 loop 再连线是常态。
"""
from __future__ import annotations

import ast
from typing import Any, Iterable

NODE_TYPES = {"start", "agent", "tool", "condition", "parallel", "loop", "end"}

# PRD 9.2:表达式沙箱只允许这些语法单元(禁 Call/Subscript/Lambda/推导式/字符串插值)
_ALLOWED_AST = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Compare, ast.BinOp,
    ast.Name, ast.Attribute, ast.Constant, ast.Load,
    ast.And, ast.Or, ast.Not, ast.USub,
    ast.Add, ast.Sub,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
)


def _children(node: dict[str, Any]) -> list[str]:
    """普通后继边(不含 loop 的 body_next 回边)。"""
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


def _check_expression(expr: Any, node_id: str, field: str, errors: list[str]) -> None:
    """条件/退出表达式:语法可解析 + 算子在白名单内(PRD 9.2 铁律:禁 eval)。"""
    if not isinstance(expr, str) or not expr.strip():
        errors.append(f"节点 {node_id} 的 {field} 必须是非空字符串")
        return
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        errors.append(f"节点 {node_id} 的 {field} 语法错误:{exc.msg}（表达式:{expr}）")
        return
    for sub in ast.walk(tree):
        if not isinstance(sub, _ALLOWED_AST):
            errors.append(
                f"节点 {node_id} 的 {field} 含不允许的语法 {type(sub).__name__}（PRD 9.2:"
                f"仅允许 context.* 与比较/逻辑运算，禁函数调用与下标）"
            )
            return


def validate_dag(
    dag: dict[str, Any],
    known_agents: Iterable[str] | None = None,
    known_tools: Iterable[str] | None = None,
) -> list[str]:
    """返回错误列表,空列表表示通过。"""
    errors: list[str] = []
    if not isinstance(dag, dict):
        return ["dag 必须是对象"]
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
        if not node_id or not isinstance(node_id, str):
            errors.append(f"第 {index} 个节点缺少 id")
            continue
        if node_id in by_id:
            errors.append(f"节点 id 重复:{node_id}")
        by_id[node_id] = node
        ids.append(node_id)
        if node_type not in NODE_TYPES:
            errors.append(f"节点 {node_id} 的 type={node_type} 非法(允许 {sorted(NODE_TYPES)})")
        if node_type in {"agent", "tool", "condition", "parallel", "loop"} and not node.get("name"):
            errors.append(f"节点 {node_id}({node_type})缺少 name")

    starts = [i for i in ids if by_id[i].get("type") == "start"]
    ends = [i for i in ids if by_id[i].get("type") == "end"]
    if len(starts) != 1:
        errors.append(f"必须有且只有一个 start 节点,当前 {len(starts)} 个({starts})")
    if len(ends) != 1:
        errors.append(f"必须有且只有一个 end 节点,当前 {len(ends)} 个({ends})")

    # ── 引用完整性 + 每种节点的必填语义(PRD 9.2 表) ──
    known_agent_set = set(known_agents or ())
    known_tool_set = set(known_tools or ())
    for node_id, node in by_id.items():
        node_type = node.get("type")
        for child in _children(node):
            if child not in by_id:
                errors.append(f"节点 {node_id} 的 next/branches 指向不存在的节点 {child}")

        body = node.get("body_next")
        if body is not None:
            if not isinstance(body, str) or body not in by_id:
                errors.append(f"节点 {node_id} 的 body_next 指向不存在的节点 {body}")
            elif node_type != "loop":
                errors.append(f"节点 {node_id} 不是 loop 类型,不应有 body_next")

        if node_type == "agent":
            key = node.get("agent_key")
            if not key:
                errors.append(f"agent 节点 {node_id} 缺少 agent_key")
            elif known_agent_set and key not in known_agent_set:
                errors.append(f"节点 {node_id} 引用了未定义的 agent_key={key}")
        elif node_type == "tool":
            name = node.get("tool")
            if not name:
                errors.append(f"tool 节点 {node_id} 缺少 tool 名")
            elif known_tool_set and name not in known_tool_set:
                errors.append(f"节点 {node_id} 引用了未注册的工具 {name}")
            params = node.get("params")
            if params is not None and not isinstance(params, dict):
                errors.append(f"tool 节点 {node_id} 的 params 必须是对象")
        elif node_type == "condition":
            branches = node.get("branches")
            if not isinstance(branches, dict):
                errors.append(f"condition 节点 {node_id} 的 branches 必须是 {{true,false}} 对象")
            else:
                for key in ("true", "false"):
                    target = branches.get(key)
                    if not isinstance(target, list) or not target:
                        errors.append(f"condition 节点 {node_id} 缺少 branches.{key}(必须是非空数组)")
            if node.get("next"):
                errors.append(f"condition 节点 {node_id} 不应有 next(分流走 branches)")
            _check_expression(node.get("expression"), node_id, "expression", errors)
        elif node_type == "parallel":
            branches = node.get("branches")
            if not isinstance(branches, list) or len(branches) < 2:
                errors.append(f"parallel 节点 {node_id} 的 branches 必须是非空数组(至少 2 路扇出)")
        elif node_type == "loop":
            if not body:
                errors.append(f"loop 节点 {node_id} 缺少 body_next(循环体入口)")
            max_iter = node.get("max_iterations")
            if not isinstance(max_iter, int) or isinstance(max_iter, bool) or max_iter < 1:
                errors.append(f"loop 节点 {node_id} 的 max_iterations 必须是正整数")
            _check_expression(node.get("exit_expression"), node_id, "exit_expression", errors)
        elif node_type in {"start", "end"}:
            if body is not None:
                errors.append(f"{node_type} 节点 {node_id} 不应有 body_next")
            if node_type == "start" and not _children(node):
                errors.append(f"start 节点 {node_id} 缺少 next(流程无处可去)")
            if node_type == "end" and _children(node):
                errors.append(f"end 节点 {node_id} 不应有 next/branches(流程到此为止)")

    # ── 环检测:DFS 三色标记,忽略 loop 的 body_next 回边(那是循环语义,不是错) ──
    color: dict[str, int] = {}

    def walk(node_id: str, stack: list[str]) -> None:
        color[node_id] = 1
        stack.append(node_id)
        for child in _children(by_id.get(node_id, {})):
            if child not in by_id:
                continue
            if color.get(child) == 1:
                cycle = " → ".join(stack[stack.index(child):] + [child])
                errors.append(f"检测到环:{cycle}(loop 的循环请用 body_next 表达)")
            elif color.get(child, 0) == 0:
                walk(child, stack)
        color[node_id] = 2
        stack.pop()

    for node_id in ids:
        if color.get(node_id, 0) == 0:
            walk(node_id, [])

    # ── 可达性:从 start 扩散,loop 按 body_next 继承可达(迭代到不动点) ──
    if starts:
        seen: set[str] = set()
        queue = [starts[0]]
        while True:
            while queue:
                cur = queue.pop()
                if cur in seen or cur not in by_id:
                    continue
                seen.add(cur)
                queue.extend(_children(by_id[cur]))
                body = by_id[cur].get("body_next")
                if isinstance(body, str):
                    queue.append(body)
            promoted = [
                node_id for node_id in ids
                if node_id not in seen
                and by_id[node_id].get("type") == "loop"
                and isinstance(by_id[node_id].get("body_next"), str)
                and by_id[node_id]["body_next"] in seen
            ]
            if not promoted:
                break
            queue.extend(promoted)

        unreachable = [i for i in ids if i not in seen]
        if unreachable:
            inbound = {c for node in by_id.values() for c in _children(node)}
            inbound |= {
                node["body_next"] for node in by_id.values()
                if isinstance(node.get("body_next"), str)
            }
            orphans = [i for i in unreachable if i not in inbound]
            msg = f"以下节点从 start 不可达:{unreachable}"
            if orphans:
                msg += f";其中 {orphans} 没有任何节点指向它(画布上漏了连线)"
            errors.append(msg)

    return errors
