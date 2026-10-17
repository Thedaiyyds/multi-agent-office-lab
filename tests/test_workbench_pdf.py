"""Real PDF pagination and escaped text checks; no model or user data."""

from io import BytesIO

import pytest
from pypdf import PdfReader

from office_agents.workbench.pdf_export import render_pdf


def test_long_chinese_table_splits_pages_and_preserves_last_cell(tmp_path):
    markdown = "# 分页核对\n\n| 编号 | 指标 | 数值 | 单位 | 定义 |\n|---|---|---|---|---|\n"
    markdown += "\n".join(
        f"| F{index:03} | 中文项目指标 | {index} | 项 | 来源已核对，保持范围。 |"
        for index in range(1, 121)
    )
    markdown += "\n\n## 末尾核验\n\n中文末尾标记 & 原文 <b>不是HTML执行</b>。\n"
    path = tmp_path / "long.pdf"
    render_pdf(dict(markdown=markdown, mode="live"), path)
    reader = PdfReader(BytesIO(path.read_bytes()))
    assert len(reader.pages) >= 4
    assert all("编号" in page.extract_text() for page in reader.pages[:-1])
    text = "".join(page.extract_text() for page in reader.pages)
    assert "F120" in text and "中文末尾标记 & 原文 <b>不是HTML执行</b>。" in text
    assert all(float(page.mediabox.width) < 596 for page in reader.pages)


def test_single_oversized_cell_is_paginated_instead_of_failing_export(tmp_path):
    markdown = "# 长来源核验\n\n| 来源 | 内容 |\n|---|---|\n"
    markdown += "| 原文 | " + "中文来源长段落。" * 900 + "末端标记 |\n"
    path = tmp_path / "cell.pdf"
    render_pdf(dict(markdown=markdown, mode="offline_mock"), path)
    reader = PdfReader(path)
    assert len(reader.pages) > 1
    assert "末端标记" in "".join(page.extract_text() for page in reader.pages)


@pytest.mark.parametrize("markdown", ["", None, "x" * 2_000_001])
def test_pdf_rejects_empty_or_oversized_frozen_content(tmp_path, markdown):
    with pytest.raises(ValueError):
        render_pdf(dict(markdown=markdown), tmp_path / "invalid.pdf")
