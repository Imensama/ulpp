# -*- coding: utf-8 -*-
"""解析 PDF：找出每一页里的“卡片”（名称/编号/尺寸/序号/数量/颜色 + 图）。

坐标约定
--------
pdfplumber 用「左上角原点、y 向下」；PDF 用户坐标用「左下角原点、y 向上」。
本模块内部先按 pdfplumber 坐标算，最后统一换算成 PDF 坐标存进 Card.clip_pdf。
"""

from __future__ import annotations

import os
import re
import statistics
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

import pdfplumber

from .i18n import tr

# ---------------------------------------------------------------- 文本规则

# 标签后的空白只用 "[ \t]*"，不能用 \s*：\s 会跨行，把下一行的值吃进空字段。
# 值的首字符不能是冒号——否则"包络尺寸:"（值为空）会把冒号本身当成值。
NAME_RE = re.compile(r"文件名称[ \t]*[：:]?[ \t]*([^\n：:][^\n]*)")
SIZE_RE = re.compile(r"(?:包络)?尺寸[ \t]*[：:]?[ \t]*([^\n：:][^\n]*)")
SEQ_RE = re.compile(r"序号[ \t]*[：:]?[ \t]*(\d+)")
QTY_RE = re.compile(r"数量[ \t]*[：:]?[ \t]*(\d+)")
COLOR_RE = re.compile(r"颜色[ \t]*[：:]?[ \t]*([^\n：:][^\n]*)")
DWG_NO_RE = re.compile(r"图号[ \t]*[：:]?[ \t]*([^\n：:][^\n]*)")

ANCHOR = "文件名称"
# 页眉页脚里的“第10页(共512页)”这类噪音，不进卡片
PAGE_NOISE = re.compile(r"第\s*\d+\s*页|共\s*\d+\s*页|Page\s*\d+\s*(?:of|/)\s*\d+", re.I)

# 卡片内容距离格线的裁剪余量（pt）：避免把表格线条一起缩进标签
EDGE_PAD_PT = 1.2
# 一张卡里，字段之间最多允许跳过多少行非字段内容（备注/图纸标注/手写）
MAX_NOTE_LINES = 20
# 聚类容差（pt）
CLUSTER_TOL = 6.0
# 判断“表格线”的最大粗细（pt）
RULE_THICKNESS = 1.6


@dataclass
class Card:
    """一张标签的数据。"""

    name: str = ""
    seq: Optional[int] = None
    qty: int = 1
    size: str = ""
    color: str = ""
    dwg_no: str = ""
    col: int = 0
    row: int = 0
    # PDF 用户坐标（左下原点）
    cell_pdf: Tuple[float, float, float, float] = (0, 0, 0, 0)
    clip_pdf: Tuple[float, float, float, float] = (0, 0, 0, 0)

    @property
    def label(self) -> str:
        return self.name or "?"


@dataclass
class PageCards:
    page_no: int                      # 1 起的物理页号
    cards: List[Card] = field(default_factory=list)
    cols: int = 0
    rows: int = 0
    warnings: List[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.cards)


@dataclass
class PdfCards:
    path: str
    n_pages: int
    pages: List[PageCards] = field(default_factory=list)

    @property
    def cards(self) -> List[Card]:
        return [c for p in self.pages for c in p.cards]

    @property
    def stickers(self) -> int:
        return sum(c.qty for c in self.cards)


# ---------------------------------------------------------------- 工具函数

def _cluster(values: Iterable[float], tol: float = CLUSTER_TOL) -> List[float]:
    groups: List[List[float]] = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _pitch(starts: Sequence[float], fallback: float) -> float:
    """由相邻起点估计节距。"""
    if len(starts) >= 2:
        diffs = [b - a for a, b in zip(starts, starts[1:]) if b - a > 1]
        if diffs:
            return statistics.median(diffs)
    return fallback


def _bbox_union(boxes: Iterable[Tuple[float, float, float, float]]):
    boxes = list(boxes)
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _grid_positions(drawings: Sequence[Tuple[float, float, float, float]], page_w: float, page_h: float):
    """找出贯通整页的表格线位置（列线 x、行线 y），用来识别“格线”。"""
    vgrid, hgrid = [], []
    for x0, y0, x1, y1 in drawings:
        if (x1 - x0) <= 2.0 and (y1 - y0) > 0.3 * page_h:
            vgrid.append((x0 + x1) / 2)
        if (y1 - y0) <= 2.0 and (x1 - x0) > 0.3 * page_w:
            hgrid.append((y0 + y1) / 2)
    return sorted(vgrid), sorted(hgrid)


