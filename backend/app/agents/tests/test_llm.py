"""REQ-F-001 LLM 接入层单元测试(PRD 7.2 + 20.2)。

被测契约:
- OpenAI 兼容调用,主备 provider 按序尝试,超时/失败自动切备用;
- 连续 2 次失败进入规则降级(结果带 degraded 标记),恢复后自动切回;
- 每次调用回报 tokens 与耗时(on_usage 回调);
- 工具调用参数解析,畸形 JSON 保留原文不崩。
"""
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from app.core.llm import LLMClient, ProviderConfig, build_client_from_env

GLM = ProviderConfig("glm", "http://glm.test/v4", "glm-key", "glm-4-flash")
DEEPSEEK = ProviderConfig("deepseek", "https://api.deepseek.test", "ds-key", "deepseek-chat")


def _response(content=None, tool_calls=None, tokens_in=10, tokens_out=5):
    """镜像 openai SDK ChatCompletion 的完整结构(只含被测代码读取的字段)。"""
    return SimpleNamespace(
        id="chatcmpl-test",
        model="glm-4-flash",
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(
            prompt_tokens=tokens_in,
            completion_tokens=tokens_out,
            total_tokens=tokens_in + tokens_out,
        ),
    )


def _tool_call(tid="call-1", name="get_weather", arguments='{"city": "杭州"}'):
    return SimpleNamespace(
        id=tid,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _conn_error(url="http://glm.test/v4"):
    return APIConnectionError(request=httpx.Request("POST", url))


def _timeout_error():
    return APITimeoutError(request=httpx.Request("POST", "http://glm.test/v4"))


class FakeOpenAI:
    """double for openai.AsyncOpenAI —— 仅模拟 chat.completions.create。

    behavior: BaseException 表示该 provider 调用即失败;
              可调用对象表示成功,返回 _response() 构造的响应。
    """

    def __init__(self, behavior):
        self._behavior = behavior
        self.create_calls = 0

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.create_calls += 1
        if isinstance(self._behavior, BaseException):
            raise self._behavior
        return self._behavior()


def _client(providers, behaviors, on_usage=None, probe_interval=30.0):
    """按 provider.name 分发 FakeOpenAI 的工厂式构造。"""
    fakes = {p.name: FakeOpenAI(behaviors[p.name]) for p in providers}
    return LLMClient(
        providers=providers,
        client_factory=lambda p: fakes[p.name],
        on_usage=on_usage,
        probe_interval=probe_interval,
    ), fakes


@pytest.mark.asyncio
async def test_complete_returns_content_and_reports_usage():
    # 断点:成功路径的 content/usage 解析被删改(如不读 usage、不回调 on_usage)→ 本测试失败
    usage = []
    client, _ = _client(
        [GLM],
        {"glm": lambda: _response(content="播报内容", tokens_in=12, tokens_out=7)},
        on_usage=lambda provider, tin, tout, latency: usage.append((provider, tin, tout, latency)),
    )

    result = await client.complete([{"role": "user", "content": "hi"}])

    assert result.content == "播报内容"
    assert result.tokens_in == 12
    assert result.tokens_out == 7
    assert result.latency_ms >= 0
    assert result.degraded is False
    assert result.provider == "glm"
    assert len(usage) == 1 and usage[0][:3] == ("glm", 12, 7)


@pytest.mark.asyncio
async def test_primary_failure_falls_back_to_backup_provider():
    # 断点:主 provider 失败后不做备用切换(直接失败/抛出)→ 本测试失败
    client, fakes = _client(
        [GLM, DEEPSEEK],
        {"glm": _conn_error(), "deepseek": lambda: _response(content="备用回答")},
    )

    result = await client.complete([{"role": "user", "content": "hi"}])

    assert result.content == "备用回答"
    assert result.provider == "deepseek"
    assert result.degraded is False
    assert fakes["glm"].create_calls == 1
    assert fakes["deepseek"].create_calls == 1


@pytest.mark.asyncio
async def test_timeout_on_primary_uses_backup_provider():
    # 断点:主 provider 超时不视为失败(不切换)→ 本测试失败
    client, fakes = _client(
        [GLM, DEEPSEEK],
        {"glm": _timeout_error(), "deepseek": lambda: _response(content="超时切换成功")},
    )

    result = await client.complete([{"role": "user", "content": "hi"}])

    assert result.content == "超时切换成功"
    assert result.provider == "deepseek"
    assert fakes["glm"].create_calls == 1


@pytest.mark.asyncio
async def test_two_consecutive_failures_enter_degraded_mode():
    # 断点:降级阈值逻辑被改(第 1 次失败就降级,或永远不降级)→ 本测试失败
    client, _ = _client([GLM], {"glm": _conn_error()})

    first = await client.complete([{"role": "user", "content": "hi"}])
    assert first.degraded is False
    assert first.content is None
    assert first.error  # 失败原因透出,供上层记录
    assert client.consecutive_failures == 1

    second = await client.complete([{"role": "user", "content": "hi"}])
    assert second.degraded is True
    assert client.degraded is True


@pytest.mark.asyncio
async def test_degraded_mode_short_circuits_within_probe_interval():
    # 断点:降级期间仍真打 LLM(短路逻辑缺失)→ create_calls 不为 0,本测试失败
    client, fakes = _client([GLM], {"glm": _conn_error()})
    await client.complete([{"role": "user", "content": "a"}])
    await client.complete([{"role": "user", "content": "b"}])
    assert client.degraded is True
    fakes["glm"].create_calls = 0

    result = await client.complete([{"role": "user", "content": "c"}])

    assert result.degraded is True
    assert result.content is None
    assert fakes["glm"].create_calls == 0  # 探测窗口内不发起真实调用


@pytest.mark.asyncio
async def test_probe_recovers_from_degraded_mode():
    # 断点:降级后永远不恢复(探测成功也不切回)→ 本测试失败
    fake = FakeOpenAI(_conn_error())
    client = LLMClient(
        providers=[GLM],
        client_factory=lambda p: fake,
        probe_interval=0,  # 每次调用都视为一次探测
    )
    await client.complete([{"role": "user", "content": "a"}])
    await client.complete([{"role": "user", "content": "b"}])
    assert client.degraded is True

    fake._behavior = lambda: _response(content="网络恢复,真实回答")
    result = await client.complete([{"role": "user", "content": "c"}])

    assert result.content == "网络恢复,真实回答"
    assert result.degraded is False
    assert client.degraded is False  # 自动切回
    assert client.consecutive_failures == 0


@pytest.mark.asyncio
async def test_tool_calls_are_parsed_into_structured_dicts():
    # 断点:tool_calls 解析被删(不返回结构化工具调用)→ 本测试失败
    client, _ = _client(
        [GLM],
        {"glm": lambda: _response(content=None, tool_calls=[_tool_call()])},
    )

    result = await client.complete([{"role": "user", "content": "天气?"}])

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.id == "call-1"
    assert tc.name == "get_weather"
    assert tc.arguments == {"city": "杭州"}


@pytest.mark.asyncio
async def test_malformed_tool_arguments_are_kept_raw_not_crashing():
    # 断点:畸形 JSON 导致解析崩溃(没有兜底)→ 本测试失败
    client, _ = _client(
        [GLM],
        {"glm": lambda: _response(content=None, tool_calls=[_tool_call(arguments="not-json")])},
    )

    result = await client.complete([{"role": "user", "content": "天气?"}])

    tc = result.tool_calls[0]
    assert tc.name == "get_weather"
    assert tc.arguments is None
    assert tc.arguments_raw == "not-json"


def test_build_client_from_env_selects_provider_order():
    # 断点:env 键名/provider 顺序与 PRD 21.1 不一致 → 本测试失败
    client = build_client_from_env(
        {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "ds", "GLM_API_KEY": "glm"}
    )
    assert [p.name for p in client.providers] == ["deepseek", "glm"]
    assert client.providers[0].base_url == "https://api.deepseek.com"
    assert client.providers[0].model == "deepseek-chat"

    client2 = build_client_from_env({"LLM_PROVIDER": "glm", "GLM_API_KEY": "glm"})
    assert [p.name for p in client2.providers] == ["glm", "deepseek"]
    assert client2.providers[0].base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert client2.providers[0].model == "glm-4-flash"
