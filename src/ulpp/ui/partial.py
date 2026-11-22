# -*- coding: utf-8 -*-
"""接着打：用上次没用完的那半张纸。

做法很轻：左边一张可点的格子图（点一下切换"用过 / 还能打"），右边显示这件纸上还剩几格、
内容从哪来，点一次就只把内容排进空格子；生成后自动把用掉的格子记进这张纸。

引擎是老的 ``build_partial_all``（v1 就在用），这里只做界面和"记格子"。
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Dict, List, Optional

from ..builder import build_partial_all, collect_entries
from ..parser import parse_many
from ..partial import plan_placements
from ..sheets import SheetStore
from ..textlabel import parse_text_block

from .buttons import AppButton

CELL_FREE = "#FFFFFF"
CELL_USED = "#D8DEE9"
CELL_LINE = "#94A3B8"


class PartialWindow(tk.Toplevel):
    def __init__(self, app) -> None:
        super().__init__(app.root)
        self.app = app
        P, S = app.P, app.S
        self.title(app.T("partial.title"))
        self.configure(bg=P["bg"])
        self.transient(app.root)
        self.resizable(False, False)
        self.store: Optional[SheetStore] = app.store
        if self.store is None:
            try:
                self.store = SheetStore.load()
            except Exception:
                self.store = None
        self.sheet = None
        self.output_path: Optional[str] = None
        self.error: Optional[str] = None
        self.leftover = 0
        self._canvas: Optional[tk.Canvas] = None
        self._cell_rects: Dict[int, int] = {}

        self.sheet_var = app.keep(tk.StringVar())
        self._pick_initial()

        wrap = tk.Frame(self, bg=P["bg"])
        wrap.pack(fill="both", expand=True, padx=S(22), pady=S(18))
        tk.Label(wrap, text=app.T("partial.title"), font=app.F(16, True), fg=P["text"],
                 bg=P["bg"], anchor="w").pack(fill="x")
        tk.Label(wrap, text=app.T("partial.body"), font=app.F(10), fg=P["muted"],
                 bg=P["bg"], anchor="w", justify="left",
                 wraplength=S(620)).pack(fill="x", pady=(S(4), S(12)))

        body = tk.Frame(wrap, bg=P["bg"])
        body.pack(fill="both", expand=True)

        self.left = tk.Frame(body, bg=P["card"], highlightthickness=1,
                             highlightbackground=P["border"])
        self.left.pack(side="left", fill="y")
        self.right = tk.Frame(body, bg=P["bg"])
        self.right.pack(side="left", fill="both", expand=True, padx=(S(20), 0))

        foot = tk.Frame(wrap, bg=P["bg"])
        foot.pack(fill="x", pady=(S(12), 0))
        self._foot = foot
        self.refresh()

        self.update_idletasks()
        self._centre()
        try:
            self.grab_set()
        except tk.TclError:      # pragma: no cover
            pass

    # ------------------------------------------------------------ 数据
    def _pick_initial(self) -> None:
        if self.store is None:
            return
        if not self.store.sheets:
            self._new_sheet()
        self.sheet = self.store.sheets[-1]
        if self.sheet is not None:
            self.sheet_var.set(self.sheet.name)

    def _new_sheet(self) -> None:
        if self.store is None:
            return
        base = self.app._selected_grid()          # 当前选中的纸
        try:
            self.sheet = self.store.add_sheet("接着打", base)
            self._save_store()
        except Exception as exc:
            self.error = str(exc)

    def _save_store(self) -> None:
        if self.store is None:
            return
        try:
            self.store.save()
        except Exception:
            pass        # 配置目录不可写时只留在内存里

    # ------------------------------------------------------------ 渲染
    def refresh(self) -> None:
        app, P, S = self.app, self.app.P, self.app.S
        if self.sheet is None:
            self.error = app.T("partial.none")
        for child in self.right.winfo_children():
            child.destroy()
        for child in self.left.winfo_children():
            child.destroy()
        for child in self._foot.winfo_children():
            child.destroy()

        if self.sheet is not None:
            self._draw_grid()

        # ---- 右栏 ----
        tk.Label(self.right, text=app.T("partial.sheet"), font=app.F(10), fg=P["muted"],
                 bg=P["bg"], anchor="w").pack(fill="x")
        names = [s.name for s in (self.store.sheets if self.store else [])]
        combo = ttk.Combobox(self.right, textvariable=self.sheet_var, values=names,
                             state="readonly", width=26, font=app.F(11))
        combo.pack(fill="x", pady=(S(4), 0))
        combo.bind("<<ComboboxSelected>>", self._on_pick)

        if self.sheet is not None:
            tk.Label(self.right,
                     text=app.T("partial.remaining", free=self.sheet.free_count,
                                total=self.sheet.per_sheet),
                     font=app.F(14, True), fg=P["text"], bg=P["bg"], anchor="w").pack(
                fill="x", pady=(S(14), 0))

        lines = len(parse_text_block(self.app.content_text or ""))
        info = app.T("partial.content", files=len(app.files), images=len(app.images),
                     lines=lines) \
            if (app.files or app.images or lines) else app.T("partial.none")
        tk.Label(self.right, text=info, font=app.F(10), fg=P["muted"], bg=P["bg"],
                 anchor="w", justify="left", wraplength=S(360)).pack(fill="x", pady=(S(8), 0))

        if self.error:
            tk.Label(self.right, text=app.T("partial.fail", err=self.error), font=app.F(10),
                     fg="#B91C1C", bg=P["bg"], anchor="w", justify="left",
                     wraplength=S(360)).pack(fill="x", pady=(S(8), 0))
        if self.leftover:
            tk.Label(self.right, text=app.T("partial.leftover", n=self.leftover),
                     font=app.F(10), fg="#B45309", bg=P["bg"], anchor="w",
                     justify="left", wraplength=S(360)).pack(fill="x", pady=(S(6), 0))
        if self.output_path:
            tk.Label(self.right, text=app.T("partial.done", name=Path(self.output_path).name),
                     font=app.F(11, True), fg=P["soft_text"], bg=P["bg"], anchor="w").pack(
                fill="x", pady=(S(8), 0))

        # ---- 页脚 ----
        AppButton(self._foot, app.T("partial.close"), self.destroy,
                  button_type="cancel", palette=app.P, font=app.F,
                  scale=app.S, size="md").pack(side="right")
        if self.output_path:
            AppButton(self._foot, app.T("partial.open"), self._open,
                      button_type="info", palette=app.P, font=app.F,
                      scale=app.S, size="md").pack(side="right", padx=(0, S(8)))
        AppButton(self._foot, app.T("partial.new"), self._on_new,
                  button_type="info", palette=app.P, font=app.F,
                  scale=app.S, size="md").pack(side="left")
        if self.sheet is not None and self.sheet.free_count:
            AppButton(self._foot, app.T("partial.gen"), self.generate,
                      button_type="submit", palette=app.P, font=app.F,
                      scale=app.S, size="md").pack(side="right",
                                                  padx=(0, S(8)))

    def _draw_grid(self) -> None:
        app, S = self.app, self.app.S
        grid = self.sheet.grid_spec
        cell_w, cell_h = S(30), S(24)
        head = S(18)
        width = S(10) + head + cell_w * grid.cols + S(10)
        height = S(10) + head + cell_h * grid.rows + S(10)
        cv = tk.Canvas(self.left, width=width, height=height, bg=app.P["card"],
                       highlightthickness=0)
        cv.pack(padx=S(8), pady=S(8))
        self._canvas = cv
        x_base, y_base = S(10) + head, S(10) + head
        tiny = app.F(8)
        for i in range(grid.per_sheet):
            col, row = i % grid.cols, i // grid.cols
            x0 = x_base + col * cell_w
            y0 = y_base + row * cell_h
            free = self.sheet.is_free(i)
            rect = cv.create_rectangle(x0 + 1, y0 + 1, x0 + cell_w - 1, y0 + cell_h - 1,
                                       fill=CELL_FREE if free else CELL_USED,
                                       outline=CELL_LINE, width=max(1, S(1) // 2))
            cv.tag_bind(rect, "<Button-1>", lambda _e, slot=i: self._toggle(slot))
            # 格子编号：和参考版 PDF 上的编号一致，方便对着实物勾
            cv.create_text(x0 + S(7), y0 + S(7), text=str(i + 1), fill="#64748B",
                           font=tiny, anchor="w")
        # 行/列头：点一下整行、整列一起切
        for c in range(grid.cols):
            x0 = x_base + c * cell_w
            box = cv.create_rectangle(x0 + 1, S(10) + 1, x0 + cell_w - 1, S(10) + head - 1,
                                      fill=app.P["chip"], outline=CELL_LINE,
                                      width=max(1, S(1) // 2))
            txt = cv.create_text(x0 + cell_w // 2, S(10) + head // 2, text=str(c + 1),
                                 fill=app.P["muted"], font=app.F(9, True))
            for item in (box, txt):
                cv.tag_bind(item, "<Button-1>", lambda _e, col=c: self._toggle_column(col))
        for r in range(grid.rows):
            y0 = y_base + r * cell_h
            box = cv.create_rectangle(S(10) + 1, y0 + 1, S(10) + head - 1, y0 + cell_h - 1,
                                      fill=app.P["chip"], outline=CELL_LINE,
                                      width=max(1, S(1) // 2))
            txt = cv.create_text(S(10) + head // 2, y0 + cell_h // 2, text=str(r + 1),
                                 fill=app.P["muted"], font=app.F(9, True))
            for item in (box, txt):
                cv.tag_bind(item, "<Button-1>", lambda _e, row=r: self._toggle_row(row))

    def _toggle_line(self, slots: list) -> None:
        """整行/整列：全都用掉了就全放开，否则全部标成用掉。"""
        if self.sheet is None or not slots:
            return
        if all(not self.sheet.is_free(s) for s in slots):
            self.sheet.mark_free(slots)
        else:
            self.sheet.mark_used(slots)
        self._save_store()
        self.refresh()

    def _toggle_row(self, row: int) -> None:
        if self.sheet is None:
            return
        cols = self.sheet.grid_spec.cols
        self._toggle_line([row * cols + c for c in range(cols)])

    def _toggle_column(self, col: int) -> None:
        if self.sheet is None:
            return
        rows = self.sheet.grid_spec.rows
        cols = self.sheet.grid_spec.cols
        self._toggle_line([r * cols + col for r in range(rows)])

    # ------------------------------------------------------------ 交互
    def _on_pick(self, _event=None) -> None:
        name = self.sheet_var.get()
        for sheet in (self.store.sheets if self.store else []):
            if sheet.name == name:
                self.sheet = sheet
                break
        self.output_path = None
        self.error = None
        self.refresh()

    def _on_new(self) -> None:
        self._new_sheet()
        if self.sheet is not None:
            self.sheet_var.set(self.sheet.name)
        self.output_path = None
        self.refresh()

    def _toggle(self, slot: int) -> None:
        if self.sheet is None:
            return
        if self.sheet.is_free(slot):
            self.sheet.mark_used([slot])
        else:
            self.sheet.mark_free([slot])
        self._save_store()
        self.refresh()

    # ------------------------------------------------------------ 生成
    def generate(self) -> None:
        app = self.app
        if self.sheet is None:
            return
        text = app.content_text or ""
        items = parse_text_block(text)
        if not app.files and not app.images and not items:
            self.error = app.T("partial.none")
            self.refresh()
            return
        self.error = None
        self.output_path = None
        try:
            pdfs = [parse_many([f], first_page_only=bool(app.first_page_only.get()))[0]
                    for f in app.files]
            entries = collect_entries(pdfs, items, app.images)
            free = self.sheet.free_cells
            if not entries:
                raise ValueError(app.T("partial.none"))
            placements, self.leftover = plan_placements(free, entries)
            grid = self.sheet.grid_spec
            outs = build_partial_all(
                placements, grid, app._out_dir(),
                base_name=app.base_name.get().strip() or "标签",
                make_csv=bool(app.make_csv.get()),
                text_align=app.text_align.get(),
                text_uniform=bool(app.text_uniform.get()))
            self.output_path = outs.get("production")
            self.sheet.mark_used(placements.keys())
            self._save_store()
        except Exception as exc:
            self.error = str(exc)
        self.refresh()

    def _open(self) -> None:
        if self.output_path:
            self.app._open_path(self.output_path)

    def _centre(self) -> None:
        host = self.app.root
        x = host.winfo_rootx() + (host.winfo_width() - self.winfo_width()) // 2
        y = host.winfo_rooty() + (host.winfo_height() - self.winfo_height()) // 3
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))