def _is_rule(
    box: Tuple[float, float, float, float],
    cell: Sequence[float],
    vgrid: Sequence[float] = (),
    hgrid: Sequence[float] = (),
) -> bool:
    """细长的水平/垂直表格线（含贴格边的格线），不应该算进卡片内容。"""
    cw, ch = cell[2] - cell[0], cell[3] - cell[1]
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if h <= RULE_THICKNESS and w >= 0.9 * cw:
        return True
    if w <= RULE_THICKNESS and h >= 0.9 * ch:
        return True
    if h <= 2.0 and w >= 0.5 * cw and any(abs(y0 - g) < 2.0 or abs(y1 - g) < 2.0 for g in hgrid):
        return True
    if w <= 2.0 and h >= 0.5 * ch and any(abs(x0 - g) < 2.0 or abs(x1 - g) < 2.0 for g in vgrid):
        return True
    return False


def _is_frame(box: Tuple[float, float, float, float], cw: float, ch: float) -> bool:
    """几乎占满整格的边框/外框（3 列 1 行这类大格子常见），不算卡片内容。"""
    w, h = box[2] - box[0], box[3] - box[1]
    return w >= 0.9 * cw and h >= 0.9 * ch


FIELD_LABELS = ("文件名称", "图号", "包络尺寸", "尺寸", "序号", "数量", "颜色")


def _extract_words(page) -> Tuple[List[dict], int]:
    """两种取词模式都跑，取“锚点出现次数多”的那份。

    默认取词按坐标从左到右拼，相邻两格文字坐标重叠时会被粘成一个词
    （2026-11-16 泰国小U 的 12 张卡只解析出 7 张就是这个原因）；
    `use_text_flow=True` 按 PDF 内容流取，重叠的两段仍是两个词。
    """
    best_words: List[dict] = []
    best_hits = -1
    for flow in (False, True):   # 打平时留默认模式（老图纸的排版就靠它）
        try:
            words = page.extract_words(use_text_flow=flow, x_tolerance=2, y_tolerance=3)
        except Exception:                                 # pragma: no cover - 老版本 pdfplumber
            continue
        words.sort(key=lambda w: (round(w["top"] / 2.0), w["x0"]))
        hits = sum(w["text"].count(ANCHOR) for w in words)
        if hits > best_hits:
            best_words, best_hits = words, hits
    return best_words, max(0, best_hits)


def _split_merged_anchors(words: Sequence[dict]) -> Tuple[List[dict], List[dict]]:
    """一个词里粘了多张卡的“文件名称”时，按字符比例切成各自的锚点。

    两种取词模式都粘连是最后手段：位置是估算的，但至少每张卡都有锚点、不整张消失。
    """
    kept: List[dict] = []
    anchors: List[dict] = []
    for w in words:
        text = w["text"]
        count = text.count(ANCHOR)
        if count == 0:
            kept.append(w)
        elif count == 1:
            kept.append(w)
            anchors.append(w)
        else:
            total = max(1, len(text))
            base, span = w["x0"], w["x1"] - w["x0"]
            pos = 0
            for _ in range(count):
                i = text.find(ANCHOR, pos)
                if i < 0:                                  # pragma: no cover - 理论上不会
                    break
                nxt = text.find(ANCHOR, i + len(ANCHOR))
                end = nxt if nxt > 0 else total
                seg = dict(w)
                seg["text"] = text[i:end]
                seg["x0"] = base + span * (i / total)
                seg["x1"] = base + span * (end / total)
                kept.append(seg)
                anchors.append(seg)
                pos = end if nxt > 0 else total
    kept.sort(key=lambda w: (round(w["top"] / 2.0), w["x0"]))
    return kept, anchors


