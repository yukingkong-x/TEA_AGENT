"""通用问答（检索增强）：把「知识库检索」和「大模型」接成一条回答链路。

和 7 个 Agent 的区别，一句话说清：
- 7 个 Agent 是**工作流里的角色**，有绑定工具、有多轮工具循环，由引擎调度；
- 这里是**用户随口问一句**，单轮、不调工具、必须带引用，回答完就结束。

所以这块不复用 agents/base.py 的循环（那套会为了凑工具调用多跑好几轮，慢且贵），
只借它的 LLM 客户端（wiring.current_llm，设置页换 key 后自动重建）。
"""
from __future__ import annotations

import re
import time
from typing import Any

from loguru import logger

from .. import seams

# 提示词写在代码里而不是塞进 agents 表：agents 表被「对话剧场」按 7 个角色读取，
# 多插一条会在大屏上多出一个空角色。要可视化编辑人设时再单独加字段。
SYSTEM_PROMPT = """你是「茶博士」平台的茶园农艺顾问，服务对象是茶园管理者。

回答规则，逐条遵守：
1. 只回答茶园种植、灌溉、土壤、气象、病虫害、设备与平台使用相关的问题。
   与这些无关的问题（写代码、闲聊、其他行业），用一句话礼貌说明不擅长，并把话题拉回茶园。
2. 优先依据【资料】回答。用到资料时要标注引用编号，例如 [1]、[2]，编号与资料顺序一致。
3. 资料里没有直接依据、你要凭通用农艺常识补充时，必须先声明「平台资料里没有直接依据，以下是一般经验」，
   并且不要编造具体日期、数值、用药剂量。
4. 涉及剂量、阈值、用药等有风险的操作，要补一句「需现场确认后再执行」。
5. 回答简洁：先给结论，再给 2-4 条要点，总长不超过 200 字。不要用「当然可以」这类客套开场。
6. 一个正确示例：用户问「帮我写一段排序代码」，你答：「这个我帮不上，我是茶园农艺顾问。
   要问茶园的事可以直接说，比如『茶饼病怎么防治』。」——**拒绝之后不要真的把代码写出来**。
7. 只回答茶园与平台相关的问题，答案里不许出现代码块。
"""

DEGRADED_ANSWER = "模型暂不可用，下面是知识库命中的资料，可直接参考。"

# ── 数值判断护栏 ───────────────────────────────────────────────────────────
# 为什么需要它：实测 glm-4-flash 会把「45% vs 阈值 70%」判成「45% 高于 70%」，
# 而且加了"不要下结论"的规则它照样下。灌溉/用药判错是烂根、药害的代价，
# 这种结论绝不能出自一个心算不可靠的模型。所以：模型一旦越界下结论，
# 就把那段话整段换成代码算出来的确定性答复（只报事实，不拍板）。
_DECISION_WORDS = (
    "不需要浇水", "需要浇水", "不用浇水", "该浇水", "不该浇", "建议浇水",
    "不需要灌溉", "需要灌溉", "不用灌溉", "建议灌溉",
    "不需要施肥", "需要施肥", "不用施肥",
    "需要遮阳", "不需要遮阳", "要遮阳", "不用遮阳",
    "需要打药", "不需要打药", "不用打药", "建议打药",
    "高于阈值", "低于阈值", "尚未达到灌溉阈值", "已达到灌溉阈值",
)
_SENTENCE_RE = re.compile(r"[^。；\n]{0,60}?(?:低于|高于|超过|不足)\s*\d+(?:\.\d+)?\s*(?:%|度|℃)[^。；\n]{0,40}")
# 只认「带单位的数」：45% / 32度 / 30℃。裸数字（第2轮、2026年）不触发，
# 否则每句话都可能被拦，护栏会变成噪音。
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|度|℃|摄氏度)")


def _threshold_quote(hits: list[dict[str, Any]]) -> str | None:
    """从检索到的原文里抠出「…低于 70%…」这类阈值原句，只引用、不改写。"""
    for hit in hits:
        text = str(hit.get("chunk_text") or hit.get("text") or "")
        found = _SENTENCE_RE.search(text)
        if found:
            return found.group(0).strip()
    return None


def guard_numeric_decision(question: str, hits: list[dict[str, Any]], text: str | None) -> tuple[str | None, str | None]:
    """拦截「替用户拍板」的答案。返回 (可能被替换的答案, 拦截说明 or None)。

    只在这两种条件同时成立时动手：问题里带了具体数值 + 答案里出现了执行结论。
    这样「茶饼病怎么防治」这类知识问答完全不受影响。
    """
    if not text:
        return text, None
    if not _NUMBER_RE.search(question):
        return text, None
    if not any(word in text for word in _DECISION_WORDS):
        return text, None

    quote = _threshold_quote(hits)
    value = _NUMBER_RE.search(question).group(0)
    lines = ["这个问题涉及按数值拍板，问答这边不替你做决定。"]
    if quote:
        lines.append(f"资料里的判断依据：{quote}")
    lines.append(f"你给的数值：{value}")
    lines.append("是否执行请点「开始巡园」走平台流程——决策官按阈值判定，验证官复测后才算闭环。")
    return "\n".join(lines), "数值结论已拦截（改由平台决策链路判定）"


