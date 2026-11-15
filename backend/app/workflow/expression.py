"""PRD 9.2 表达式沙箱:condition 的 expression 与 loop 的 exit_expression 求值。

铁律:**禁 eval / exec**,只走 ast 白名单。允许的语法面:
- `context.<field>` 属性访问(context 是 dict,支持 `.` 取值)
- 比较:`== != < <= > >= in not in is is not`(支持链式)
- 逻辑:`and or not`
- 常量:数字/字符串/布尔/None
- 算术:`+ -`(只做拼串与数值加减,够用即可)

一律拒绝:函数调用、下标、lambda、推导式、f-string、赋值。
静态校验在 `workflow/dag.py` 里做一次(保存前),运行期这里再拦一次(防绕过)。
"""
from __future__ import annotations

import ast
from typing import Any


class ExpressionError(ValueError):
    """表达式非法或求值失败。"""


def _attr(base: Any, name: str) -> Any:
    if isinstance(base, dict):
        if name not in base:
            raise ExpressionError(f"context 缺少字段 {name}")
        return base[name]
    return getattr(base, name)


def _eval(node: ast.AST, ctx: dict) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "context":
            return ctx
        if node.id in {"True", "False", "None"}:
            return {"True": True, "False": False, "None": None}[node.id]
        raise ExpressionError(f"未定义的标识符 {node.id}(只允许 context.*)")
    if isinstance(node, ast.Attribute):
        return _attr(_eval(node.value, ctx), node.attr)
    if isinstance(node, ast.BoolOp):
        values = node.values
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in values:
                result = _eval(value, ctx)
                if not result:
                    return result
            return result
        result = False
        for value in values:
            result = _eval(value, ctx)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, ctx)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise ExpressionError(f"不允许的一元运算 {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, ctx), _eval(node.right, ctx)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        raise ExpressionError(f"不允许的二元运算 {type(node.op).__name__}")
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, ctx)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            elif isinstance(op, ast.In):
                ok = left in right
            elif isinstance(op, ast.NotIn):
                ok = left not in right
            elif isinstance(op, ast.Is):
                ok = left is right
            elif isinstance(op, ast.IsNot):
                ok = left is not right
            else:
                raise ExpressionError(f"不允许的比较运算 {type(op).__name__}")
            if not ok:
                return False
            left = right
        return True
    raise ExpressionError(f"不允许的语法 {type(node).__name__}(表达式沙箱禁函数调用/下标/lambda)")


def evaluate(expr: str, context: dict) -> Any:
    """求值并返回结果;语法非法或字段缺失抛 ExpressionError。"""
    if not isinstance(expr, str) or not expr.strip():
        raise ExpressionError("表达式为空")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"表达式语法错误:{exc.msg}") from exc
    return _eval(tree.body, context)


def evaluate_bool(expr: str, context: dict) -> bool:
    return bool(evaluate(expr, context))
