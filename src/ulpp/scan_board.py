# -*- coding: utf-8 -*-
"""标定板：一张 A4，黑边框 + 20 mm 一格的黑色小方块 + 四角定位角标。

用途：拍照量纸时，把标定板和胶纸**并排平放**在一起拍进同一张照片——
- 方块的已知毫米坐标 → 估出手机镜头的径向畸变（这是照片精度最大的误差源）；
- 去畸变后再用胶纸的 A4 四边做单应，量格阵就会准得多。

方块坐标（mm，页面左上角原点）与检测端共用 ``dot_positions()``，改版式只改这里。
"""
from __future__ import annotations

from typing import List, Tuple

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DictionaryObject,
    FloatObject,
    NameObject,
)

A4_W_MM, A4_H_MM = 210.0, 297.0
MM_TO_PT = 72.0 / 25.4

FRAME_MM = 6.0          # 黑边框宽
MARK_MM = 4.0           # 小方块边长
SPACING_MM = 20.0       # 方块间距
FIRST_X_MM = 25.0
FIRST_Y_MM = 30.0
COLS = 9
ROWS = 13


def dot_positions() -> List[Tuple[float, float]]:
    """按行优先返回每个方块中心的 (x_mm, y_mm)。"""
    out = []
    for r in range(ROWS):
        for c in range(COLS):
            out.append((FIRST_X_MM + c * SPACING_MM, FIRST_Y_MM + r * SPACING_MM))
    return out


def make_board_pdf(path: str) -> str:
    """画一张标定板 A4（纯黑矩形，不依赖字体）。"""
    writer = PdfWriter()
    page = writer.add_blank_page(width=A4_W_MM * MM_TO_PT, height=A4_H_MM * MM_TO_PT)
    page_h = A4_H_MM * MM_TO_PT

    def rect_mm(x, y, w, h):
        """mm（左上原点）→ PDF 用户坐标（左下原点）。"""
        return [FloatObject(round(x * MM_TO_PT, 3)),
                FloatObject(round(page_h - (y + h) * MM_TO_PT, 3)),
                FloatObject(round(w * MM_TO_PT, 3)),
                FloatObject(round(h * MM_TO_PT, 3))]

    ops = [([], b"q"), ([FloatObject(0)], b"g")]
    # 纸边留白、不画外框，也不在四角加额外方块：多出来的标记会让"网格角点"认错。
    # 靠"纸本身是亮的 + 满页 20 mm 方块"就够定位了。
    # 小方块
    for cx, cy in dot_positions():
        ops.append((rect_mm(cx - MARK_MM / 2, cy - MARK_MM / 2, MARK_MM, MARK_MM), b"re"))
    ops += [([], b"f"), ([], b"Q")]

    content = ContentStream(None, writer)
    content.operations.extend(ops)
    page.replace_contents(content)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/ProcSet"): ArrayObject([NameObject("/PDF")]),
    })
    writer.add_metadata({"/Title": "ulpp 标定板", "/Creator": "ulpp"})
    with open(path, "wb") as fh:
        writer.write(fh)
    writer.close()
    return path
