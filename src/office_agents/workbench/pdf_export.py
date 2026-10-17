"""Render the frozen Markdown with embedded Chinese type and repeatable tables."""

from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from markdown_it import MarkdownIt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

FONT_NAME = "OfficeWenKai"
FONT_PATH = Path(__file__).parent / "assets" / "LXGWWenKai-Regular.ttf"
_FONT_LOCK = Lock()


def _font():
    with _FONT_LOCK:
        if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
    return FONT_NAME


def _inline(token):
    """Use parser text tokens only; user HTML can never become ReportLab markup."""
    return "".join(
        "<br/>"
        if child.type in {"softbreak", "hardbreak"}
        else escape(child.content)
        if child.type in {"text", "code_inline", "html_inline"}
        else ""
        for child in (token.children or [])
    )


def render_pdf(snapshot: dict, destination: Path) -> None:
    """Export the exact frozen Markdown; no model or mutable report is consulted."""
    font = _font()
    markdown = snapshot["markdown"]
    if not isinstance(markdown, str) or not markdown.strip() or len(markdown) > 2_000_000:
        raise ValueError("Invalid frozen Markdown size")
    body = ParagraphStyle(
        "Body",
        fontName=font,
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#243449"),
        spaceAfter=8,
        wordWrap="CJK",
        splitLongWords=True,
        allowWidows=0,
        allowOrphans=0,
    )
    title = ParagraphStyle(
        "Title", parent=body, fontSize=21, leading=29, spaceBefore=8, spaceAfter=16
    )
    heading = ParagraphStyle(
        "Heading",
        parent=body,
        fontSize=13,
        leading=21,
        textColor=colors.HexColor("#145b69"),
        spaceBefore=14,
        spaceAfter=7,
        keepWithNext=True,
    )
    cell = ParagraphStyle("Cell", parent=body, fontSize=8, leading=12, spaceAfter=0)
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=10, firstLineIndent=-8)
    tokens = MarkdownIt("commonmark", {"html": False}).enable("table").parse(markdown)
    story = []
    index = 0
    list_depth = 0
    width = A4[0] - 96
    while index < len(tokens):
        token = tokens[index]
        if token.type == "table_open":
            rows = []
            row = []
            index += 1
            while tokens[index].type != "table_close":
                item = tokens[index]
                if item.type == "tr_open":
                    row = []
                elif item.type == "inline":
                    row.append(Paragraph(_inline(item), cell))
                elif item.type == "tr_close":
                    rows.append(row)
                index += 1
            if rows:
                columns = len(rows[0])
                widths = (
                    [width * value for value in (0.10, 0.24, 0.12, 0.08, 0.46)]
                    if columns == 5
                    else [width / columns] * columns
                )
                table = LongTable(rows, colWidths=widths, repeatRows=1, splitInRow=1, hAlign="LEFT")
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1f3")),
                            (
                                "ROWBACKGROUNDS",
                                (0, 1),
                                (-1, -1),
                                [colors.white, colors.HexColor("#f7f9fb")],
                            ),
                            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#92b9c1")),
                            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dce4eb")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 7),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                        ]
                    )
                )
                story += [Spacer(1, 5), table, Spacer(1, 10)]
        elif token.type == "heading_open":
            story.append(
                Paragraph(_inline(tokens[index + 1]), title if token.tag == "h1" else heading)
            )
            index += 2
        elif token.type == "paragraph_open":
            content = _inline(tokens[index + 1])
            story.append(
                Paragraph(("• " if list_depth else "") + content, bullet if list_depth else body)
            )
            index += 2
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            list_depth += 1
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            list_depth -= 1
        elif token.type in {"fence", "code_block"}:
            story.append(Paragraph(escape(token.content).replace("\n", "<br/>"), body))
        index += 1

    def page(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#697b8e"))
        canvas.drawString(48, A4[1] - 30, "部门工作汇报 / 多智能体协作")
        canvas.setStrokeColor(colors.HexColor("#dce4eb"))
        canvas.line(48, 38, A4[0] - 48, 38)
        canvas.drawString(
            48, 24, "离线夹具结果" if snapshot.get("mode") == "offline_mock" else "审核合格快照"
        )
        canvas.drawRightString(A4[0] - 48, 24, f"第 {document.page} 页")
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(destination),
        pagesize=A4,
        rightMargin=48,
        leftMargin=48,
        topMargin=52,
        bottomMargin=52,
        title=snapshot.get("requirements", {}).get("title", "部门工作汇报"),
        author="多智能体办公协作系统",
        pageCompression=1,
    )
    body.alignment = TA_LEFT
    document.build(story, onFirstPage=page, onLaterPages=page)
