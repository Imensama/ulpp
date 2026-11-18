# -*- coding: utf-8 -*-
"""初次校准向导：新拿到的胶纸型号，先量一次尺寸。

一问 + 两条路：
1. 「这台机器能扫描吗？」→ 有扫描仪走扫描件；没有就走标定板拍照；
2. 两条路的终点一样：量出格阵 → 存成「我的纸」→ 回主界面直接用。

应急入口（没有多余 A4、没法打标定板）做成**正常大小、琥珀色的按钮**，旁边直接写清"精度略低"，
不再是灰色小字——用户看不见的选项等于没有。
"""
from __future__ import annotations

import math
import os
import tkinter as tk
from pathlib import Path
from typing import Optional

from ..templates import Template
from . import screens

WARN_COLOR = "#B45309"


class CalibrateWizard(tk.Toplevel):
    """初次校准：先问"手边有什么设备"，然后**一路下一步**走完，不再摆一排按钮。

    三条路线：
    - 扫描仪：最准，直接选扫描件
    - 打印机：打标定板 → 拍一张 → （认不出纸边就点四角）→ 结果
    - 都没有：只拍胶纸靠纸边估，界面上明确标"精度略低"
    """

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
        self.corners: list = []
        self.measurement_plain = False
        self._drag_index = None
        self._press = None
        self._moved = False
        self._press_dot = None
        self._photo = None
        self._base_scale = 1.0
        self._zoom = 1.0
        self._img_off = (0.0, 0.0)
        self._canvas = None
        self._box = (0, 0)
        self._go_btn = None

        # 先把底部（按钮栏 + 分隔线）占好位置，再让 body 填剩下的——
        # 反过来的话 body 会把 foot 挤出窗口，按钮就"消失"了。
        self.foot = tk.Frame(self, bg=P["bg"])
        self.foot.pack(side="bottom", fill="x", padx=S(24), pady=(S(10), S(14)))
        self.rule = tk.Frame(self, bg="#CBD5E1", height=1)
        self.rule.pack(side="bottom", fill="x")
        self.body = tk.Frame(self, bg=P["bg"], width=S(470))
        self.body.pack(fill="both", expand=True, padx=S(44), pady=(S(22), S(4)))
        self.render()
        self.update_idletasks()
        self._centre()
        try:
            self.grab_set()
        except tk.TclError:              # pragma: no cover
            pass

    # ------------------------------------------------------------ 基础件
    def _clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        for child in self.foot.winfo_children():
            child.destroy()

    def _button(self, parent, text, command, kind="soft", size=12):
        app, P = self.app, self.app.P
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

    def _gradient_image(self, width, height, radius, colors, bg):
        """生成圆角渐变按钮图（运行时画，不增加图片文件）。"""
        from PIL import Image, ImageDraw

        a, b = colors[0], colors[1]
        grad = Image.new("RGB", (1, height))
        px = grad.load()
        for y in range(height):
            t = y / max(1, height - 1)
            px[0, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
        grad = grad.resize((width, height))
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, width - 1, height - 1],
                                               radius=radius, fill=255)
        base = Image.new("RGB", (width, height), bg)
        base.paste(grad, (0, 0), mask)
        from PIL import ImageTk

        return ImageTk.PhotoImage(base)

    def _hex_rgb(self, value):
        value = value.lstrip("#")
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

    def _round_button(self, parent, text, command, primary, width, height=None,
                      radius=None, size=13):
        """Canvas 画的圆角按钮（Tk 原生按钮没法圆角）。"""
        app, P = self.app, self.app.P
        height = height or app.S(56)
        radius = radius if radius is not None else app.S(12)
        fill = P["accent"] if primary else P["card"]
        fg = P["accent_text"] if primary else P["text"]
        edge = P["accent"] if primary else "#9DB4B8"
        canvas = tk.Canvas(parent, width=width, height=height, bg=P["bg"],
                           highlightthickness=0, cursor="hand2")
        r = min(radius, height / 2 - 1)

        def _round_points():
            pts = []
            corners = ((width - r, r, -90, 0), (width - r, height - r, 0, 90),
                       (r, height - r, 90, 180), (r, r, 180, 270))
            for cx, cy, a0, a1 in corners:
                for i in range(9):
                    ang = math.radians(a0 + (a1 - a0) * i / 8.0)
                    pts.extend([cx + r * math.cos(ang), cy + r * math.sin(ang)])
            return pts

        def shape(color):
            return canvas.create_polygon(_round_points(), fill=color, outline=edge,
                                         width=1 if primary else 2)

        gradient = os.environ.get("ULPP_GRAD", "off") if primary else ""
        if gradient in ("", "off", "0", "no"):
            gradient = ""
        if gradient:
            c1 = P["accent"]
            c2 = P.get("accent2") or P["accent"]
            photo = self._gradient_image(int(width), int(height), int(r),
                                         (self._hex_rgb(c1), self._hex_rgb(c2)),
                                         self._hex_rgb(P["bg"]))
            canvas.create_image(0, 0, anchor="nw", image=photo)
            canvas.image = photo
            body = canvas.create_polygon(_round_points(), fill="", outline=edge, width=1)
        else:
            body = shape(fill)
        label = canvas.create_text(width / 2, height / 2, text=text, fill=fg,
                                   font=app.F(size, True))
        for item in (body, label):
            canvas.tag_bind(item, "<Button-1>", lambda _e: command())
        canvas.tag_bind(body, "<Enter>", lambda _e: canvas.itemconfigure(body, fill=edge))
        canvas.tag_bind(body, "<Leave>", lambda _e: canvas.itemconfigure(body, fill=fill))
        return canvas

    def _choice(self, parent, left_text, left_cmd, right_text, right_cmd):
        """左右二选一：直角按钮，两个平分内容宽度。"""
        app, P = self.app, self.app.P
        row = tk.Frame(parent, bg=P["bg"])
        row.pack(side="bottom", fill="x", pady=(0, app.S(6)), anchor="w")
        available = app.S(647) - 2 * app.S(44)
        gap = app.S(14)
        card_w = int((available - gap) / 2)
        for i, (text, cmd, primary) in enumerate(
                ((left_text, left_cmd, True), (right_text, right_cmd, False))):
            edge = P["accent"] if primary else "#94A3B8"
            card = tk.Frame(row, bg=edge, width=card_w, height=app.S(58))
            card.pack(side="left", padx=(0, gap) if i == 0 else (0, 0))
            card.pack_propagate(False)
            btn = self._button(card, text, cmd, kind="solid" if primary else "ghost", size=13)
            btn.pack(fill="both", expand=True, padx=2, pady=2)
        return row

    def _option(self, parent, title, desc, command, primary=False):
        """整块可点的选项卡：对比度比"浅底小字"高得多。"""
        app, P = self.app, self.app.P
        bg = P["accent"] if primary else P["card"]
        fg = P["accent_text"] if primary else P["text"]
        card = tk.Frame(parent, bg=bg, highlightthickness=2,
                        highlightbackground=P["accent"] if primary else P["border"],
                        cursor="hand2")
        card.pack(fill="x", pady=(0, app.S(10)))
        head = tk.Label(card, text=title, font=app.F(14, True), fg=fg, bg=bg,
                        anchor="w", cursor="hand2")
        head.pack(fill="x", padx=app.S(16), pady=(app.S(12), 0))
        sub = tk.Label(card, text=desc, font=app.F(10), anchor="w", justify="left",
                       fg=P["accent_text"] if primary else P["muted"], bg=bg,
                       wraplength=app.S(560), cursor="hand2")
        sub.pack(fill="x", padx=app.S(16), pady=(app.S(2), app.S(12)))
        for widget in (card, head, sub):
            widget.bind("<Button-1>", lambda _e: command())
        return card

    def _title(self, text, size=18):
        tk.Label(self.body, text=text, font=self.app.F(size, True), fg=self.app.P["text"],
                 bg=self.app.P["bg"], anchor="w", justify="left",
                 wraplength=self.app.S(560)).pack(fill="x")

    def _center(self, make, note: str = ""):
        """在居中的一行里放按钮：make(parent) 负责用给定父级创建控件。"""
        row = tk.Frame(self.body, bg=self.app.P["bg"])
        row.pack(fill="x", pady=(self.app.S(16), 0))
        inner = tk.Frame(row, bg=self.app.P["bg"])
        inner.pack(anchor="center")
        widget = make(inner)
        widget.configure(padx=self.app.S(34))       # 主按钮放宽一点，别显得局促
        widget.pack(pady=self.app.S(2))
        if note:
            tk.Label(row, text=note, font=self.app.F(9), fg=self.app.P["muted"],
                     bg=self.app.P["bg"]).pack(anchor="center", pady=(self.app.S(6), 0))
        return widget

    def _line(self, text, color=None, font_size=11):
        tk.Label(self.body, text=text, font=self.app.F(font_size),
                 fg=color or self.app.P["muted"], bg=self.app.P["bg"], anchor="w",
                 justify="left", wraplength=self.app.S(560)).pack(fill="x", pady=(self.app.S(8), 0))

    def _centre(self) -> None:
        host = self.app.root
        x = host.winfo_rootx() + (host.winfo_width() - self.winfo_width()) // 2
        y = host.winfo_rooty() + (host.winfo_height() - self.winfo_height()) // 3
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))

    # ------------------------------------------------------------ 分步渲染
    def _hug(self, min_width=None) -> None:
        """窗口贴着内容长：宽度不够才补到最小宽度，上下由内容决定。"""
        app = self.app
        width = max(self.winfo_reqwidth(), min_width or app.S(560))
        height = self.winfo_reqheight()
        self.geometry("%dx%d" % (width, height))
        self._centre()

    def _size_for(self) -> tuple:
        app = self.app
        if self.step == "corners":
            return app.S(780), app.S(700)
        if self.step == "result":
            return app.S(620), app.S(400)
        if self.step in ("ask", "paper"):
            return app.S(660), app.S(300)
        if self.step == "shoot":
            return app.S(700), app.S(400)
        return app.S(700), app.S(300)

    def render(self) -> None:
        self._clear()
        if self.step == "corners":
            self._render_corners()
        elif self.step == "result":
            self._render_result()
        elif self.step == "scan":
            self._render_scan()
        elif self.step == "paper":
            self._render_paper()
        elif self.step == "print":
            self._render_print()
        elif self.step == "shoot":
            self._render_shoot()
        elif self.step == "plain":
            self._render_plain()
        else:
            self._render_ask()
        self.update_idletasks()
        if self.step in ("ask", "paper"):
            # 黄金分割：宽 = 高 × 1.618
            self.geometry("%dx%d" % (self.app.S(647), self.app.S(400)))
        elif self.step == "corners":
            width = max(self.app.S(780), self.winfo_reqwidth())
            height = self.winfo_reqheight()
            self.geometry("%dx%d" % (width, height))
        else:
            self._hug()
        self._centre()

    def _render_ask(self) -> None:
        app = self.app
        self._title(app.T("calib.ask"), size=20)
        self._line(app.T("calib.ask_body"), font_size=11)
        self._choice(self.body, app.T("calib.yes_scan"), lambda: self.go("scan"),
                     app.T("calib.no_scan"), lambda: self.go("paper"))

    def _render_paper(self) -> None:
        app = self.app
        self._title(app.T("calib.q_paper"), size=20)
        self._line(app.T("calib.q_paper_body"), font_size=11)
        self._choice(self.body, app.T("calib.yes_paper"), lambda: self.go("print"),
                     app.T("calib.no_paper"), lambda: self.go("plain"))
        self._button(self.foot, app.T("calib.back_ask"), lambda: self.go("ask"),
                     kind="ghost", size=10).pack(side="left")

    def _render_scan(self) -> None:
        app = self.app
        self._title(app.T("calib.scan_title"), size=20)
        self._line(app.T("calib.scan_body"))
        self._line(app.T("calib.scan_tip"), font_size=10)
        scan_btn = self._center(
            lambda parent: self._button(parent, app.T("calib.scan_pick"),
                                        self.pick_scan, kind="solid"),
            note=app.T("calib.drop_hint"))
        app.bind_drop(scan_btn, self._drop_scan)
        if self.error:
            self._line(app.T("calib.fail", err=self.error), color="#B91C1C", font_size=10)
        self._button(self.foot, app.T("calib.back_ask"), lambda: self.go("ask"),
                     kind="ghost", size=10).pack(side="left")

    def _render_print(self) -> None:
        app = self.app
        self._title(app.T("calib.print_title"), size=20)
        self._line(app.T("calib.print_body"))
        self._line(app.T("calib.print_tip"), font_size=10)
        btn = self._center(
            lambda parent: self._button(parent, app.T("calib.print_board"),
                                        self.save_board, kind="solid"))
        if self.error:
            self._line(app.T("calib.fail", err=self.error), color="#B91C1C", font_size=10)
        self._button(self.foot, app.T("calib.back_prev"), lambda: self.go("paper"),
                     kind="ghost", size=10).pack(side="left")

    def _render_shoot(self) -> None:
        app = self.app
        self._title(app.T("calib.shoot_title"), size=20)
        self._line(app.T("calib.shoot_body"))
        self._line(app.T("calib.light_hint"), color=WARN_COLOR, font_size=10)
        self._line(app.T("calib.backlight"), font_size=10)
        row = tk.Frame(self.body, bg=app.P["bg"])
        row.pack(fill="x", pady=(app.S(16), 0))
        inner = tk.Frame(row, bg=app.P["bg"])
        inner.pack(anchor="center")
        btn = self._button(inner, app.T("calib.shoot_btn"), self.pick_photo, kind="solid")
        btn.pack(side="left")
        app.bind_drop(btn, self._drop_photo)
        self._button(inner, app.T("calib.help"), lambda: CartoonHelp(app),
                     kind="ghost", size=10).pack(side="left", padx=(app.S(10), 0))
        if self.error:
            self._line(app.T("calib.fail", err=self.error), color="#B91C1C", font_size=10)
        self._button(self.foot, app.T("calib.back_prev"), lambda: self.go("print"),
                     kind="ghost", size=10).pack(side="left")

    def _render_plain(self) -> None:
        app = self.app
        self._title(app.T("calib.plain_title"), size=20)
        self._line(app.T("calib.fallback_warn"), color=WARN_COLOR, font_size=10)
        self._line(app.T("calib.shoot_body"))
        btn = self._center(
            lambda parent: self._button(parent, app.T("calib.shoot_btn"),
                                        self.pick_photo_plain, kind="warn"))
        app.bind_drop(btn, self._drop_plain)
        if self.error:
            self._line(app.T("calib.fail", err=self.error), color="#B91C1C", font_size=10)
        self._button(self.foot, app.T("calib.back_ask"), lambda: self.go("ask"),
                     kind="ghost", size=10).pack(side="left")

    # ------------------------------------------------------------ 点四角（可缩放/平移）
    def _render_corners(self) -> None:
        app = self.app
        from PIL import Image

        self.body.pack_configure(padx=self.app.S(26))
        self._title(app.T("calib.corners_title"), size=20)
        self._line(app.T("calib.corners_body"))
        if self.error:
            self._line(app.T("calib.fail", err=self.error), color="#B91C1C", font_size=10)
        self._line(app.T("calib.corners_hint"), font_size=10)
        self._line(app.T("calib.backlight"), font_size=9)

        img = Image.open(self.photo_path).convert("RGB")
        box_w, box_h = app.S(720), app.S(470)
        self._photo = img
        self._box = (box_w, box_h)
        self._base_scale = min(box_w / img.width, box_h / img.height)
        self._zoom = 1.0
        self._img_off = ((box_w - img.width * self._base_scale) / 2.0,
                         (box_h - img.height * self._base_scale) / 2.0)

        canvas = tk.Canvas(self.body, width=box_w, height=box_h, bg="#111111",
                           highlightthickness=0)
        canvas.pack(pady=(app.S(8), 0))
        canvas.bind("<Button-1>", self._on_canvas_press)
        canvas.bind("<B1-Motion>", self._on_canvas_motion)
        canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        canvas.bind("<Button-3>", self._pan_start)
        canvas.bind("<B3-Motion>", self._pan_move)
        canvas.bind("<MouseWheel>", self._on_wheel)
        canvas.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.15))
        canvas.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.15))
        self._canvas = canvas
        self._redraw_all()

        self._button(self.foot, app.T("calib.corners_reset"), self._reset_corners,
                     kind="ghost", size=10).pack(side="left")
        self._button(self.foot, app.T("calib.zoom_fit"), self._zoom_fit,
                     kind="ghost", size=10).pack(side="left", padx=(app.S(8), 0))
        self._button(self.foot, app.T("calib.help"), lambda: CartoonHelp(app),
                     kind="ghost", size=10).pack(side="left", padx=(app.S(8), 0))
        self._go_btn = self._button(self.foot, app.T("calib.corners_go"),
                                    self.measure_corners, kind="solid", size=12)
        self._go_btn.pack(side="right")
        self._sync_go_btn()

    def _scale(self) -> float:
        return self._base_scale * self._zoom

    def _canvas_xy(self, x: float, y: float):
        s = self._scale()
        return (x * s + self._img_off[0], y * s + self._img_off[1])

    def _image_xy(self, cx: float, cy: float):
        s = self._scale()
        return ((cx - self._img_off[0]) / s, (cy - self._img_off[1]) / s)

    def _zoom_at(self, cx: float, cy: float, factor: float) -> None:
        if self._photo is None:
            return
        ix, iy = self._image_xy(cx, cy)
        new_zoom = max(1.0, min(6.0, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        self._zoom = new_zoom
        s = self._scale()
        self._img_off = (cx - ix * s, cy - iy * s)
        self._clamp_offset()
        self._redraw_all()

    def _on_wheel(self, event) -> None:
        self._zoom_at(event.x, event.y, 1.15 if event.delta > 0 else 1 / 1.15)

    def _zoom_fit(self) -> None:
        if self._photo is None:
            return
        box_w, box_h = self._box
        self._zoom = 1.0
        self._img_off = ((box_w - self._photo.width * self._base_scale) / 2.0,
                         (box_h - self._photo.height * self._base_scale) / 2.0)
        self._redraw_all()

    def _clamp_offset(self) -> None:
        if self._photo is None:
            return
        box_w, box_h = self._box
        w = self._photo.width * self._scale()
        h = self._photo.height * self._scale()
        ox, oy = self._img_off
        ox = (box_w - w) / 2.0 if w <= box_w else min(0.0, max(box_w - w, ox))
        oy = (box_h - h) / 2.0 if h <= box_h else min(0.0, max(box_h - h, oy))
        self._img_off = (ox, oy)

    def _pan_start(self, event) -> None:
        self._pan_from = (event.x, event.y, self._img_off[0], self._img_off[1])

    def _pan_move(self, event) -> None:
        start = getattr(self, "_pan_from", None)
        if not start:
            return
        self._img_off = (start[2] + (event.x - start[0]), start[3] + (event.y - start[1]))
        self._clamp_offset()
        self._redraw_all()

    def _redraw_all(self) -> None:
        cv = getattr(self, "_canvas", None)
        if cv is None or self._photo is None:
            return
        from PIL import ImageTk

        cv.delete("all")
        s = self._scale()
        box_w, box_h = self._box
        ox, oy = self._img_off
        x0 = max(0, int(-ox / s))
        y0 = max(0, int(-oy / s))
        x1 = min(self._photo.width, int((box_w - ox) / s) + 1)
        y1 = min(self._photo.height, int((box_h - oy) / s) + 1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        crop = self._photo.crop((x0, y0, x1, y1))
        w = max(1, int(round((x1 - x0) * s)))
        h = max(1, int(round((y1 - y0) * s)))
        self._photo_tk = ImageTk.PhotoImage(crop.resize((w, h)))
        cv.create_image(ox + x0 * s, oy + y0 * s, anchor="nw", image=self._photo_tk)
        self._redraw_corners()

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
        for i, (cx, cy) in enumerate(pts):
            cv.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, outline="#F59E0B",
                           width=3, fill="", tags="mark")
            cv.create_text(cx + 16, cy - 14, text=str(i + 1), fill="#F59E0B",
                           font=self.app.F(12, True), tags="mark")

    def _hit_corner(self, cx: float, cy: float):
        for i, (x, y) in enumerate(self.corners):
            px, py = self._canvas_xy(x, y)
            if (px - cx) ** 2 + (py - cy) ** 2 <= 16 ** 2:
                return i
        return None

    # ---- 点击 = 加点；拖动 = 平移（或拖已有点）----
    def _on_canvas_press(self, event) -> None:
        self._press = (event.x, event.y)
        self._moved = False
        self._press_dot = self._hit_corner(event.x, event.y)
        self._off_start = self._img_off

    def _on_canvas_motion(self, event) -> None:
        if self._press is None:
            return
        dx = event.x - self._press[0]
        dy = event.y - self._press[1]
        if not self._moved and abs(dx) + abs(dy) < 4:
            return                       # 还没到"拖动"的门槛，先不动作
        self._moved = True
        if self._press_dot is not None and self._press_dot < len(self.corners):
            x, y = self._image_xy(event.x, event.y)
            x = max(0.0, min(x, float(self._photo.width)))
            y = max(0.0, min(y, float(self._photo.height)))
            self.corners[self._press_dot] = (x, y)
            self._redraw_corners()
            return
        self._img_off = (self._off_start[0] + dx, self._off_start[1] + dy)
        self._clamp_offset()
        self._redraw_all()

    def _on_canvas_release(self, event) -> None:
        moved = self._moved
        dot = self._press_dot
        self._press = None
        self._moved = False
        self._press_dot = None
        if moved or self._photo is None:
            return
        if dot is not None:
            return                       # 点已有圆点：不新增
        if len(self.corners) >= 4:
            return
        x, y = self._image_xy(event.x, event.y)
        if not (0 <= x <= self._photo.width and 0 <= y <= self._photo.height):
            return
        self.corners.append((x, y))
        self._redraw_corners()
        self._sync_go_btn()

    def _sync_go_btn(self) -> None:
        btn = self._go_btn
        if btn is None:
            return
        ready = len(self.corners) == 4
        btn.configure(state="normal" if ready else "disabled",
                      cursor="hand2" if ready else "arrow")

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
            self.measurement_plain = False
            self._finish(measure_photo_corners(self.photo_path, self.corners,
                                               expect_cols=grid.cols,
                                               expect_rows=grid.rows))
        except Exception as exc:
            self.error = str(exc)
            self.step = "corners"
            self.render()

    # ------------------------------------------------------------ 结果
    def _render_result(self) -> None:
        app, m = self.app, self.measurement
        self._title(app.T("calib.result_title"))
        if m is None:
            return
        tk.Label(self.body, text=app.T("calib.result_spec", cols=m.cols, rows=m.rows,
                                       px=m.pitch_x_mm, py=m.pitch_y_mm),
                 font=app.F(13), fg=app.P["text"], bg=app.P["bg"], anchor="w").pack(
                     fill="x", pady=(app.S(6), 0))
        tk.Label(self.body, text=app.T("calib.result_conf", conf=m.confidence),
                 font=app.F(13), fg=app.P["text"], bg=app.P["bg"], anchor="w").pack(
                     fill="x", pady=(app.S(6), 0))
        if m.warnings:
            tk.Label(self.body, text="\n".join(m.warnings), font=app.F(9),
                     fg=app.P["muted"], bg=app.P["bg"], anchor="w", justify="left",
                     wraplength=app.S(560)).pack(fill="x", pady=(app.S(8), 0))
        inner = tk.Frame(self.foot, bg=self.app.P["bg"])
        inner.pack(anchor="center")
        self._button(inner, app.T("calib.again"), self.back_to_pick,
                     kind="ghost", size=10).pack(side="left", padx=(0, app.S(10)))
        self._button(inner, app.T("calib.save"), self.save_template,
                     kind="solid", size=12).pack(side="left")

    # ------------------------------------------------------------ 动作
    def go(self, step: str) -> None:
        self.step = step
        self.error = None
        self.render()

    def _grid(self):
        from . import screens

        return screens._selected(self.app).to_grid()

    def _finish(self, measurement) -> None:
        self.measurement = measurement
        self.error = None
        self.step = "result"
        self.render()

    def _pick_file(self, title, filetypes):
        from tkinter import filedialog

        return filedialog.askopenfilename(title=title, filetypes=filetypes, parent=self)

    def pick_scan(self) -> None:
        path = self._pick_file(self.app.T("calib.scan_pick"),
                               [("扫描件", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff"),
                                ("所有文件", "*.*")])
        if path:
            self._measure_scan(path)

    def _drop_scan(self, path) -> None:
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
        path = self._pick_file(self.app.T("calib.shoot_btn"),
                               [("照片 JPG/PNG", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"),
                                ("所有文件", "*.*")])
        if path:
            self._try_photo(path)

    def _drop_photo(self, path) -> None:
        if path:
            self._try_photo(path)

    def _try_photo(self, path: str) -> None:
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
        path = self._pick_file(self.app.T("calib.shoot_btn"),
                               [("照片 JPG/PNG", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"),
                                ("所有文件", "*.*")])
        if path:
            self._measure_plain(path)

    def _drop_plain(self, path) -> None:
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
            initialfile=self.app.T("calib.board_filename"), filetypes=[("PDF", "*.pdf")], parent=self)
        if not path:
            return
        try:
            make_board_pdf(path)
            self.app._open_path(path)
            self.go("shoot")            # 打完直接下一步，不用再点
        except Exception as exc:
            self.error = str(exc)
            self.render()

    def back_to_pick(self) -> None:
        self.measurement = None
        self.go("corners" if self.photo_path else "scan")

    def save_template(self) -> None:
        app, m = self.app, self.measurement
        if m is None:
            return
        from ..templates import Template

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


class CartoonHelp(tk.Toplevel):
    """三步图示：一次性排开（不轮播），一眼看完怎么摆、怎么拍、怎么点。"""

    BOARD_FILL, BOARD_LINE, BOARD_DOT = "#EEF3F9", "#94A3B8", "#111827"
    SHEET_FILL, SHEET_LINE, SHEET_GRID = "#FDF6EC", "#C9AE8A", "#EBDCC4"
    INK, ACCENT = "#334155", "#B45309"

    def __init__(self, app) -> None:
        super().__init__(app.root)
        self.app = app
        P, S = app.P, app.S
        self.title(app.T("calib.help_title"))
        self.configure(bg=P["bg"])
        self.transient(app.root)
        self.resizable(False, False)

        panel_w = S(300)
        panel_h = S(235)
        pad = S(16)
        self.canvases = []
        row = tk.Frame(self, bg=P["bg"])
        row.pack(padx=pad, pady=(S(16), S(6)))
        for i in range(3):
            col = tk.Frame(row, bg=P["bg"])
            col.pack(side="left", padx=(0 if i == 0 else S(12), 0))
            canvas = tk.Canvas(col, width=panel_w, height=panel_h, bg="#FFFFFF",
                               highlightthickness=1, highlightbackground=P["border"])
            canvas.pack()
            canvas.create_text(S(18), S(16), text="①②③"[i],
                               fill=self.ACCENT, font=app.F(14, True))
            self.canvases.append(canvas)
            tk.Label(col, text=app.T("calib.help%d" % (i + 1)), font=app.F(11),
                     fg=P["text"], bg=P["bg"], wraplength=panel_w,
                     justify="left").pack(fill="x", pady=(S(8), 0))

        foot = tk.Frame(self, bg=P["bg"])
        foot.pack(fill="x", padx=pad, pady=(S(8), S(14)))
        tk.Button(foot, text=app.T("calib.help_close"), font=app.F(11, True),
                  relief="flat", bd=0, bg=P["accent"], fg=P["accent_text"],
                  padx=S(20), pady=S(9), cursor="hand2", command=self.destroy
                  ).pack(side="right")

        self.update_idletasks()
        self._draw_all()
        host = app.root
        x = host.winfo_rootx() + (host.winfo_width() - self.winfo_width()) // 2
        y = host.winfo_rooty() + (host.winfo_height() - self.winfo_height()) // 3
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))
        try:
            self.grab_set()
        except tk.TclError:                     # pragma: no cover
            pass

    def _draw_all(self) -> None:
        drawers = (self._draw_board_and_sheet, self._draw_phone, self._draw_corners)
        for canvas, drawer in zip(self.canvases, drawers):
            canvas.delete("all")
            self._canvas = canvas
            drawer()

    # ---- 三个小图（每个画在 300×360 的面板里）----
    def _board(self, x, y, width, caption=None):
        c = self._canvas
        height = width * 1.4142
        c.create_rectangle(x, y, x + width, y + height, fill=self.BOARD_FILL,
                           outline=self.BOARD_LINE, width=2)
        for r in range(6):
            for col in range(4):
                cx = x + width * (0.16 + col * 0.23)
                cy = y + height * (0.12 + r * 0.14)
                side = width * 0.06
                c.create_rectangle(cx, cy, cx + side, cy + side, fill=self.BOARD_DOT, outline="")
        if caption:
            c.create_text(x + width / 2, y + height + 16, text=caption,
                          fill=self.INK, font=self.app.F(10))

    def _sheet(self, x, y, width, caption=None, corners=False):
        c = self._canvas
        height = width * 1.4142
        c.create_rectangle(x, y, x + width, y + height, fill=self.SHEET_FILL,
                           outline=self.SHEET_LINE, width=2)
        for i in range(1, 5):
            gx = x + width * i / 5.0
            c.create_line(gx, y + 2, gx, y + height - 2, fill=self.SHEET_GRID)
        for i in range(1, 9):
            gy = y + height * i / 9.0
            c.create_line(x + 2, gy, x + width - 2, gy, fill=self.SHEET_GRID)
        if corners:
            pts = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
            for i, (px, py) in enumerate(pts):
                c.create_oval(px - 7, py - 7, px + 7, py + 7, outline="#F59E0B", width=3)
                dx = 16 if i in (1, 2) else -16
                dy = -16 if i in (0, 1) else 16
                c.create_text(px + dx, py + dy, text=str(i + 1), fill="#F59E0B",
                              font=self.app.F(11, True))
        if caption:
            c.create_text(x + width / 2, y + height + 16, text=caption,
                          fill=self.INK, font=self.app.F(10))

    def _draw_board_and_sheet(self) -> None:
        w = self._canvas.winfo_reqwidth()
        width = w * 0.30
        self._board(w * 0.12, 16, width, caption="标定板")
        self._sheet(w * 0.54, 16, width, caption="胶纸")

    def _draw_phone(self) -> None:
        """第 2 步：相机取景框里，两张纸都完整入画。"""
        c = self._canvas
        w = c.winfo_reqwidth()
        h = c.winfo_reqheight()
        fx0, fy0 = w * 0.07, h * 0.07
        fx1, fy1 = w * 0.93, h * 0.86
        c.create_rectangle(fx0, fy0, fx1, fy1, fill="#111827", outline="#0F172A", width=2)
        # 取景角标
        arm = min(w, h) * 0.10
        inset = min(w, h) * 0.03
        for px, py, sx, sy in ((fx0 + inset, fy0 + inset, 1, 1), (fx1 - inset, fy0 + inset, -1, 1),
                               (fx1 - inset, fy1 - inset, -1, -1), (fx0 + inset, fy1 - inset, 1, -1)):
            c.create_line(px, py, px + sx * arm, py, fill="#F59E0B", width=3)
            c.create_line(px, py, px, py + sy * arm, fill="#F59E0B", width=3)
        # 框里的两张纸（完整入画）
        frame_w = fx1 - fx0
        paper_w = frame_w * 0.30
        paper_h = paper_w * 1.4142
        gap = frame_w * 0.06
        left = (fx0 + fx1) / 2 - (paper_w * 2 + gap) / 2
        top = fy0 + ((fy1 - fy0) - paper_h) / 2
        self._board(left, top, paper_w)
        self._sheet(left + paper_w + gap, top, paper_w)

    def _draw_corners(self) -> None:
        w = self._canvas.winfo_reqwidth()
        width = w * 0.40
        self._sheet((w - width) / 2, 38, width, corners=True)
