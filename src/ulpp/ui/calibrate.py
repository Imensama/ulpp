# -*- coding: utf-8 -*-
"""初次校准向导：新拿到的胶纸型号，先量一次尺寸。

一问 + 两条路：
1. 「这台机器能扫描吗？」→ 有扫描仪走扫描件；没有就走标定板拍照；
2. 两条路的终点一样：量出格阵 → 存成「我的纸」→ 回主界面直接用。

应急入口（没有多余 A4、没法打标定板）做成**正常大小、琥珀色的按钮**，旁边直接写清"精度略低"，
不再是灰色小字——用户看不见的选项等于没有。
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from typing import Optional

from ..templates import Template
from . import screens

WARN_COLOR = "#B45309"


class CalibrateWizard(tk.Toplevel):
    """三步：能扫吗 → 扫/拍 → 结果。模态小窗，关掉不影响主界面。"""

    def __init__(self, app) -> None:
        super().__init__(app.root)
        self.app = app
        P, S = app.P, app.S
        self.title(app.T("calib.title"))
        self.configure(bg=P["bg"])
        self.transient(app.root)
        self.resizable(False, False)
        self.step = "ask"
        self.measurement = None
        self.error: Optional[str] = None
        self.source = ""
        self.photo_path: Optional[str] = None
        self.corners: list = []          # 手动点的四个角（原图像素）
        self._drag_index = None
        self._photo = None               # PIL 图，点角时用
        self._img_scale = 1.0
        self._img_off = (0.0, 0.0)
        self._canvas = None

        self.body = tk.Frame(self, bg=P["bg"])
        self.body.pack(fill="both", expand=True, padx=S(24), pady=S(20))
        self.foot = tk.Frame(self, bg=P["bg"])
        self.foot.pack(fill="x", padx=S(24), pady=(0, S(16)))
        self.render()
        self.update_idletasks()
        self._centre()
        try:
            self.grab_set()
        except tk.TclError:      # pragma: no cover
            pass

    # ------------------------------------------------------------ 基础
    def _clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        for child in self.foot.winfo_children():
            child.destroy()

    def _button(self, parent, text, command, kind="soft", size=12):
        app = self.app
        P = app.P
        if kind == "solid":
            fg, bg = P["accent_text"], P["accent"]
        elif kind == "warn":
            fg, bg = "#FFFFFF", WARN_COLOR
        elif kind == "ghost":
            fg, bg = P["text"], P["card"]
        else:
            fg, bg = P["soft_text"], P["soft"]
        return tk.Button(parent, text=text, font=app.F(size, True), fg=fg, bg=bg,
                         activeforeground=fg, activebackground=P["border"],
                         relief="flat", bd=0, padx=app.S(20), pady=app.S(12),
                         highlightthickness=1 if kind == "ghost" else 0,
                         highlightbackground=P["border"], cursor="hand2",
                         command=command, wraplength=app.S(420), justify="left")

    def _title(self, text, size=18):
        tk.Label(self.body, text=text, font=self.app.F(size, True), fg=self.app.P["text"],
                 bg=self.app.P["bg"], anchor="w", justify="left",
                 wraplength=self.app.S(560)).pack(fill="x")

    def _line(self, text, color=None, font_size=11):
        tk.Label(self.body, text=text, font=self.app.F(font_size), fg=color or self.app.P["muted"],
                 bg=self.app.P["bg"], anchor="w", justify="left",
                 wraplength=self.app.S(560)).pack(fill="x", pady=(self.app.S(8), 0))

    def _centre(self) -> None:
        host = self.app.root
        x = host.winfo_rootx() + (host.winfo_width() - self.winfo_width()) // 2
        y = host.winfo_rooty() + (host.winfo_height() - self.winfo_height()) // 3
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))

    # ------------------------------------------------------------ 三步
    def render(self) -> None:
        self._clear()
        if self.step == "corners":
            self._render_corners()
        elif self.step == "result":
            self._render_result()
        elif self.step == "scan":
            self._render_scan()
        elif self.step == "photo":
            self._render_photo()
        else:
            self._render_ask()
        self.update_idletasks()

    def _render_ask(self) -> None:
        app = self.app
        self._title(app.T("calib.ask"))
        self._line(app.T("calib.ask_body"))
        row = tk.Frame(self.body, bg=app.P["bg"])
        row.pack(fill="x", pady=(app.S(18), 0))
        self._button(row, app.T("calib.has_scanner"), self.go_scan, kind="solid",
                     size=13).pack(side="left")
        self._button(row, app.T("calib.no_scanner"), self.go_photo, kind="soft",
                     size=13).pack(side="left", padx=(app.S(12), 0))
        self._line(app.T("calib.ask_hint"), font_size=10)


    def _render_scan(self) -> None:
        app = self.app
        self._title(app.T("calib.scan_title"))
        self._line(app.T("calib.scan_body"))
        self._line(app.T("calib.scan_tip"), font_size=10)
        scan_btn = self._button(self.body, app.T("calib.scan_pick"), self.pick_scan,
                                kind="solid")
        scan_btn.pack(anchor="w", pady=(app.S(18), 0))
        app.bind_drop(scan_btn, self._drop_scan)
        tk.Label(self.body, text=app.T("calib.drop_hint"), font=app.F(9),
                 fg=app.P["muted"], bg=app.P["bg"]).pack(anchor="w")
        if self.error:
            self._line(app.T("calib.fail", err=self.error), color="#B91C1C", font_size=10)
        self._back()

    def _render_photo(self) -> None:
        app = self.app
        self._title(app.T("calib.photo_title"))
        self._line(app.T("calib.photo_body"))
        self._line(app.T("calib.light_hint"), color=WARN_COLOR, font_size=10)
        self._line(app.T("calib.backlight"), font_size=10)
        row = tk.Frame(self.body, bg=app.P["bg"])
        row.pack(fill="x", pady=(app.S(16), 0))
        self._button(row, app.T("calib.print_board"), self.save_board,
                     kind="ghost", size=11).pack(side="left")
        photo_btn = self._button(row, app.T("calib.photo_pick"), self.pick_photo,
                                 kind="solid")
        photo_btn.pack(side="left", padx=(app.S(10), 0))
        app.bind_drop(photo_btn, self._drop_photo)

        # 应急入口：正常大小 + 琥珀色，配一行说明
        warn_box = tk.Frame(self.body, bg=app.P["bg"])
        warn_box.pack(fill="x", pady=(app.S(18), 0))
        plain_btn = self._button(warn_box, app.T("calib.photo_fallback"),
                                 self.pick_photo_plain, kind="warn", size=11)
        plain_btn.pack(anchor="w")
        app.bind_drop(plain_btn, self._drop_plain)
        tk.Label(warn_box, text=app.T("calib.fallback_warn"), font=app.F(10),
                 fg=WARN_COLOR, bg=app.P["bg"], anchor="w", justify="left",
                 wraplength=app.S(560)).pack(fill="x", pady=(app.S(6), 0))

        if self.error:
            self._line(app.T("calib.fail", err=self.error), color="#B91C1C", font_size=10)
        self._back()

    def _render_corners(self) -> None:
        app, P = self.app, self.app.P
        from PIL import Image, ImageTk

        self._title(app.T("calib.corners_title"))
        self._line(app.T("calib.corners_body"))
        if self.error:
            self._line(app.T("calib.fail", err=self.error), color="#B91C1C", font_size=10)
        self._line(app.T("calib.corners_hint"), font_size=10)
        self._line(app.T("calib.backlight"), font_size=9)

        img = Image.open(self.photo_path).convert("RGB")
        box_w, box_h = app.S(720), app.S(500)
        scale = min(box_w / img.width, box_h / img.height)
        shown = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        self._photo = img
        self._img_scale = scale
        self._img_off = ((box_w - shown.width) / 2.0, (box_h - shown.height) / 2.0)
        self._photo_tk = ImageTk.PhotoImage(shown)

        canvas = tk.Canvas(self.body, width=box_w, height=box_h, bg="#111111",
                           highlightthickness=0, cursor="crosshair")
        canvas.pack(pady=(app.S(8), 0))
        canvas.create_image(self._img_off[0], self._img_off[1], anchor="nw", image=self._photo_tk)
        canvas.bind("<Button-1>", self._on_canvas_click)
        canvas.bind("<B1-Motion>", self._on_canvas_drag)
        canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        canvas.configure(cursor="crosshair")
        self._canvas = canvas
        self._redraw_corners()

        self._button(self.foot, app.T("calib.corners_reset"), self._reset_corners,
                     kind="ghost", size=10).pack(side="left")
        self._button(self.foot, app.T("calib.back"),
                     lambda: self.go("photo"), kind="ghost", size=10).pack(
                         side="left", padx=(app.S(8), 0))

        self._go_btn = self._button(self.foot, app.T("calib.corners_go"),
                                    self.measure_corners, kind="solid", size=12)
        self._go_btn.pack(side="right")
        self._sync_go_btn()

    def _sync_go_btn(self) -> None:
        btn = getattr(self, "_go_btn", None)
        if btn is None:
            return
        btn.configure(state="normal" if len(self.corners) == 4 else "disabled",
                      cursor="hand2" if len(self.corners) == 4 else "arrow")

    def _redraw_corners(self) -> None:
        cv = getattr(self, "_canvas", None)
        if cv is None:
            return
        cv.delete("mark")
        cv.delete("quad")
        pts = [self._canvas_xy(x, y) for x, y in self.corners]
        if len(pts) >= 2:
            flat = [c for p in pts for c in p]
            if len(pts) == 4:
                cv.create_polygon(flat, outline="#F59E0B", width=2, fill="#F59E0B",
                                  stipple="gray25", tags="quad")
            else:
                cv.create_line(flat, fill="#F59E0B", width=2, tags="quad")
        for i, ((cx, cy), (x, y)) in enumerate(zip(pts, self.corners)):
            cv.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, outline="#F59E0B",
                           width=3, fill="", tags="mark")
            cv.create_text(cx + 16, cy - 14, text=str(i + 1), fill="#F59E0B",
                           font=self.app.F(12, True), tags="mark")

    def _canvas_xy(self, x: float, y: float):
        return (x * self._img_scale + self._img_off[0],
                y * self._img_scale + self._img_off[1])

    def _hit_corner(self, cx: float, cy: float):
        """点到已有圆点附近就抓住它，用来微调。"""
        for i, (x, y) in enumerate(self.corners):
            px, py = self._canvas_xy(x, y)
            if (px - cx) ** 2 + (py - cy) ** 2 <= 16 ** 2:
                return i
        return None

    def _on_canvas_click(self, event) -> None:
        if self._photo is None:
            return
        hit = self._hit_corner(event.x, event.y)
        if hit is not None:
            self._drag_index = hit
            return
        if len(self.corners) >= 4:
            return
        x = (event.x - self._img_off[0]) / self._img_scale
        y = (event.y - self._img_off[1]) / self._img_scale
        if not (0 <= x <= self._photo.width and 0 <= y <= self._photo.height):
            return
        self.corners.append((x, y))
        self._redraw_corners()
        self._sync_go_btn()

    def _on_canvas_drag(self, event) -> None:
        idx = getattr(self, "_drag_index", None)
        if idx is None or idx >= len(self.corners):
            return
        x = (event.x - self._img_off[0]) / self._img_scale
        y = (event.y - self._img_off[1]) / self._img_scale
        x = max(0.0, min(x, float(self._photo.width)))
        y = max(0.0, min(y, float(self._photo.height)))
        self.corners[idx] = (x, y)
        self._redraw_corners()

    def _on_canvas_release(self, _event) -> None:
        self._drag_index = None

    def _reset_corners(self) -> None:
        self.corners = []
        self._redraw_corners()
        self._sync_go_btn()

    def measure_corners(self) -> None:
        from ..scan_calib import measure_photo_corners

        if len(self.corners) != 4 or not self.photo_path:
            return
        grid = self._grid()
        try:
            self.source = self.photo_path
            self._finish(measure_photo_corners(self.photo_path, self.corners,
                                               expect_cols=grid.cols,
                                               expect_rows=grid.rows))
            self.measurement_plain = False
        except Exception as exc:
            self.error = str(exc)
            self.step = "corners"
            self.render()

    def _render_result(self) -> None:
        app, m = self.app, self.measurement
        self._title(app.T("calib.result_title"))
        if m is None:
            return
        lines = [
            app.T("calib.result_spec", cols=m.cols, rows=m.rows,
                  px=m.pitch_x_mm, py=m.pitch_y_mm),
            app.T("calib.result_conf", conf=m.confidence),
        ]
        for text in lines:
            tk.Label(self.body, text=text, font=app.F(13), fg=app.P["text"],
                     bg=app.P["bg"], anchor="w").pack(fill="x", pady=(app.S(6), 0))
        if m.warnings:
            tk.Label(self.body, text="\n".join(m.warnings), font=app.F(9),
                     fg=app.P["muted"], bg=app.P["bg"], anchor="w", justify="left",
                     wraplength=app.S(560)).pack(fill="x", pady=(app.S(8), 0))
        self._button(self.foot, app.T("calib.save"), self.save_template,
                     kind="solid", size=12).pack(side="right")
        self._button(self.foot, app.T("calib.again"), self.back_to_pick,
                     kind="ghost", size=10).pack(side="right", padx=(0, app.S(10)))

    def _back(self) -> None:
        app = self.app
        self._button(self.foot, app.T("calib.back"),
                     lambda: self.go("ask"), kind="ghost", size=10).pack(side="left")

    # ------------------------------------------------------------ 动作
    def go(self, step: str) -> None:
        self.step = step
        self.error = None
        self.render()

    def go_ruler(self) -> None:
        """看不清刻线 → 直接去高级参数手填四个数（同一个对话框，不重复做一套）。"""
        self.destroy()
        self.app.open_advanced()

    def go_scan(self) -> None:
        self.go("scan")

    def go_photo(self) -> None:
        self.go("photo")

    def _grid(self):
        return screens._selected(self.app).to_grid()

    def _finish(self, measurement) -> None:
        self.measurement = measurement
        self.step = "result"
        self.error = None
        self.render()

    def pick_scan(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=self.app.T("calib.scan_pick"),
            filetypes=[("扫描件", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff"),
                       ("所有文件", "*.*")], parent=self)
        if path:
            self._measure_scan(path)

    def _measure_scan(self, path: str) -> None:
        from ..scan import measure_file

        grid = self._grid()
        try:
            self.source = path
            self._finish(measure_file(path, expect_cols=grid.cols, expect_rows=grid.rows))
        except Exception as exc:
            self.error = str(exc)
            self.render()

    def pick_photo(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=self.app.T("calib.photo_pick"),
            filetypes=[("照片 JPG/PNG", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"),
                       ("所有文件", "*.*")], parent=self)
        if path:
            self._try_photo(path)

    def _drop_scan(self, path) -> None:
        if path:
            self._measure_scan(path)

    def _drop_photo(self, path) -> None:
        if path:
            self._try_photo(path)

    def _drop_plain(self, path) -> None:
        if path:
            self._measure_plain(path)

    def _try_photo(self, path: str) -> None:
        """先试全自动；认不出纸边就转"手动点四个角"，不把用户卡死。"""
        from ..scan_calib import measure_photo_calibrated

        grid = self._grid()
        try:
            self.source = path
            self._finish(measure_photo_calibrated(path, expect_cols=grid.cols,
                                                  expect_rows=grid.rows))
        except Exception as exc:
            self.photo_path = path
            self.corners = []
            self.error = str(exc)
            self.step = "corners"
            self.render()

    def pick_photo_plain(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=self.app.T("calib.photo_fallback"),
            filetypes=[("照片 JPG/PNG", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"),
                       ("所有文件", "*.*")], parent=self)
        if path:
            self._measure_plain(path)

    def _measure_plain(self, path: str) -> None:
        from ..scan_photo import measure_photo

        grid = self._grid()
        try:
            self.source = path
            self.measurement_plain = True
            self._finish(measure_photo(path, expect_cols=grid.cols, expect_rows=grid.rows))
        except Exception as exc:
            self.photo_path = path
            self.corners = []
            self.error = str(exc)
            self.step = "corners"
            self.render()

    def save_board(self) -> None:
        from tkinter import filedialog
        from ..scan_board import make_board_pdf

        path = filedialog.asksaveasfilename(
            title=self.app.T("calib.print_board"), defaultextension=".pdf",
            initialfile="ulpp标定板.pdf", filetypes=[("PDF", "*.pdf")], parent=self)
        if not path:
            return
        try:
            make_board_pdf(path)
            self.app._open_path(path)
        except Exception as exc:
            self.error = str(exc)
            self.render()

    def back_to_pick(self) -> None:
        self.measurement = None
        self.go("photo" if getattr(self, "measurement_plain", False) else "scan")

    def save_template(self) -> None:
        app, m = self.app, self.measurement
        if m is None:
            return
        grid = self._grid()
        tpl = Template(
            id=Template.new_id("calib"), name=app.T("calib.tpl_name", cols=m.cols, rows=m.rows),
            cols=m.cols, rows=m.rows,
            cell_w_mm=m.cell_w_mm, cell_h_mm=m.cell_h_mm,
            pitch_x_mm=m.pitch_x_mm, pitch_y_mm=m.pitch_y_mm,
            origin_x_mm=m.first_x_mm, origin_y_mm=m.first_y_mm,
            page_w_mm=grid.page_w, page_h_mm=grid.page_h,
            rotation_deg=m.rotation_deg, confidence=m.confidence,
            source="scan:" + os.path.basename(self.source or ""),
        )
        app.templates.upsert(tpl)
        app.flow.answer("paper", "tpl:" + tpl.id)
        app.save()
        app.render()
        self.destroy()