def _snippet(text: str, limit: int = 160) -> str:
    """片段截断：保留头部信息，超长加省略号。避免整段 JSON 糊在页面上。"""
    clean = " ".join(str(text or "").split())
    return clean if len(clean) <= limit else f"{clean[:limit]}…"


def citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把检索结果整理成前端能直接渲染的引用列表（编号从 1 开始，与提示词里对齐）。"""
    out: list[dict[str, Any]] = []
    for index, hit in enumerate(hits, start=1):
        if not isinstance(hit, dict):
            continue
        out.append(
            {
                "index": index,
                "title": str(hit.get("title") or "未命名资料"),
                "snippet": _snippet(hit.get("chunk_text") or hit.get("text") or ""),
                "score": hit.get("score"),
                "doc_id": hit.get("doc_id"),
            }
        )
    return out


def build_messages(question: str, hits: list[dict[str, Any]]) -> list[dict[str, str]]:
    """拼单轮对话：系统人设 + 一份带编号的资料 + 用户问题。"""
    if hits:
        blocks = []
        for index, hit in enumerate(hits, start=1):
            title = hit.get("title") or "未命名资料"
            body = " ".join(str(hit.get("chunk_text") or hit.get("text") or "").split())
            blocks.append(f"[{index}]《{title}》：{body}")
        material = "\n".join(blocks)
    else:
        material = "（本次未检索到相关资料）"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"【资料】\n{material}\n\n【问题】{question}"},
    ]


def _retrieve(question: str, top_k: int) -> tuple[list[dict[str, Any]], str | None]:
    """检索失败不当错误抛出：知识库没就绪时照样让模型用通用知识答，只是标记出来。"""
    try:
        hits = seams.search(question=question, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 SeamNotReady / Chroma 连接失败都走这里
        logger.warning("问答检索失败，降级为无资料回答：{}", exc)
        return [], f"知识库检索不可用（{type(exc).__name__}）"
    if not isinstance(hits, list):
        return [], "知识库检索返回了非列表结果"
    return [h for h in hits if isinstance(h, dict)], None


async def answer(question: str, top_k: int = 3, llm: Any = None) -> dict[str, Any]:
    """一条问答的完整链路：检索 → 拼提示词 → 单轮生成 → 整理引用。

    llm 可注入（单测用）。正常路径下取 wiring.current_llm()。
    任何一步失败都返回 degraded=True 的结构，不抛给 HTTP 层——问答挂掉不该变成 500。
    """
    started = time.perf_counter()
    text = " ".join(str(question or "").split())
    if not text:
        return {
            "question": "",
            "answer": None,
            "citations": [],
            "degraded": True,
            "reason": "问题为空",
            "provider": None,
            "latency_ms": 0,
            "retrieved": 0,
        }

    hits, retrieve_note = _retrieve(text, top_k)
    refs = citations(hits)

    if llm is None:
        from ..workflow.wiring import current_llm

        llm = current_llm()

    reason = retrieve_note
    answer_text: str | None = None
    provider: str | None = None
    try:
        result = await llm.complete(build_messages(text, hits), temperature=0.2, max_tokens=800)
    except Exception as exc:  # noqa: BLE001 网络/鉴权/超时都在这里收口
        logger.warning("问答调用模型失败：{}: {}", type(exc).__name__, exc)
        result = None
        reason = f"模型调用失败（{type(exc).__name__}）"

    degraded = False
    if result is None:
        degraded = True
    elif getattr(result, "degraded", False):
        degraded = True
        reason = getattr(result, "error", None) or "模型处于降级状态（未配置 Key 或被限流）"
    else:
        answer_text = (getattr(result, "content", None) or "").strip() or None
        provider = getattr(result, "provider", None)
        if answer_text is None:
            degraded = True
            reason = reason or "模型返回了空内容"

    if degraded and refs:
        answer_text = answer_text or DEGRADED_ANSWER
    elif degraded and not refs:
        answer_text = answer_text or "模型暂不可用，知识库也没有命中相关资料，请稍后再试。"

    # 最后一道闸：模型如果不听劝、还是对数值下了执行结论，这里把它换掉。
    answer_text, guard_note = guard_numeric_decision(text, hits, answer_text)
    if guard_note:
        logger.info("问答触发数值护栏：{}", guard_note)

    return {
        "question": text,
        "answer": answer_text,
        "citations": refs,
        "degraded": degraded,
        "reason": reason,
        "guarded": guard_note is not None,
        "provider": provider,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "retrieved": len(refs),
    }
