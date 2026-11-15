"""`_emit` 的载荷装配:引擎发扁平结构,只有基座信封才包 `{"type","data"}`。

这里守的是一个**不报错但功能全哑**的 bug:取 `event.get("data")` 永远拿不到东西,
WS 载荷变成 `{}`、`agent_messages` 一行不落,而日志里干干净净。
"""
import sys
import types

import pytest

from app.workflow import wiring


class FakeManager:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    def publish_threadsafe(self, msg_type, data) -> None:
        self.sent.append((msg_type, data))


@pytest.fixture
def fake_ws(monkeypatch):
    manager = FakeManager()
    module = types.ModuleType("app.core.ws_manager")
    module.manager = manager            # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.ws_manager", module)
    return manager


def test_flat_event_fields_become_data_payload(fake_ws):
    wiring._emit({"type": "run_status", "run_id": 7, "status": "running",
                  "wf_key": "patrol_irrigation", "ts": 1700000000000})

    msg_type, data = fake_ws.sent[0]
    assert msg_type == "run_status"
    assert data == {"run_id": 7, "status": "running", "wf_key": "patrol_irrigation"}
    # 毫秒 ts 不进 data:基座 _envelope 会在顶层给秒级 ts,同名不同量纲前端必混
    assert "ts" not in data and "type" not in data


def test_nested_data_still_supported(fake_ws):
    """将来引擎若改成 {"type","data"} 嵌套,这里不用跟着改。"""
    wiring._emit({"type": "node_state", "data": {"node_id": "n2", "state": "started"}})
    assert fake_ws.sent[0] == ("node_state", {"node_id": "n2", "state": "started"})


def test_agent_message_persisted_only_on_finished(monkeypatch, fake_ws):
    calls: list[dict] = []
    monkeypatch.setattr(wiring, "_persist_agent_message", lambda data: calls.append(data))

    # started 不能落库,否则每轮发言会写两行
    wiring._emit({"type": "node_state", "state": "started", "agent_key": "scout", "run_id": 1})
    assert calls == []

    wiring._emit({"type": "node_state", "state": "finished", "agent_key": "scout",
                  "run_id": 1, "output": "【巡园播报】A 区正常", "tool_calls": [],
                  "tokens_in": 11, "tokens_out": 3})
    assert len(calls) == 1
    assert calls[0]["agent_key"] == "scout"
    assert calls[0]["tokens_in"] == 11


def test_non_agent_node_never_persists(monkeypatch, fake_ws):
    calls: list[dict] = []
    monkeypatch.setattr(wiring, "_persist_agent_message", lambda data: calls.append(data))
    wiring._emit({"type": "node_state", "state": "finished", "node_id": "n10",
                  "node_type": "tool", "agent_key": None, "run_id": 1})
    assert calls == []


def test_citations_extract_doc_ids_from_query_knowledge():
    tool_calls = [
        {"name": "query_knowledge",
         "result": [{"doc_id": 2, "chunk_index": 0}, {"doc_id": 2, "chunk_index": 3},
                    {"doc_id": 5, "chunk_index": 1}]},
        {"name": "read_sensor", "result": {"doc_id": 9}},     # 非知识库工具不认
    ]
    # 同文档多块只算一次引用,顺序按命中顺序
    assert wiring._citations_of(tool_calls) == [2, 5]


def test_citations_accepts_json_string_and_hits_wrapper():
    """LLM 的工具返回常被序列化成字符串,别在这里丢掉引用脚标。"""
    assert wiring._citations_of(
        [{"name": "query_knowledge", "result": '{"hits": [{"doc_id": 3}]}'}]
    ) == [3]


def test_citations_ignores_garbage():
    assert wiring._citations_of([]) == []
    assert wiring._citations_of([None, "x", {"name": "query_knowledge", "result": None}]) == []
