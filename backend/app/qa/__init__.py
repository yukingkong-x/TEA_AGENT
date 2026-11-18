"""通用问答模块（用户自由提问 → 检索增强 → 模型回答）。

与 agents/ 并列而不是塞进 agents/：那边是工作流角色，这边是给人用的对话框。
"""
from .answering import SYSTEM_PROMPT, answer, build_messages, citations

__all__ = ["SYSTEM_PROMPT", "answer", "build_messages", "citations"]
