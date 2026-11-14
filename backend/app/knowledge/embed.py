"""确定性本地向量化：字符 n-gram 有符号哈希 + 亚线性压缩 + L2 归一化。

**为什么是稀疏向量而不是定长数组**：
一度用 512 维定长数组，实测“霜冻风险怎么处理”把植保文档排到了气象文档前面——
短文档里 70 个 token 撞进 512 个桶，碰撞噪声盖过了真实信号。现在把哈希空间放大到
32768 且只存非零项：碰撞率降到可忽略，而每块向量只占 ~1KB（JSON 里是一串 [下标,值]）。

**为什么不用模型向量**：
- 演示机首次运行要下载 embedding 模型（几百 MB），彩排现场等不起；
- 中文农艺条文的关键区分度在字面搭配（“霜冻”“灰霉病”“pH 5.5”），字符 bigram 正好覆盖；
- 确定性：同样输入永远同样向量，回归测试可断言，不会某天悄悄变。

已知边界：不做同义词扩展（“霜冻”检索不到只写“冻害”的段落）。这是有意的取舍——
宁可检索不到，也不猜；植保员提示词也要求“未检索到就说未检索到”。
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata

# 哈希空间大小，同时也是导出给 Chroma 的稠密维度。
# 32768 是在「碰撞率」与「Chroma 上传体积（float32 128KB/块）」之间的折中。
DIM = 32768

_UNIGRAM_WEIGHT = 0.3   # 单字信号弱且易噪声，压到 3 成
_BIGRAM_WEIGHT = 1.0    # 主要信号
_WORD_WEIGHT = 1.0      # 拉丁词/数字整体作为一个 token

_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_ASCII_WORD = re.compile(r"[a-z0-9]+(?:[._\-/+][a-z0-9]+)*")

# 这些 ASCII 标点参与构词（5.5 / pH-7 / A/B），不能当分隔符吃掉
_KEEP_PUNCT = set("._-/+%")


def normalize(text: str) -> str:
    """全半角统一 + 小写 + 其余标点转空格（标点不承载语义，但会切断 bigram）。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    out = []
    for ch in text:
        if ch == "\n" or ch in _KEEP_PUNCT:
            out.append(ch)
        elif ch.isalnum() or "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf":
            out.append(ch)
        else:
            out.append(" ")
    return "".join(out)


def tokenize(text: str) -> list[tuple[str, float]]:
    """返回 [(token, 权重)]，保持出现顺序。空文本返回 []。"""
    norm = normalize(text)
    if not norm.strip():
        return []
    tokens: list[tuple[str, float]] = []
    for run in _CJK_RUN.finditer(norm):
        seg = run.group(0)
        for ch in seg:
            tokens.append((f"u:{ch}", _UNIGRAM_WEIGHT))
        for i in range(len(seg) - 1):
            tokens.append((f"b:{seg[i:i + 2]}", _BIGRAM_WEIGHT))
    for word in _ASCII_WORD.finditer(norm):
        tokens.append((f"w:{word.group(0)}", _WORD_WEIGHT))
    return tokens


def _bucket(token: str) -> tuple[int, float]:
    """token → (维度下标, ±1)。同一 token 永远落在同一格、同号（有符号哈希）。"""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % DIM, (1.0 if value >> 63 else -1.0)


def embed(text: str) -> dict[int, float]:
    """文本 → 稀疏单位向量（下标 → 权重）。空文本返回 {}，不抛错。"""
    raw: dict[int, float] = {}
    for token, weight in tokenize(text):
        idx, sign = _bucket(token)
        raw[idx] = raw.get(idx, 0.0) + sign * weight

    # 亚线性压缩：一个词出现 10 次不该等于 10 个词的权重
    vec = {i: math.copysign(math.log1p(abs(v)), v) for i, v in raw.items() if v}
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm == 0.0:
        return {}
    return {i: v / norm for i, v in vec.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    """稀疏余弦（两向量都已单位化，点积即余弦）。任一为空返回 0.0。"""
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(index, 0.0) for index, value in a.items())


def to_dense(vec: dict[int, float], dim: int = DIM) -> list[float]:
    """稀疏 → 稠密，仅供 Chroma 等要求定长向量的后端使用。"""
    dense = [0.0] * dim
    for index, value in vec.items():
        if 0 <= index < dim:
            dense[index] = value
    return dense


def to_pairs(vec: dict[int, float]) -> list[list[float]]:
    """稀疏 → [[下标, 值]]，JSON 落盘用（比定长数组省两个数量级）。"""
    return [[index, round(value, 6)] for index, value in sorted(vec.items())]


def from_pairs(pairs) -> dict[int, float]:
    """[[下标, 值]] → 稀疏。容忍脏数据（跳过不合规项而不是整库报错）。"""
    out: dict[int, float] = {}
    if not isinstance(pairs, list):
        return out
    for item in pairs:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                out[int(item[0])] = float(item[1])
            except (TypeError, ValueError):
                continue
    return out
