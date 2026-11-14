"""工作流引擎接线：把 `EngineDeps` 接到基座的库与 WS（B 在 bootstrap 里加两行）。

```python
from .workflow.wiring import install as install_workflow
# start_all() 里
install_workflow()
```

不接的话 `start_run` 会抛 `SeamNotReady` → 路由 503（这是设计好的：宁可不跑，不跑假的）。

顺带补一个没人认领的缺口：**Agent 发言落库**。引擎发 `node_state`(state=finished) 事件，
但 PRD 6.7 的对话剧场要的是 `agent_messages` 表 + `agent_message` WS 消息，所以这里
在 emit 里把 agent 节点的产出同时落一行表、推一条消息；`tool_calls_json` 与
`citations_json` 也从事件里带上（引擎负责搬运 turn 的明细，这里负责解析与落库）。
"""
from __future__ import annotations

import json

import importlib
import os
import threading
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from app.workflow.engine import EngineDeps, configure, is_ready

_llm: Any = None
_llm_signature: Optional[tuple] = None
_lock = threading.Lock()

_MESSAGE_MAX_CHARS = 20000


# ─────────────────────────── LLM ───────────────────────────

def _providers() -> list[dict[str, str]]:
    """主备两套 provider。优先级：settings 表 > 环境变量 > 代码默认。"""
    from app.core.llm import (
        DEEPSEEK_DEFAULT_BASE_URL, DEEPSEEK_DEFAULT_MODEL,
        GLM_DEFAULT_BASE_URL, GLM_DEFAULT_MODEL,
    )
    from app.core.runtime_settings import get_secret, get_value

    primary = str(get_value("llm_provider", os.getenv("LLM_PROVIDER", "glm")) or "glm").lower()
    if primary not in {"glm", "deepseek"}:
        logger.warning("未知的 llm_provider={}，按 glm 处理", primary)

    glm_key = get_secret("llm_api_key") if primary == "glm" else os.getenv("GLM_API_KEY", "")
    deepseek_key = get_secret("llm_api_key") if primary == "deepseek" else os.getenv("DEEPSEEK_API_KEY", "")

    glm = {
        "name": "glm",
        "base_url": os.getenv("GLM_BASE_URL", GLM_DEFAULT_BASE_URL),
        "api_key": glm_key or "",
        "model": os.getenv("GLM_MODEL", GLM_DEFAULT_MODEL),
    }
    deepseek = {
        "name": "deepseek",
        "base_url": os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_DEFAULT_BASE_URL),
        "api_key": deepseek_key or "",
        "model": os.getenv("DEEPSEEK_MODEL", DEEPSEEK_DEFAULT_MODEL),
    }
    return [glm, deepseek] if primary != "deepseek" else [deepseek, glm]


def current_llm() -> Any:
    """全局 LLM 客户端。设置页改 key/供应商后，下一次取用自动重建（不用重启）。"""
    global _llm, _llm_signature
    from app.core.llm import LLMClient, ProviderConfig

    providers = _providers()
    signature = tuple((p["name"], p["base_url"], p["api_key"], p["model"]) for p in providers)
    with _lock:
        if _llm is None or signature != _llm_signature:
            _llm = LLMClient([ProviderConfig(**p) for p in providers])
            _llm_signature = signature
            logger.info("LLM 客户端就绪（主 {}，备 {}，主 key {}）",
                        providers[0]["name"], providers[1]["name"],
                        "已配置" if providers[0]["api_key"] else "未配置→将走降级")
        return _llm


# ─────────────────────────── Agent 工厂 ───────────────────────────

def _agent_factory(agent_key: str) -> Any:
    """`agent_key` → runner。约定每个 Agent 一个模块，模块内 `build_runner(llm, registry)`。"""
    from app.core.tool_impl import get_registry

    if not agent_key:
        raise ValueError("工作流 agent 节点缺少 agent_key")
    try:
        module = importlib.import_module(f"app.agents.runner_{agent_key}")
    except ModuleNotFoundError as exc:
        raise ValueError(f"未知 agent_key：{agent_key}（没有 app/agents/runner_{agent_key}.py）") from exc
    return module.build_runner(current_llm(), get_registry())


def _tool_invoke(name: str, params: dict) -> Any:
    from app.core.tool_impl import get_registry

    return get_registry().invoke(name, params or {})


# ─────────────────────────── 库适配 ───────────────────────────

def _load_workflow(wf_id: int) -> dict:
    from app.db import session_scope
    from app.models.workflows import Workflow

    with session_scope() as db:
        row = db.get(Workflow, wf_id)
        if row is None:
            raise LookupError(f"工作流 {wf_id} 不存在")
        dag = dict(row.dag_json or {})
        dag.update({"wf_id": row.id, "wf_key": row.wf_key, "name": row.name})
        return dag


def _create_run(wf_id: int, trigger: str) -> int:
    from app.db import session_scope
    from app.models.workflow_runs import WorkflowRun

    with session_scope() as db:
        run = WorkflowRun(wf_id=wf_id, status="running", trigger=trigger,
                          started_at=datetime.now(), context_json={})
        db.add(run)
        db.flush()
        return int(run.id)


def _update_run(run_id: int, status: str, context: dict, error: Optional[str]) -> None:
    from app.db import session_scope
    from app.models.workflow_runs import WorkflowRun

    with session_scope() as db:
        run = db.get(WorkflowRun, run_id)
        if run is None:
            logger.warning("run {} 不存在，状态回写丢弃", run_id)
            return
        run.status = status
        payload = dict(context or {})
        if error:
            payload["error"] = error
        run.context_json = payload
        run.finished_at = datetime.now()


