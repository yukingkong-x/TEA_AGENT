"""正文抽取：txt / md / pdf。

PDF 走三级降级，**每一级都真的会用**，不是摆设：
    1. pypdf（若镜像里装了）——最稳，能处理 xref 流/对象流；
    2. pdfminer.six（若装了）——版面还原更好；
    3. 内置最小解析器——只用标准库，直接扫 `stream...endstream` 解 Flate，
       抓 `(...) Tj` / `[...] TJ` / `<...>` 十六进制串。够对付“Word 导出 PDF”
       这类常见场景，也是演示机上唯一保证能跑的一级。

扫描件（纯图片）抽不出字是**正常结果**，此时抛出带指引的 ExtractionError，
让上传接口把 doc 标成 failed 并说明原因——不能悄悄入库 0 个切片还说成功。
"""
from __future__ import annotations

import re
import zlib
from pathlib import Path

# 判定“抽出来的东西是不是正文”的阈值：可读字符占比低于此值视为乱码
_MIN_READABLE_RATIO = 0.55
_MIN_TEXT_CHARS = 20

_ALLOWED_SUFFIX = {".txt", ".md", ".markdown", ".pdf"}

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ExtractionError(RuntimeError):
    """抽不出正文（格式不支持 / 扫描件 / 文件损坏 / 编码不可识别）。"""


# ─────────────────────────── 入口 ───────────────────────────

def extract_text(path: str | Path) -> str:
    file = Path(path)
    if not file.exists():
        raise ExtractionError(f"文件不存在：{file}")
    suffix = file.suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise ExtractionError(f"不支持的格式 {suffix}（只支持 {sorted(_ALLOWED_SUFFIX)}）")

    if suffix == ".pdf":
        text = _extract_pdf(file.read_bytes())
    else:
        text = _decode_text(file.read_bytes())

    text = _tidy(text)
    if len(text) < _MIN_TEXT_CHARS:
        raise ExtractionError(
            f"{file.name} 抽不到正文（{len(text)} 字）。"
            "扫描件/图片型 PDF 需要先做 OCR，或改传 txt/md。"
        )
    if _readable_ratio(text) < _MIN_READABLE_RATIO:
        raise ExtractionError(f"{file.name} 抽出的是乱码（字体编码不受支持），请改传 txt/md。")
    return text


# ─────────────────────────── 纯文本 ───────────────────────────

def _decode_text(data: bytes) -> str:
    """UTF-8 优先，退回 GB18030（中文 Windows 导出的 txt 常见），再退回 latin-1。"""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    # latin-1 不会失败；可读性由 extract_text 的 ratio 检查兜住
    return data.decode("latin-1", errors="replace")


def _tidy(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = _CTRL.sub("", text)
    # PDF 里常见的连字/断行修复：中文之间被插入的单个换行交给切片器合并
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _readable_ratio(text: str) -> float:
    if not text:
        return 0.0
    good = 0
    for ch in text:
        if ch.isalnum() or ch.isspace() or "\u4e00" <= ch <= "\u9fff":
            good += 1
        elif ch in "，。、；：！？（）《》“”‘’—…·％℃°/-+%.,:;()[]'\"":
            good += 1
        elif ch == "\ufffd":
            good -= 1
    return max(0.0, good) / len(text)


# ─────────────────────────── PDF ───────────────────────────

def _extract_pdf(data: bytes) -> str:
    for backend in (_pdf_pypdf, _pdf_pdfminer_top, _pdf_builtin):
        try:
            text = backend(data)
        except Exception:  # noqa: BLE001 任一后端不可用/解析失败都继续降级
            continue
        if text and len(_tidy(text)) >= _MIN_TEXT_CHARS and _readable_ratio(_tidy(text)) >= _MIN_READABLE_RATIO:
            return text
    return ""


def _pdf_pypdf(data: bytes) -> str:
    import io

    from pypdf import PdfReader  # 可选依赖，镜像里没有就 ImportError 降级

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _pdf_pdfminer_top(data: bytes) -> str:
    from pdfminer.high_level import extract_text as _extract  # 可选依赖
    import io

    return _extract(io.BytesIO(data))


_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)


def _pdf_builtin(data: bytes) -> str:
    """最小解析器：解压内容流 → 抓字符串字面量/十六进制串。"""
    pieces: list[str] = []
    for match in _STREAM.finditer(data):
        raw = match.group(1)
        content = raw
        if raw[:2] in (b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
            try:
                content = zlib.decompress(raw)
            except zlib.error:
                continue
        if b"Tj" not in content and b"TJ" not in content:
            continue
        pieces.extend(_content_strings(content))
    return " ".join(pieces)


def _content_strings(content: bytes) -> list[str]:
    out: list[str] = []
    length = len(content)
    i = 0
    while i < length:
        byte = content[i:i + 1]
        if byte == b"(":
            text, i = _read_literal(content, i)
            out.append(text)
        elif byte == b"<" and content[i + 1:i + 2] != b"<":
            end = content.find(b">", i)
            if end == -1:
                break
            out.append(_decode_hex(content[i + 1:end]))
            i = end + 1
        elif byte in (b"\n", b"\r", b"T") and content[i:i + 2] in (b"TD", b"Td", b"T*", b"ET"):
            out.append("\n")   # 位置/换行算子 → 断行，避免把两行拼成一个词
            i += 2
        else:
            i += 1
    return out


_ESCAPES = {
    b"n": "\n", b"r": "\r", b"t": "\t", b"b": "\b", b"f": "\f",
    b"(": "(", b")": ")", b"\\": "\\",
}


def _read_literal(content: bytes, start: int) -> tuple[str, int]:
    """读 PDF 字符串字面量，处理嵌套括号与转义；返回 (文本, 下一个位置)。"""
    out = bytearray()
    depth = 1
    i = start + 1
    length = len(content)
    while i < length and depth:
        ch = content[i:i + 1]
        if ch == b"\\":
            nxt = content[i + 1:i + 2]
            if nxt in _ESCAPES:
                out += _ESCAPES[nxt].encode("latin-1")
                i += 2
            elif nxt.isdigit():
                octal = content[i + 1:i + 4]
                digits = b""
                for byte in octal:
                    if byte in b"01234567":
                        digits += bytes([byte])
                    else:
                        break
                out.append(int(digits or b"0", 8) & 0xFF)
                i += 1 + len(digits)
            elif nxt in (b"\n", b"\r"):
                i += 2
            else:
                out += nxt
                i += 2
        elif ch == b"(":
            depth += 1
            out += ch
            i += 1
        elif ch == b")":
            depth -= 1
            if depth:
                out += ch
            i += 1
        else:
            out += ch
            i += 1
    return _decode_pdf_bytes(bytes(out)), i


def _decode_pdf_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    return raw.decode("latin-1", errors="replace")


def _decode_hex(raw: bytes) -> str:
    hexed = re.sub(rb"[^0-9A-Fa-f]", b"", raw)
    if len(hexed) % 2:
        hexed += b"0"
    try:
        data = bytes.fromhex(hexed.decode("ascii"))
    except ValueError:
        return ""
    return _decode_pdf_bytes(data)
