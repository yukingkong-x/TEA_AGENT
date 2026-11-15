"""切片（PRD 7.4 的“切片入库”环节）。

三条规则：
1. **先按段落，再按句子**——农艺条文几乎都是“一、土壤湿度…。二、…”的条目式，
   按固定字数硬切会把“低于 55% 应灌溉”和它的条件“沙壤土”切到两个块里，
   检索出来就是断章取义。
2. **块长有硬上限**，且上限把 overlap 也算进去——否则“每块 ≤ 480 字”这句话
   在实现里就成了谎话。
3. **不产生尾巴块**——最后一段不足 40 字时并进上一块，避免出现
   「三、」这种没有内容的碎片污染 top-k。
"""
from __future__ import annotations

import re

DEFAULT_MAX_CHARS = 480
DEFAULT_OVERLAP = 80
MIN_CHUNK_CHARS = 40       # 低于此长度的尾巴并入上一块
HARD_MIN_MAX = 80          # max_chars 的合理下限

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SplitError(ValueError):
    pass


def clean(text: str) -> str:
    """去控制字符、压缩空白；单换行视为软换行（PDF 每行一个 \\n），双换行才是段落。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CTRL.sub("", text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    # 行尾空格丢掉；连续空行压成一个空行
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def paragraphs(text: str) -> list[str]:
    """按空行切段；段内的单换行拼回一行（PDF 换行不是语义边界）。"""
    out: list[str] = []
    for block in _PARAGRAPH_SPLIT.split(clean(text)):
        merged = " ".join(part.strip() for part in block.split("\n") if part.strip())
        if merged:
            out.append(merged)
    return out


def sentences(paragraph: str) -> list[str]:
    """按中文句末标点切句，标点跟着前一句走。"""
    return [s.strip() for s in _SENTENCE_SPLIT.split(paragraph) if s.strip()]


def _hard_cut(sentence: str, max_chars: int) -> list[str]:
    """单句超长（英文长句/无标点表格行）时按字数硬切。"""
    if len(sentence) <= max_chars:
        return [sentence]
    return [sentence[i:i + max_chars] for i in range(0, len(sentence), max_chars)]


def _units(paragraph: str, max_chars: int) -> list[str]:
    """一段拆成「不可再分的句子级单元」，每个单元都不超过 max_chars。"""
    units: list[str] = []
    for sentence in sentences(paragraph):
        units.extend(_hard_cut(sentence, max_chars))
    return units


def split_text(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """文本 → 切片列表。空文本返回 []，不抛错（上层据此判“抽不出正文”）。

    组装是「句子级贪心 + 段首换行 + 块间重叠」：
    段与段之间用 \\n 分隔（保留条目结构），段内句子直接相接（不凭空插空格）；
    开新块时先放上一块的尾部 overlap 字，再判断放不放进下一个单元——
    放不进就丢掉重叠，**块长上限永远优先于重叠**。
    """
    if max_chars < HARD_MIN_MAX:
        raise SplitError(f"max_chars 不能小于 {HARD_MIN_MAX}，收到 {max_chars}")
    if not 0 <= overlap < max_chars:
        raise SplitError(f"overlap 必须满足 0 <= overlap < max_chars，收到 {overlap}")

    # (文本, 是否段首) —— 段首要补换行，段内句子直接相邻
    stream: list[tuple[str, bool]] = []
    for paragraph in paragraphs(text):
        for index, unit in enumerate(_units(paragraph, max_chars)):
            stream.append((unit, index == 0))

    chunks: list[str] = []
    buf = ""
    for unit, para_start in stream:
        sep = "\n" if (para_start and buf) else ""
        if not buf:
            buf = unit
            continue
        if len(buf) + len(sep) + len(unit) <= max_chars:
            buf += sep + unit
            continue

        chunks.append(buf)
        carry = buf[-overlap:] if overlap else ""
        if carry and len(carry) + 1 + len(unit) <= max_chars:
            buf = f"{carry}\n{unit}"
        else:
            buf = unit
    if buf:
        chunks.append(buf)

    # 尾巴并块：最后一块太短时并进上一块（并完仍可能超长，那就保持独立）
    if len(chunks) >= 2 and len(chunks[-1]) < MIN_CHUNK_CHARS:
        merged = f"{chunks[-2]}\n{chunks[-1]}"
        if len(merged) <= max_chars:
            chunks[-2] = merged
            chunks.pop()

    return chunks
