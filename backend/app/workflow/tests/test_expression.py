"""PRD 9.2 表达式沙箱单测:只允许 context.* + 比较/逻辑,函数调用与下标必须拒绝。"""
import pytest

from app.workflow.expression import ExpressionError, evaluate, evaluate_bool


def test_prd_examples():
    ctx = {"last_decision": "irrigate", "round": 2, "last_verification": "success"}
    assert evaluate_bool("context.last_decision == 'irrigate'", ctx) is True
    assert evaluate_bool("context.last_decision == 'none'", ctx) is False
    assert evaluate_bool("context.last_verification == 'success' or context.round > 2", ctx) is True
    assert evaluate_bool("context.round > 2", {"round": 1}) is False


def test_logic_and_compare_chain():
    ctx = {"a": 1, "b": 5, "c": 9, "tags": "pest,weather", "last_decision": "none"}
    assert evaluate_bool("context.a < context.b < context.c", ctx) is True
    assert evaluate_bool("not context.a > 10", ctx) is True
    assert evaluate_bool("'pest' in context.tags and context.last_decision == 'none'", ctx) is True
    assert evaluate_bool("'soil' not in context.tags", ctx) is True


def test_missing_field_is_explicit():
    with pytest.raises(ExpressionError, match="缺少字段"):
        evaluate_bool("context.nope == 1", {"round": 1})


def test_function_call_rejected():
    with pytest.raises(ExpressionError):
        evaluate("__import__('os').system('echo hi')", {})


def test_subscript_rejected():
    with pytest.raises(ExpressionError):
        evaluate("context['round'] > 1", {"round": 2})


def test_lambda_rejected():
    with pytest.raises(ExpressionError):
        evaluate("(lambda: 1)()", {})


def test_dunder_attribute_denied_by_missing_key():
    # 属性链只走 dict 取值,不会穿透到对象内部
    with pytest.raises(ExpressionError):
        evaluate("context.__class__", {"round": 1})


def test_syntax_error_message():
    with pytest.raises(ExpressionError, match="语法错误"):
        evaluate("context.round ==", {"round": 1})


def test_empty_expression():
    with pytest.raises(ExpressionError, match="为空"):
        evaluate("   ", {})
