"""正文抽取：编码兼容、格式拒绝、PDF 内置解析器。"""
from __future__ import annotations

import zlib

import pytest

from app.knowledge.extract import ExtractionError, _pdf_builtin, extract_text


def _pdf_bytes(stream: bytes, compress: bool = True) -> bytes:
    """造一个最小可用 PDF：一个内容流，里头是 Tj 文本。"""
    body = zlib.compress(stream) if compress else stream
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/Contents 4 0 R>>endobj\n"
        b"4 0 obj<</Length " + str(len(body)).encode() + b">>\nstream\n"
        + body
        + b"\nendstream\nendobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    )


def test_utf8_txt(tmp_path):
    file = tmp_path / "a.txt"
    file.write_text("茶园土壤湿度低于 55% 时应灌溉，沙壤土取下限。", encoding="utf-8")
    assert "土壤湿度" in extract_text(file)


def test_gb18030_txt(tmp_path):
    file = tmp_path / "b.txt"
    file.write_bytes("茶园霜冻预警：气温低于 4℃ 启动防霜风机。".encode("gb18030"))
    assert "霜冻" in extract_text(file)


def test_markdown(tmp_path):
    file = tmp_path / "c.md"
    file.write_text("# 灌溉规程\n\n湿度低于 55% 应灌溉。", encoding="utf-8")
    assert "灌溉规程" in extract_text(file)


def test_unsupported_suffix_rejected(tmp_path):
    file = tmp_path / "d.docx"
    file.write_bytes(b"whatever")
    with pytest.raises(ExtractionError, match="不支持"):
        extract_text(file)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(ExtractionError, match="不存在"):
        extract_text(tmp_path / "nope.txt")


def test_too_short_rejected(tmp_path):
    file = tmp_path / "e.txt"
    file.write_text("太短", encoding="utf-8")
    with pytest.raises(ExtractionError, match="抽不到正文"):
        extract_text(file)


def test_builtin_pdf_extractor_reads_tj_text():
    # 镜像里没有 pypdf，这一级才是演示机真正会走到的路径
    stream = b"BT /F1 12 Tf 72 720 Td (Soil moisture 55 percent, irrigate now.) Tj ET"
    text = _pdf_builtin(_pdf_bytes(stream))
    assert "Soil moisture" in text
    assert "irrigate" in text


def test_builtin_pdf_extractor_handles_hex_and_escapes():
    stream = rb"BT <48656C6C6F> Tj (\050A\051) Tj ET"
    text = _pdf_builtin(_pdf_bytes(stream))
    assert "Hello" in text
    assert "(A)" in text


def test_scanned_pdf_reports_extraction_error(tmp_path):
    # 无任何 Tj 的 PDF（等价于扫描件）必须显式失败，不能入库 0 切片还说成功
    stream = b"BT ET"
    file = tmp_path / "scan.pdf"
    file.write_bytes(_pdf_bytes(stream))
    with pytest.raises(ExtractionError):
        extract_text(file)
