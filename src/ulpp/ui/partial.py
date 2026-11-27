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
from tkinter import filedialog
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
CELL_UNSURE = "#FDBA74"                     # 扫描拿不准的格
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
        self.scan_verdict = None            # 最近一次扫描识别的结论
        self.scan_summary = ""              # 界面上那行摘要
        self.scan_warnings: List[str] = []  # 读不全之类的提示（琥珀色小字）
        self.scan_added: List[int] = []     # 这次扫描新标上的格子
        self._canvas: Optional[tk.Canvas] = None
        self._grid_geo = None               # (x_base, y_base, cell_w, cell_h, head, cols, rows)
        self._remain_label: Optional[tk.Label] = None
        self._unsure: set = set()
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
        """优先打开「跟当前选中的纸对得上」的那张记录，对不上就按当前纸新建。

        原来总取存档里最后一张，导致在第 1 站换了纸型、这里还是老格阵（用户会以为没联动）。
        """
        if self.store is None:
            return
        current = self.app._selected_grid()
        match = None
        for record in reversed(self.store.sheets):
            if record.grid_spec == current:      # GridSpec 是 dataclass，逐字段比较
                match = record
                break
        if match is None:
            self._new_sheet()
            return
        self.sheet = match
        self.sheet_var.set(match.name)

    def _new_sheet(self) -> None:
        if self.store is None:
            return
        base = self.app._selected_grid()          # 当前选中的纸
        try:
            self.sheet = self.store.add_sheet("接着打", base)
            self.sheet_var.set(self.sheet.name)   # 下拉框跟着改，否则显示空白
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
            self._draw_orient_hint()

        # ---- 右栏 ----
        tk.Label(self.right, text=app.T("partial.sheet"), font=app.F(10), fg=P["muted"],
                 bg=P["bg"], anchor="w").pack(fill="x")
        names = [s.name for s in (self.store.sheets if self.store else [])]
        combo = ttk.Combobox(self.right, textvariable=self.sheet_var, values=names,
                             state="readonly", width=26, font=app.F(11))
        combo.pack(fill="x", pady=(S(4), 0))
        combo.bind("<<ComboboxSelected>>", self._on_pick)
        if self.sheet is not None:
            g = self.sheet.grid_spec
            tk.Label(self.right, text=app.T("partial.grid_info", cols=g.cols, rows=g.rows,
                                       cell_w=g.cell_w, cell_h=g.cell_h),
                     font=app.F(9), fg=P["muted"], bg=P["bg"], anchor="w").pack(fill="x")

        if self.sheet is not None:
            self._remain_label = tk.Label(
                self.right,
                text=app.T("partial.remaining", free=self.sheet.free_count,
                           total=self.sheet.per_sheet),
                font=app.F(14, True), fg=P["text"], bg=P["bg"], anchor="w")
            self._remain_label.pack(fill="x", pady=(S(14), 0))
        else:
            self._remain_label = None

        if self.scan_summary:
            tk.Label(self.right, text=self.scan_summary, font=app.F(10), fg=P["text"],
                     bg=P["bg"], anchor="w", justify="left",
                     wraplength=S(360)).pack(fill="x", pady=(S(8), 0))
            tk.Label(self.right, text=app.T("partial.scan_hint"), font=app.F(10),
                     fg=P["muted"], bg=P["bg"], anchor="w", justify="left",
                     wraplength=S(360)).pack(fill="x", pady=(S(4), 0))
            for line in self.scan_warnings[:2]:
                tk.Label(self.right, text=line, font=app.F(9), fg="#B45309",
                         bg=P["bg"], anchor="w", justify="left",
                         wraplength=S(360)).pack(fill="x", pady=(S(4), 0))

        lines = len(parse_text_block(self.app.content_text or ""))
        has_content = bool(app.files or app.images or lines)
        info = app.T("partial.content", files=len(app.files), images=len(app.images),
                     lines=lines) if has_content else app.T("partial.none")
        tk.Label(self.right, text=info, font=app.F(10), fg=P["muted"], bg=P["bg"],
                 anchor="w", justify="left", wraplength=S(360)).pack(fill="x", pady=(S(8), 0))

        # 两种顺序都支持：可以先在格子图里定好能打哪儿，再从这里挑文件；
        # 也可以先在主界面放好内容再进来。
        picker = tk.Frame(self.right, bg=P["bg"])
        picker.pack(fill="x", pady=(S(6), 0))
        AppButton(picker, app.T("partial.add_files"), self._add_files,
                  button_type="info", palette=P, font=app.F, scale=S,
                  size="sm").pack(side="left")
        AppButton(picker, app.T("partial.add_text_hint"), self._back_to_text,
                  button_type="cancel", palette=P, font=app.F, scale=S,
                  size="sm").pack(side="left", padx=(S(8), 0))

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
        if self.sheet is not None:
            # 扫一张半张纸，自动标出已经用掉的格，省掉一格一格点
            AppButton(self._foot, app.T("partial.scan"), self._scan_used,
                      button_type="info", palette=app.P, font=app.F,
                      scale=app.S, size="md").pack(side="left", padx=(S(8), 0))
        if self.sheet is not None and self.sheet.free_count:
            AppButton(self._foot, app.T("partial.gen"), self.generate,
                      button_type="submit", palette=app.P, font=app.F,
                      scale=app.S, size="md").pack(side="right",
                                                  padx=(0, S(8)))

    def _draw_orient_hint(self) -> None:
        """右栏一句「怎么塞纸」：方向取自向导存的打印机配置，不提纸面标记。

        纸面箭头那套改成可选功能（默认关），这里只说进纸方向，剩下的交给用户自己认边。
        """
        app, S, P = self.app, self.app.S, self.app.P
        tk.Label(self.right, text=app.T("partial.orient_hint", dir=app.direction_label()),
                 font=app.F(10), fg=P["muted"], bg=P["bg"], anchor="w", justify="left",
                 wraplength=S(340)).pack(fill="x", pady=(S(12), 0))

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
        self._unsure = set(self.scan_verdict.unsure) if self.scan_verdict is not None else set()
        self._cell_rects = {}
        for i in range(grid.per_sheet):
            col, row = i % grid.cols, i // grid.cols
            x0 = x_base + col * cell_w
            y0 = y_base + row * cell_h
            rect = cv.create_rectangle(x0 + 1, y0 + 1, x0 + cell_w - 1, y0 + cell_h - 1,
                                       fill=self._cell_fill(i),
                                       outline=CELL_LINE, width=max(1, S(1) // 2))
            self._cell_rects[i] = rect
            # 格子编号：和参考版 PDF 上的编号一致，方便对着实物勾
            cv.create_text(x0 + S(7), y0 + S(7), text=str(i + 1), fill="#64748B",
                           font=tiny, anchor="w")
        # 行/列头：点一下整行、整列一起切
        for c in range(grid.cols):
            x0 = x_base + c * cell_w
            cv.create_rectangle(x0 + 1, S(10) + 1, x0 + cell_w - 1, S(10) + head - 1,
                                fill=app.P["chip"], outline=CELL_LINE,
                                width=max(1, S(1) // 2), tags=("colhead", "c%d" % c))
            cv.create_text(x0 + cell_w // 2, S(10) + head // 2, text=str(c + 1),
                           fill=app.P["muted"], font=app.F(9, True),
                           tags=("colhead", "c%d" % c))
        for r in range(grid.rows):
            y0 = y_base + r * cell_h
            cv.create_rectangle(S(10) + 1, y0 + 1, S(10) + head - 1, y0 + cell_h - 1,
                                fill=app.P["chip"], outline=CELL_LINE,
                                width=max(1, S(1) // 2), tags=("rowhead", "r%d" % r))
            cv.create_text(S(10) + head // 2, y0 + cell_h // 2, text=str(r + 1),
                           fill=app.P["muted"], font=app.F(9, True),
                           tags=("rowhead", "r%d" % r))

        # 整块画布一个点击处理器：点在数字上、边线上都算点中那格（原来是逐个矩形绑事件，
        # 数字盖在上面会吃掉点击，用户感觉"不跟手"）。
        self._grid_geo = (x_base, y_base, cell_w, cell_h, head, grid.cols, grid.rows)
        cv.bind("<Button-1>", self._on_grid_click)

    def _cell_fill(self, slot: int) -> str:
        """格子底色：灰=已用、橙=扫描拿不准、白=还能打。"""
        if not self.sheet.is_free(slot):
            return CELL_USED
        if slot in self._unsure:
            return CELL_UNSURE
        return CELL_FREE

    def _on_grid_click(self, event) -> None:
        """按坐标判断点的是格子、行头还是列头。"""
        if self.sheet is None or self._grid_geo is None:
            return
        x_base, y_base, cell_w, cell_h, head, cols, rows = self._grid_geo
        col = (event.x - x_base) // cell_w if event.x >= x_base else -1
        row = (event.y - y_base) // cell_h if event.y >= y_base else -1
        if 0 <= row < rows and 0 <= col < cols:
            self._toggle(int(row * cols + col))
        elif event.y < y_base and 0 <= col < cols:
            self._toggle_column(int(col))
        elif event.x < x_base and 0 <= row < rows:
            self._toggle_row(int(row))

    def _refresh_cells(self) -> None:
        """只重画格子底色和"还能打"那行，不重建整个窗口（重建会让点击发飘）。"""
        if self._canvas is None or self.sheet is None:
            return
        for slot, rect in self._cell_rects.items():
            self._canvas.itemconfigure(rect, fill=self._cell_fill(slot))
        if self._remain_label is not None:
            self._remain_label.configure(
                text=self.app.T("partial.remaining", free=self.sheet.free_count,
                                total=self.sheet.per_sheet))

    def _toggle_line(self, slots: list) -> None:
        """整行/整列：全都用掉了就全放开，否则全部标成用掉。"""
        if self.sheet is None or not slots:
            return
        if all(not self.sheet.is_free(s) for s in slots):
            self.sheet.mark_free(slots)
        else:
            self.sheet.mark_used(slots)
        self._save_store()
        self._refresh_cells()

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
        self._refresh_cells()          # 局部重画：整窗 refresh 会让连点发飘

    # ------------------------------------------------------------ 自动识别
    def _scan_used(self) -> None:
        """扫一张半张纸，自动把「已用」的格标上；拿不准的标橙色，点一下即可采纳。"""
        from ..partial_scan import analyze, describe

        if self.sheet is None:
            return
        path = filedialog.askopenfilename(
            title=self.app.T("partial.scan_title"),
            filetypes=[("扫描件 / 照片 / PDF", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp"),
                       ("所有文件", "*.*")])
        if not path:
            return
        verdict = analyze(path, self.sheet.grid_spec)
        self.scan_verdict = verdict
        if not verdict.ok:
            reason = (verdict.warnings[0][6:] if verdict.warnings
                      and verdict.warnings[0].startswith("fail: ") else "")
            self.scan_summary = ""
            self.scan_warnings = []
            self.error = self.app.T("partial.scan_fail", err=reason or "?")
            self.refresh()
            return
        if verdict.used:
            # 记下"这次真正新标了几格"：如果之前已经标过，界面上看不出变化，
            # 不说明白会让人以为识别没生效。
            self.scan_added = [i for i in verdict.used if self.sheet.is_free(i)]
            self.sheet.mark_used(verdict.used)
        else:
            self.scan_added = []
        self.error = None
        self.scan_summary = describe(verdict)
        if verdict.used and not self.scan_added:
            self.scan_summary += self.app.T("partial.scan_nochange",
                                            n=len(verdict.used))
        elif self.scan_added:
            self.scan_summary += self.app.T("partial.scan_added", n=len(self.scan_added))
        self.scan_warnings = [w.split(": ", 1)[-1] for w in verdict.warnings]
        self._save_store()
        self.refresh()

    # ------------------------------------------------------------ 备料
    def _add_files(self) -> None:
        """在接着打窗口里直接挑文件，不必先跑一趟主界面。"""
        self.app.pick_pdfs()
        self.error = None
        self.refresh()

    def _back_to_text(self) -> None:
        """文字标签得在主界面那个框里写：关掉本窗口，把焦点交回去。"""
        self.destroy()
        try:
            self.app.focus_text()
        except Exception:            # 老外壳没有这个方法时静默跳过
            pass

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
                orient=bool(getattr(app, "make_orient", None) and app.make_orient.get()),
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
