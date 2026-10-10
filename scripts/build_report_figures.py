"""Draw the implemented architecture and sequence for the course report.

These are diagrams authored from code, not screenshots or model-generated images.
Committed figures let report rebuilding work without a local CJK font.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/report/figures"
INK, ACCENT = "#182B3A", "#176B58"


def make_diagrams(font_path):
    font = ImageFont.truetype(str(font_path), 35)
    small = ImageFont.truetype(str(font_path), 28)
    title = ImageFont.truetype(str(font_path), 46)
    OUT.mkdir(parents=True, exist_ok=True)

    def canvas(height):
        image = Image.new("RGB", (1800, height), "white")
        return image, ImageDraw.Draw(image)

    def text(draw, xy, value, face=font, anchor="mm", color=INK):
        draw.multiline_text(
            xy, value, font=face, anchor=anchor, align="center", fill=color, spacing=10
        )

    def box(draw, coords, value):
        draw.rounded_rectangle(coords, radius=14, fill="#F4F8F7", outline=ACCENT, width=3)
        x1, y1, x2, y2 = coords
        text(draw, ((x1 + x2) / 2, (y1 + y2) / 2), value)

    def arrow(draw, points, color=ACCENT):
        draw.line(points, fill=color, width=4)
        x1, y1 = points[-2]
        x2, y2 = points[-1]
        if y1 == y2:
            sign = 1 if x2 >= x1 else -1
            draw.polygon([(x2, y2), (x2 - sign * 15, y2 - 8), (x2 - sign * 15, y2 + 8)], fill=color)
        else:
            sign = 1 if y2 >= y1 else -1
            draw.polygon([(x2, y2), (x2 - 8, y2 - sign * 15), (x2 + 8, y2 - sign * 15)], fill=color)

    image, draw = canvas(1240)
    text(draw, (900, 54), "多智能体办公协作系统实际架构", title)
    box(draw, (95, 120, 860, 230), "Streamlit 页面\n需求  上传  进度  下载")
    box(draw, (940, 120, 1705, 230), "CLI 入口\nrun  workflow-test  acceptance")
    arrow(draw, [(480, 230), (480, 290)])
    box(draw, (95, 290, 860, 410), "RunController\n输入冻结  后台执行  同会话防重")
    text(draw, (1325, 345), "CLI 直接执行原图", small)
    arrow(draw, [(480, 410), (480, 470)])
    arrow(draw, [(1325, 230), (1325, 280)])
    arrow(draw, [(1325, 400), (1325, 470)])
    draw.rounded_rectangle((65, 470, 1735, 815), radius=18, outline="#849A96", width=3)
    text(draw, (900, 510), "run_workflow  LangGraph  共享结构化状态", font)
    names = [
        "Manager\n需求解析",
        "Planner\n大纲规划",
        "Data\n工具调用",
        "Writer\n受约束草稿",
        "Checker\n程序和模型审核",
    ]
    centers = []
    for index, name in enumerate(names):
        x = 110 + 330 * index
        box(draw, (x, 570, x + 260, 720), name)
        centers.append(x + 130)
        if index:
            arrow(draw, [(x - 70, 645), (x, 645)])
    arrow(draw, [(1560, 720), (1560, 765), (1230, 765), (1230, 720)])
    text(draw, (1310, 794), "拒绝且可修正  最多返工两次", small)
    text(draw, (900, 548), "状态传递  requirements  outline  data  draft  review  events", small)
    box(draw, (95, 930, 605, 1080), "数据工具\n校验  最新快照统计\nSHA 与原始行号")
    box(
        draw, (645, 930, 1155, 1080), "共享 AgentSession\nMockTransport 或模型 API\nHTTP 与输出预算"
    )
    box(
        draw,
        (1195, 930, 1705, 1080),
        "终态后保存实际产物\nsave_workflow 门禁\n审核通过才有 report.md",
    )
    draw.line([(900, 815), (900, 880)], fill=ACCENT, width=4)
    draw.line([(350, 880), (1450, 880)], fill=ACCENT, width=4)
    for x in (350, 900, 1450):
        arrow(draw, [(x, 880), (x, 930)])
    text(
        draw,
        (900, 1150),
        "单进程集中编排  五角色顺序执行  单会话后台任务\n本版未实现跨进程队列 持久恢复或 FIPA ACL",
        small,
    )
    image.save(OUT / "architecture.png")

    image, draw = canvas(1250)
    text(draw, (900, 54), "实际协作与审核返工时序", title)
    actors = ["入口", "Manager", "Planner", "Data", "Writer", "Checker", "导出"]
    xs = [125, 380, 630, 875, 1120, 1380, 1640]
    for x, name in zip(xs, actors, strict=True):
        box(draw, (x - 105, 120, x + 105, 195), name)
        draw.line((x, 195, x, 1150), fill="#CAD6D2", width=2)
    steps = [
        (0, 1, "需求与输入来源", 260),
        (1, 2, "已确认需求", 360),
        (2, 3, "需求与大纲保存在共享状态", 460),
        (3, 4, "真实统计与来源", 560),
        (4, 5, "当前草稿  核心事实声明", 660),
        (5, 4, "不通过  当前草稿与修改意见", 800),
        (4, 5, "修改稿  原统计保持不变", 910),
        (5, 6, "终态返回  通过时复核最终报告", 1040),
    ]
    for start, end, label, y in steps:
        arrow(draw, [(xs[start], y), (xs[end], y)])
        text(draw, ((xs[start] + xs[end]) / 2, y - 30), label, small)
    text(draw, (900, 732), "Checker 程序检查失败时可跳过本轮 Checker HTTP", small)
    text(
        draw,
        (900, 1180),
        "返工可选且有界  需求缺失或异常会提前终止\n导出保留所有终态记录  失败不生成最终报告",
        small,
    )
    image.save(OUT / "sequence.png")
    print("Authored architecture.png and sequence.png from the implemented control flow.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True, help="Local CJK-capable TrueType font")
    args = parser.parse_args()
    make_diagrams(args.font)


if __name__ == "__main__":
    main()