def _group_lines(words: Sequence[dict], tol: float = 2.5) -> List[dict]:
    """把词按 top 聚成文本行。"""
    lines: List[dict] = []
    for w in sorted(words, key=lambda x: (x["top"], x["x0"])):
        if lines and abs(w["top"] - lines[-1]["top"]) <= tol:
            lines[-1]["words"].append(w)
        else:
            lines.append({"top": w["top"], "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda x: x["x0"])
        ln["text"] = "".join(w["text"] for w in ln["words"])
        ln["x0"] = min(w["x0"] for w in ln["words"])
        ln["x1"] = max(w["x1"] for w in ln["words"])
        ln["bottom"] = max(w["bottom"] for w in ln["words"])
    return lines


def _card_lines(lines: Sequence[dict], anchor_word: dict) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """从“文件名称”所在行开始，把这张卡片的字段行捡出来。

    - 行首可能残留左边格溢出的字（如“支架（改）文件名称:…”），从字段标签处截断
    - “颜色”值太长换行的，紧跟着的一行也算进来
    """
    ai = next((i for i, ln in enumerate(lines) if any(w is anchor_word for w in ln["words"])), None)
    if ai is None:
        return []

    picked: List[Tuple[str, Tuple[float, float, float, float]]] = []
    prev_label = ""
    prev_bottom = None
    skipped = 0
    for k, ln in enumerate(lines[ai:]):
        j = next((i for i, w in enumerate(ln["words"]) if w["text"].startswith(FIELD_LABELS)), None)
        if j is not None:
            ws = ln["words"][j:]
            text = "".join(w["text"] for w in ws)
            if k > 0 and text.startswith(ANCHOR):
                break                      # 撞到下一张卡片的开头，收工
            label = next(l for l in FIELD_LABELS if text.startswith(l))
            box = (min(w["x0"] for w in ws), ln["top"], max(w["x1"] for w in ws), ln["bottom"])
            picked.append((text, box))
            prev_label, prev_bottom = label, ln["bottom"]
            continue
        if picked and prev_label == "颜色" and prev_bottom is not None and ln["top"] - prev_bottom < 8:
            picked.append((ln["text"], (ln["x0"], ln["top"], ln["x1"], ln["bottom"])))
            prev_bottom = ln["bottom"]
            continue
        # 备注/手写/图纸标注这类行：跳过继续往后找字段，别因为几行不是标签就整张收工。
        # 上限放到 20 行：字段被大段说明隔开也还能找回来；真跑飞了还有格子边界兜着。
        skipped += 1
        if skipped > MAX_NOTE_LINES:
            break
    return picked


def parse_card_text(text: str) -> dict:
    """从卡片区域文本里抠字段。"""
    out = {"name": "", "seq": None, "qty": None, "size": "", "color": "", "dwg_no": ""}
    m = NAME_RE.search(text)
    if m:
        out["name"] = m.group(1).strip()
    m = SIZE_RE.search(text)
    if m:
        out["size"] = m.group(1).strip()
    m = SEQ_RE.search(text)
    if m:
        out["seq"] = int(m.group(1))
    m = QTY_RE.search(text)
    if m:
        out["qty"] = int(m.group(1))
    m = COLOR_RE.search(text)
    if m:
        out["color"] = m.group(1).strip()
    m = DWG_NO_RE.search(text)
    if m:
        out["dwg_no"] = m.group(1).strip()
    return out


# ---------------------------------------------------------------- 解析一页

def _page_drawings(page) -> List[Tuple[float, float, float, float]]:
    boxes = []
    for coll in (page.rects, page.lines, page.curves):
        for o in coll:
            boxes.append((o["x0"], o["top"], o["x1"], o["bottom"]))
    return boxes


def parse_page(page, page_no: int, page_h_pt: float) -> PageCards:
    """解析 pdfplumber 的一页。page_h_pt = 该页 PDF 坐标下的高度。"""
    res = PageCards(page_no=page_no)
    words, _hits = _extract_words(page)
    words, anchors = _split_merged_anchors(words)
    if not anchors:
        res.warnings.append(tr("parser.warn.no_anchor", page=page_no))
        return res

    xs = _cluster([a["x0"] for a in anchors])
    ys = _cluster([a["top"] for a in anchors])
    res.cols, res.rows = len(xs), len(ys)

    fallback_w = page.width / max(1, len(xs))
    fallback_h = page.height / max(1, len(ys))
    pitch_x = _pitch(xs, fallback_w)
    pitch_y = _pitch(ys, fallback_h)

    drawings = _page_drawings(page)
    vgrid, hgrid = _grid_positions(drawings, page.width, page.height)

    for a in anchors:
        ci = min(range(len(xs)), key=lambda i: abs(a["x0"] - xs[i]))
        ri = min(range(len(ys)), key=lambda i: abs(a["top"] - ys[i]))
        cx0, cy0 = xs[ci], ys[ri]
        cell = (cx0, cy0, min(cx0 + pitch_x, page.width), min(cy0 + pitch_y, page.height))
        cw, ch = cell[2] - cell[0], cell[3] - cell[1]

        # 卡片字段行：词按“最近的列起点”归属，避免把隔壁格的字吸进来；
        # 行的下界用锚点自身的位置（同一行不同卡片 top 会有 1~2pt 抖动）
        lo = a["top"] - 2.5
        hi = cell[3] - 0.5
        # 归属：既按“最近的列起点”，又要求 x 落在本格范围内 ——
        # 只按最近列起点时，溢出到邻格的字会被吸进来；只按范围时，邻格的孤立词又会串进本卡。
        cell_words = [w for w in words
                      if min(range(len(xs)), key=lambda i: abs(w["x0"] - xs[i])) == ci
                      and cell[0] - 2.0 <= w["x0"] <= cell[2]
                      and lo <= w["top"] <= hi
                      and not PAGE_NOISE.search(w["text"])]
        cell_lines = _group_lines(cell_words)
        picked = _card_lines(cell_lines, a)
        if not picked:
            res.warnings.append(tr("parser.warn.no_fields", page=page_no, row=ri + 1, col=ci + 1))
            continue
        text = "\n".join(t for t, _ in picked)
        fields = parse_card_text(text)
        if not fields["name"]:
            res.warnings.append(tr("parser.warn.no_name", page=page_no, row=ri + 1, col=ci + 1))
            continue

        # 内容包围盒：格内所有文字（含备注）+ 格内图形（排除表格线/外框）
        # 只算从本卡锚点那一列往右的字：左边格溢出来的半个字别进裁剪框
        boxes = [(w["x0"], w["top"], w["x1"], w["bottom"]) for w in cell_words
                 if w["x0"] >= a["x0"] - 2.0]
        for d in drawings:
            if d[0] >= cell[0] - 0.3 and d[1] >= cell[1] - 0.3 and d[2] <= cell[2] + 0.3 and d[3] <= cell[3] + 0.3:
                if _is_rule(d, cell, vgrid, hgrid) or _is_frame(d, cw, ch):
                    continue
                boxes.append(d)

        # 兜底：完全没有图形时只按文字框裁
        content = _bbox_union(boxes)
        if content is None:
            res.warnings.append(tr("parser.warn.no_content", page=page_no, name=fields["name"]))
            continue

        # 贴边裁剪：把紧贴格线的部分让开
        x0, y0, x1, y1 = content
        if x0 < cell[0] + EDGE_PAD_PT:
            x0 = cell[0] + EDGE_PAD_PT
        if y0 < cell[1] + EDGE_PAD_PT:
            y0 = cell[1] + EDGE_PAD_PT
        if x1 > cell[2] - EDGE_PAD_PT:
            x1 = cell[2] - EDGE_PAD_PT
        if y1 > cell[3] - EDGE_PAD_PT:
            y1 = cell[3] - EDGE_PAD_PT
        if x1 - x0 < 5 or y1 - y0 < 5:
            res.warnings.append(tr("parser.warn.bad_box", page=page_no, name=fields["name"]))
            continue

        qty = fields["qty"] if fields["qty"] else 1
        res.cards.append(
            Card(
                name=fields["name"],
                seq=fields["seq"],
                qty=qty,
                size=fields["size"],
                color=fields["color"],
                dwg_no=fields["dwg_no"],
                col=ci,
                row=ri,
                cell_pdf=(cell[0], page_h_pt - cell[3], cell[2], page_h_pt - cell[1]),
                clip_pdf=(x0, page_h_pt - y1, x1, page_h_pt - y0),
            )
        )

    res.cards.sort(key=lambda c: (c.row, c.col))
    return res


# ---------------------------------------------------------------- 解析一份 PDF

def parse_pdf(path: str, first_page_only: bool = False, progress=None) -> PdfCards:
    """解析一份 PDF，返回每页的卡片。"""
    from pypdf import PdfReader

    reader = PdfReader(path)
    n_pages = len(reader.pages)
    result = PdfCards(path=path, n_pages=n_pages)

    with pdfplumber.open(path) as pdf:
        pages = pdf.pages[:1] if first_page_only else pdf.pages
        for idx, page in enumerate(pages):
            try:
                page_h = float(reader.pages[idx].mediabox.height)
            except Exception:                                 # pragma: no cover
                page_h = float(page.height)
            try:
                info = parse_page(page, idx + 1, page_h)
            except Exception as exc:                          # pragma: no cover
                info = PageCards(page_no=idx + 1,
                                 warnings=[tr("parser.warn.page_failed", page=idx + 1, error=exc)])
            result.pages.append(info)
            if progress:
                progress(idx + 1, len(pages))
    return result


def parse_many(paths: Iterable[str], first_page_only: bool = False, progress=None) -> List[PdfCards]:
    out = []
    for p in paths:
        out.append(parse_pdf(p, first_page_only=first_page_only, progress=progress))
    return out