# ─────────────────────────── WS / 对话剧场 ───────────────────────────

# 事件里属于「信封」的键：不放进 data 载荷。
# `ts` 尤其要排除——引擎塞的是毫秒时间戳，基座 _envelope 会顶层再给一个秒级 ts，
# 两个同名字段量纲不同，前端一定会混。
_ENVELOPE_KEYS = frozenset({"type", "ts"})

_WS_TYPES = frozenset({"run_status", "node_state", "agent_message"})


def _emit(event: dict) -> None:
    """引擎事件 → WS 广播 + Agent 发言落库。

    引擎发的是**扁平**结构（字段与 type 同级）；基座的 `_envelope` 才负责包
    `{type, data, ts}`。所以这里要把除信封外的所有字段收进 data，不能找 `data` 键
    ——找它永远是 `{}`，`node_state` 的载荷会全空，`agent_messages` 也一行都落不下来。
    """
    from app.core.ws_manager import manager

    msg_type = event.get("type")
    data = event.get("data")
    if not isinstance(data, dict):
        data = {k: v for k, v in event.items() if k not in _ENVELOPE_KEYS}
    if msg_type not in _WS_TYPES:      # pragma: no cover 白名单外的类型不该出现在这条链上
        logger.warning("工作流事件类型 {} 不在 WS 白名单内，请检查 _fire 的映射", msg_type)

    manager.publish_threadsafe(msg_type, data)

    if msg_type == "node_state" and data.get("state") == "finished" and data.get("agent_key"):
        _persist_agent_message(data)


def _citations_of(tool_calls: list[dict]) -> list[int]:
    """从工具调用里抽出被引用的知识库 doc_id（对话剧场引用脚标的落库源）。

    只认 `query_knowledge`，且只取返回值里的 `doc_id`——`chunk_index` 不进库，
    前端按返回顺序重新编号（见数据契约第 8 节）。
    """
    doc_ids: list[int] = []
    for call in tool_calls or []:
        if not isinstance(call, dict) or call.get("name") != "query_knowledge":
            continue
        payload = call.get("result") if "result" in call else call.get("output")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                continue
        if isinstance(payload, dict):
            payload = payload.get("hits") or payload.get("results") or []
        if not isinstance(payload, list):
            continue
        for hit in payload:
            if isinstance(hit, dict) and hit.get("doc_id") is not None:
                doc_id = int(hit["doc_id"])
                if doc_id not in doc_ids:
                    doc_ids.append(doc_id)
    return doc_ids


def _persist_agent_message(data: dict) -> None:
    """agent 节点产出 → agent_messages 一行 + 一条 agent_message 推送。"""
    from app.core.ws_manager import manager
    from app.db import session_scope
    from app.models.agent_messages import AgentMessage

    tool_calls = [c for c in (data.get("tool_calls") or []) if isinstance(c, dict)]
    citations = _citations_of(tool_calls)
    try:
        with session_scope() as db:
            message = AgentMessage(
                run_id=data.get("run_id"),
                agent_key=str(data["agent_key"]),
                role="assistant",
                content=(data.get("output") or "")[:_MESSAGE_MAX_CHARS] or None,
                tool_calls_json=tool_calls or None,
                citations_json=citations or None,
                tokens_in=int(data.get("tokens_in") or 0),
                tokens_out=int(data.get("tokens_out") or 0),
                latency_ms=int(data.get("duration_ms") or 0),
            )
            db.add(message)
            db.flush()
            message_id = int(message.id)

        manager.publish_threadsafe("agent_message", {
            "id": message_id,
            "run_id": data.get("run_id"),
            "agent_key": data.get("agent_key"),
            "role": "assistant",
            "content": data.get("output") or "",
            "degraded": bool(data.get("degraded")),
            "latency_ms": int(data.get("duration_ms") or 0),
            "tool_calls": tool_calls,
            "citations": citations,
            "ts": data.get("ts") or datetime.now().isoformat(),
        })
    except Exception as exc:  # noqa: BLE001 落库失败不能中断工作流
        logger.warning("Agent 发言落库失败（run={} agent={}）：{}",
                       data.get("run_id"), data.get("agent_key"), exc)


# ─────────────────────────── 安装 ───────────────────────────

def build_deps() -> EngineDeps:
    return EngineDeps(
        load_workflow=_load_workflow,
        create_run=_create_run,
        update_run=_update_run,
        agent_runner_factory=_agent_factory,
        tool_invoke=_tool_invoke,
        emit=_emit,
    )


def install() -> bool:
    """幂等安装。失败只记日志不抛——调度起不来也不能让 API 起不来。"""
    if is_ready():
        return True
    try:
        configure(build_deps())
        logger.info("工作流引擎已接线（load_workflow / create_run / update_run / agent / tool / emit）")
    except Exception as exc:  # noqa: BLE001
        logger.exception("工作流引擎接线失败，start_run 将返回 503：{}", exc)
        return False

    # 空库首启：PRD 9.1 要求默认工作流写入 workflows 表，基座 seed 没有建，这里补
    try:
        from app.workflow.default_dag import ensure_default_workflow

        ensure_default_workflow()
    except Exception as exc:  # noqa: BLE001
        logger.warning("默认工作流写入失败（画布仍可手工保存一份）：{}", exc)
    return True
