"""REQ-F-001 LLM 接入层(PRD 7.2 + 20.2)。

OpenAI 兼容统一接入:GLM-4-Flash(主)+ DeepSeek-chat(备)。
- 超时 60s;单次调用失败自动重试 1 次(换备用 provider);
- 连续 2 次调用失败 → 进入规则降级(degraded),上层(AgentRunner)改用规则模板输出,
  并在对话剧场标注「⚠️ 模型降级中」;降级期间按 probe_interval 探测,成功即自动切回;
- 每次成功调用通过 on_usage 回调上报 tokens 与耗时(由上层落库 agent_messages)。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from loguru import logger
from openai import AsyncOpenAI

GLM_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
GLM_DEFAULT_MODEL = "glm-4-flash"
DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Optional[dict] = None
    arguments_raw: str = ""


@dataclass
class LLMResult:
    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    degraded: bool = False
    provider: Optional[str] = None
    error: Optional[str] = None


class LLMClient:
    """主备双 provider 的 OpenAI 兼容客户端,带降级与自动恢复。"""

    def __init__(
        self,
        providers: list[ProviderConfig],
        on_usage: Optional[Callable[[str, int, int, int], Any]] = None,
        timeout: float = 60.0,
        probe_interval: float = 30.0,
        client_factory: Optional[Callable[[ProviderConfig], Any]] = None,
        max_concurrency: int = 2,
        rate_limit_retries: int = 2,
        retry_base: float = 1.5,
    ):
        if not providers:
            raise ValueError("至少配置一个 provider")
        self.providers = list(providers)
        self.on_usage = on_usage
        self.timeout = timeout
        self.probe_interval = probe_interval
        # 并发闸门：parallel 节点会让三路 Agent 同时打同一个免费档 key，限到 2 之后
        # 429 基本消失（实测 4 次 run 里 3 次是并发打爆，不是单次调用超限）。
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self.rate_limit_retries = max(0, rate_limit_retries)
        self.retry_base = retry_base
        factory = client_factory or self._default_factory
        self._client_factory = factory
        # 惰性构造:备用 provider 未配 key 时不影响启动,真正尝试它时才报错并走降级链路
        self._clients: dict[str, Any] = {}
        self.consecutive_failures = 0
        self._degraded = False
        self._last_probe_ts = 0.0

    def _client_for(self, provider: ProviderConfig):
        client = self._clients.get(provider.name)
        if client is None:
            client = self._client_factory(provider)
            self._clients[provider.name] = client
        return client

    def _default_factory(self, provider: ProviderConfig):
        return AsyncOpenAI(
            base_url=provider.base_url,
            api_key=provider.api_key,
            timeout=self.timeout,
            max_retries=0,  # 重试由本层统一管理,不让 SDK 悄悄重试
        )

    @property
    def degraded(self) -> bool:
        return self._degraded

    async def complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        tool_choice: Optional[Any] = None,
    ) -> LLMResult:
        """tool_choice 透传给 provider（PRD 8.3「必须真的调工具」的落地手段）。

        为什么需要它：GLM-4-Flash 这类小模型会「只在文本里描述工具调用」——实测决策官
        输出了完整的 create_task 参数说明，却一个 tool_call 都没发，任务从未创建，
        执行管家拿不到 task_no，整条闭环断在决策→执行之间，而工作流状态仍显示 success。
        小模型对提示词里的「必须调用工具」并不可靠，把 choice 钉到具体函数才收得住。
        只传 OpenAI 兼容的标准写法（{"type": "function", "function": {"name": ...}}），
        不用 "required"——部分兼容实现不认这个枚举值，会直接 400。
        """
        if self._degraded and (time.monotonic() - self._last_probe_ts) < self.probe_interval:
            return LLMResult(degraded=True, error="模型降级中,等待探测窗口")
        start = time.perf_counter()
        errors: list[str] = []
        for provider in self.providers:
            try:
                kwargs: dict[str, Any] = {
                    "model": provider.model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if tools:
                    kwargs["tools"] = tools
                if tools and tool_choice is not None:
                    kwargs["tool_choice"] = tool_choice
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                resp = await self._create_with_retry(provider, kwargs)
                message = resp.choices[0].message
                result = LLMResult(
                    content=message.content,
                    tool_calls=self._parse_tool_calls(message.tool_calls),
                    tokens_in=resp.usage.prompt_tokens if resp.usage else 0,
                    tokens_out=resp.usage.completion_tokens if resp.usage else 0,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    provider=provider.name,
                )
                self.consecutive_failures = 0
                self._degraded = False  # 恢复后自动切回
                self._last_probe_ts = 0.0
                if self.on_usage:
                    self.on_usage(provider.name, result.tokens_in, result.tokens_out, result.latency_ms)
                return result
            except Exception as exc:  # noqa: BLE001 接入层统一兜底,交给降级逻辑
                errors.append(f"{provider.name}: {exc}")
        self.consecutive_failures += 1
        if self.consecutive_failures >= 2:
            self._degraded = True
            self._last_probe_ts = time.monotonic()
        return LLMResult(degraded=self._degraded, error="; ".join(errors))

    @staticmethod
    def _is_rate_limited(exc: Exception) -> bool:
        """只认限流（429），不认超时/连接错误。

        为什么只重试限流：超时是「这个 provider 不行了」，应该立刻换备用 provider；
        限流是「你打太快了」，换 provider 也没意义，等一会儿同一个 provider 就能过。
        混在一起重试会把 60s 的超时等待放大三倍，工作流节点直接卡穿。
        """
        status = getattr(exc, "status_code", None)
        if status == 429:
            return True
        text = str(exc).lower()
        return "429" in text or "rate limit" in text or "too many requests" in text

    async def _create_with_retry(self, provider: ProviderConfig, kwargs: dict) -> Any:
        """带并发闸门与限流退避的单次调用。

        实测（2026-11-14 12:20 连续 4 次 run）：glm-4-flash 免费档在
        parallel 节点三路并发 + 连续触发时返回 429，`complete` 把它当 provider 失败，
        两次之后整客户端进入 degraded，六个 Agent 全部走规则模板 —— 画面上看着像
        「模型能力不行」，实际只是自己把免费额度打爆了。赛题演示前手抖点多两次
        「执行」就会复现，所以限流必须是可重试的，并且要在源头上限并发。
        """
        last: Optional[Exception] = None
        for attempt in range(self.rate_limit_retries + 1):
            try:
                async with self._semaphore:
                    return await self._client_for(provider).chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt >= self.rate_limit_retries or not self._is_rate_limited(exc):
                    raise
                wait = self.retry_base * (2 ** attempt)
                logger.warning(
                    "{} 限流（第 {}/{} 次），{:.1f}s 后重试：{}",
                    provider.name, attempt + 1, self.rate_limit_retries, wait, exc,
                )
                await asyncio.sleep(wait)
        raise last if last is not None else RuntimeError("LLM 调用失败")

    @staticmethod
    def _parse_tool_calls(raw) -> list[ToolCall]:
        if not raw:
            return []
        calls = []
        for tc in raw:
            try:
                arguments = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, AttributeError, TypeError):
                arguments = None
            calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                    arguments_raw=tc.function.arguments,
                )
            )
        return calls


def build_client_from_env(
    env: Optional[dict] = None,
    on_usage: Optional[Callable[[str, int, int, int], Any]] = None,
) -> LLMClient:
    """从环境变量构建客户端(键名对齐 PRD 21.1 .env.example)。"""
    env = env if env is not None else os.environ
    provider = (env.get("LLM_PROVIDER") or "glm").lower()
    glm = ProviderConfig(
        name="glm",
        base_url=env.get("GLM_BASE_URL", GLM_DEFAULT_BASE_URL),
        api_key=env.get("GLM_API_KEY", ""),
        model=env.get("GLM_MODEL", GLM_DEFAULT_MODEL),
    )
    deepseek = ProviderConfig(
        name="deepseek",
        base_url=env.get("DEEPSEEK_BASE_URL", DEEPSEEK_DEFAULT_BASE_URL),
        api_key=env.get("DEEPSEEK_API_KEY", ""),
        model=env.get("DEEPSEEK_MODEL", DEEPSEEK_DEFAULT_MODEL),
    )
    ordered = [glm, deepseek] if provider != "deepseek" else [deepseek, glm]
    return LLMClient(providers=ordered, on_usage=on_usage)
