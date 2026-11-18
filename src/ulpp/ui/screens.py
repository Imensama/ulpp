# -*- coding: utf-8 -*-
"""v2 向导的两屏：① 选胶纸（含扫描测量）　② 放纸方向。

2026-11-13 第二版视觉：左边一张"纸的缩略图"（Canvas 按真实节距画格阵），右边规格 + 大按钮，
扫描按钮做大做醒目；每屏仍然只有一句说明（用户嫌第一版啰嗦）。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable, Dict, List

from ..presets import DEFAULT_PRESET_KEY, PRESETS, by_key

PREVIEW_W, PREVIEW_H = 168, 238      # 设计稿像素（会被 z 放大）


# ---------------------------------------------------------------- 基础件
def _card(app, parent) -> tk.Frame:
    return tk.Frame(parent, bg=app.P["card"], highlightthickness=1,
                    highlightbackground=app.P["border"])


def _title(app, body, step_id: str) -> None:
    tk.Label(body, text=app.T(step_id + ".title"), font=app.F(24, True), fg=app.P["text"],
             bg=app.P["bg"], anchor="w").pack(fill="x")
    tk.Label(body, text=app.T(step_id + ".body"), font=app.F(12), fg=app.P["muted"],
             bg=app.P["bg"], anchor="w", justify="left",
             wraplength=app.S(760)).pack(fill="x", pady=(app.S(6), 0))


def _tip(app, body, step_id: str) -> None:
    tk.Label(body, text=app.T(step_id + ".tip"), font=app.F(10), fg=app.P["muted"],
             bg=app.P["bg"], anchor="w", justify="left",
             wraplength=app.S(760)).pack(fill="x", pady=(app.S(14), 0))


def _button(app, parent, text: str, command: Callable[[], None] = None,
            kind: str = "soft", size: int = 12):
    """大按钮：soft=浅蓝（次要但醒目）／solid=蓝底白字（主操作）／ghost=白底描边。"""
    P = app.P
    if command is None:
        state, fg, bg = "disabled", P["muted"], P["chip"]
    elif kind == "solid":
        state, fg, bg = "normal", P["accent_text"], P["accent"]
    elif kind == "ghost":
        state, fg, bg = "normal", P["text"], P["card"]
    else:
        state, fg, bg = "normal", P["soft_text"], P["soft"]
    return tk.Button(parent, text=text, font=app.F(size, True), fg=fg, bg=bg,
                     activeforeground=fg, activebackground=P["border"],
                     relief="flat", bd=0, padx=app.S(20), pady=app.S(12),
                     highlightthickness=1 if kind == "ghost" else 0,
                     highlightbackground=P["border"],
                     cursor="hand2" if command else "arrow", state=state, command=command)


def _combo(app, parent, values: List[str], var) -> tk.Widget:
    from tkinter import ttk

    return ttk.Combobox(parent, textvariable=var, state="readonly", values=values,
                        width=30, font=app.F(11))


# ---------------------------------------------------------------- 选择与文案
def _selected(app):
    key = str(app.flow.answer("paper") or "")
    if key.startswith("tpl:"):
        tpl = app.templates.get(key[4:])
        if tpl is not None:
            return tpl
    try:
        return by_key(key or DEFAULT_PRESET_KEY)
    except Exception:
        return by_key(DEFAULT_PRESET_KEY)


def _name(item) -> str:
    return item.name if hasattr(item, "name") else item.title


def _grid_of(item):
    return item.to_grid()


def _spec(app, item) -> str:
    g = _grid_of(item)
    return app.T("sheet.spec", px=g.pitch_x, py=g.pitch_y, cols=g.cols,
                 rows=g.rows, count=g.cols * g.rows)


def _display(app, item) -> str:
    if hasattr(item, "label"):
        return app.T("sheet.tpl_marked", name=item.label())
    return item.title


# ---------------------------------------------------------------- 纸的缩略图
def _preview(app, parent, item, width: int = PREVIEW_W, height: int = PREVIEW_H):
    """按真实节距把这张纸画出来：白纸 + 格线（不画内容）。"""
    P = app.P
    w, h = app.S(width), app.S(height)
    cv = tk.Canvas(parent, width=w, height=h, bg=P["card"], highlightthickness=0)
    g = _grid_of(item)
    pad = app.S(8)
    scale = min((w - 2 * pad) / g.page_w, (h - 2 * pad) / g.page_h)
    pw, ph = g.page_w * scale, g.page_h * scale
    x0 = (w - pw) / 2
    y0 = (h - ph) / 2
    cv.create_rectangle(x0, y0, x0 + pw, y0 + ph, fill="#FFFFFF",
                        outline=P["border"], width=max(1, app.S(1)))
    line = P["dot_off"]      # 纸样格线用中性灰，别跟强调色跑
    for c in range(g.cols + 1):
        x = x0 + (g.margin_x + c * g.pitch_x) * scale
        cv.create_line(x, y0, x, y0 + ph, fill=line, width=max(1, app.S(1) // 2))
    for r in range(g.rows + 1):
        y = y0 + (g.margin_top + r * g.pitch_y) * scale
        cv.create_line(x0, y, x0 + pw, y, fill=line, width=max(1, app.S(1) // 2))
    cv.create_rectangle(x0, y0, x0 + pw, y0 + ph, outline=P["border"],
                        fill="", width=max(1, app.S(1)))
    return app.keep(cv)


# ---------------------------------------------------------------- 第 1 屏
def build_sheet(app, body) -> None:
    _title(app, body, "sheet")
    item = _selected(app)

    card = _card(app, body)
    card.pack(fill="x", pady=(app.S(18), 0))
    inner = tk.Frame(card, bg=app.P["card"])
    inner.pack(fill="x", padx=app.S(24), pady=app.S(18))

    _preview(app, inner, item).pack(side="left")

    right = tk.Frame(inner, bg=app.P["card"])
    right.pack(side="left", fill="both", expand=True, padx=(app.S(26), 0))
    right.grid_rowconfigure(0, weight=1)      # 上留白
    right.grid_rowconfigure(2, weight=1)      # 下留白：内容垂直居中，和纸样对齐
    right.grid_columnconfigure(0, weight=1)

    box = tk.Frame(right, bg=app.P["card"])
    box.grid(row=1, column=0, sticky="ew")

    tk.Label(box, text=_name(item), font=app.F(20, True), fg=app.P["text"],
             bg=app.P["card"], anchor="w").pack(fill="x")
    tk.Label(box, text=_spec(app, item), font=app.F(12), fg=app.P["muted"],
             bg=app.P["card"], anchor="w").pack(fill="x", pady=(app.S(6), 0))

    row = tk.Frame(box, bg=app.P["card"])
    row.pack(fill="x", pady=(app.S(20), 0))
    tk.Label(row, text=app.T("sheet.label"), font=app.F(11), fg=app.P["muted"],
             bg=app.P["card"]).pack(side="left")

    choices = [app.T("sheet.tpl_marked", name=t.label(app.lang)) for t in app.templates.items]
    choices += [p.title for p in PRESETS]
    disp = app.keep(tk.StringVar(value=_display(app, item)))
    combo = _combo(app, row, choices, disp)
    combo.pack(side="left", padx=app.S(10))
    combo.set(_display(app, item))

    app._wizard_button(row, app.T("calib.new_paper"), app.open_calibrate).pack(
        side="left", padx=(app.S(18), 0))

    def on_pick(_event=None):
        idx = combo.current()
        if idx < 0:
            return
        if idx < len(app.templates.items):
            chosen = app.templates.items[idx]
            app.flow.answer("paper", "tpl:" + chosen.id)
        else:
            chosen = PRESETS[idx - len(app.templates.items)]
            app.flow.answer("paper", chosen.key)
        app.on_change()
        app.render()

    combo.bind("<<ComboboxSelected>>", on_pick)

    # 量出来的结果：单独一条横幅
    if app.measurement is not None:
        m = app.measurement
        low = m.confidence < 0.5 or not m.ok
        banner = tk.Frame(body, bg=app.P["soft"] if not low else app.P["chip"],
                          highlightthickness=1,
                          highlightbackground=app.P["border"])
        banner.pack(fill="x", pady=(app.S(16), 0))
        text = (app.T("sheet.scan_low", conf=m.confidence,
                      why="；".join(w.split(":")[0] for w in m.warnings) or "-")
                if low else
                app.T("sheet.scan_ok", cols=m.cols, rows=m.rows, px=m.pitch_x_mm,
                      py=m.pitch_y_mm, conf=m.confidence))
        tk.Label(banner, text=text, font=app.F(13, True), fg=app.P["soft_text"],
                 bg=banner.cget("bg"), anchor="w", justify="left",
                 wraplength=app.S(840)).pack(fill="x", padx=app.S(20), pady=(app.S(14), app.S(10)))
        row = tk.Frame(banner, bg=banner.cget("bg"))
        row.pack(fill="x", padx=app.S(20), pady=(0, app.S(14)))
        _button(app, row, app.T("sheet.save_tpl"), app.save_measurement,
                kind="solid", size=11).pack(side="left")
        _button(app, row, app.T("sheet.rescan"), app.ask_scan,
                kind="ghost", size=10).pack(side="left", padx=(app.S(10), 0))
    elif app.scan_error:
        banner = tk.Frame(body, bg=app.P["chip"], highlightthickness=1,
                          highlightbackground=app.P["border"])
        banner.pack(fill="x", pady=(app.S(16), 0))
        tk.Label(banner, text=app.T("sheet.scan_fail", err=app.scan_error),
                 font=app.F(12), fg="#B91C1C", bg=app.P["chip"], anchor="w",
                 justify="left", wraplength=app.S(840)).pack(fill="x", padx=app.S(20),
                                                            pady=(app.S(12), app.S(6)))
        _button(app, banner, app.T("sheet.rescan"), app.ask_scan, kind="ghost",
                size=10).pack(anchor="w", padx=app.S(20), pady=(0, app.S(12)))
    _tip(app, body, "sheet")


# ---------------------------------------------------------------- 第 2 屏
def build_orient(app, body) -> None:
    _title(app, body, "orient")
    card = _card(app, body)
    card.pack(fill="x", pady=(app.S(18), 0))
    tk.Label(card, text=app.direction_label(), font=app.F(20, True), fg=app.P["text"],
             bg=app.P["card"], anchor="w").pack(fill="x", padx=app.S(24),
                                                pady=(app.S(22), app.S(14)))
    row = tk.Frame(card, bg=app.P["card"])
    row.pack(fill="x", padx=app.S(24), pady=(0, app.S(20)))
    _button(app, row, app.T("orient.calibrate"), app.open_wizard, kind="solid",
            size=12).pack(side="left")
    tk.Label(row, text=app.T("orient.wait"), font=app.F(10), fg=app.P["muted"],
             bg=app.P["card"]).pack(side="left", padx=(app.S(12), 0))
    _tip(app, body, "orient")
    if app.flow.is_last:
        return


def build_output(app, body) -> None:
    _title(app, body, "output")
    row = tk.Frame(body, bg=app.P["bg"])
    row.pack(fill="x", pady=(app.S(14), 0))

    # ---- 左：内容 ----
    left = _card(app, row)
    left.pack(side="left", fill="both", expand=True)
    li = tk.Frame(left, bg=app.P["card"])
    li.pack(fill="both", expand=True, padx=app.S(20), pady=app.S(12))

    top = tk.Frame(li, bg=app.P["card"])
    top.pack(fill="x")
    _button(app, top, app.T("output.pick"), app.pick_pdfs, kind="soft", size=11).pack(side="left")
    _button(app, top, app.T("output.add_folder"), app.pick_folder, kind="ghost",
            size=10).pack(side="left", padx=(app.S(8), 0))
    _button(app, top, app.T("output.add_zip"), app.pick_zip, kind="ghost",
            size=10).pack(side="left", padx=(app.S(8), 0))
    if app.files:
        _button(app, top, app.T("output.clear"), app.clear_files, kind="ghost",
                size=10).pack(side="right")

    total_in = len(app.files) + len(app.images)
    if total_in:
        names = "、".join(Path(f).name for f in (app.files + app.images)[:3])
        extra = "…" if total_in > 3 else ""
        tk.Label(li, text=app.T("output.files", n=total_in, names=names + extra),
                 font=app.F(11), fg=app.P["text"], bg=app.P["card"], anchor="w").pack(
            fill="x", pady=(app.S(10), 0))
        if app.images:
            tk.Label(li, text=app.T("output.images", n=len(app.images)),
                     font=app.F(10), fg=app.P["muted"], bg=app.P["card"],
                     anchor="w").pack(fill="x", pady=(app.S(2), 0))
    else:
        tk.Label(li, text=app.T("output.empty"), font=app.F(11), fg=app.P["muted"],
                 bg=app.P["card"], anchor="w").pack(fill="x", pady=(app.S(10), 0))

    tk.Label(li, text=app.T("output.text_hint"), font=app.F(10), fg=app.P["muted"],
             bg=app.P["card"], anchor="w").pack(fill="x", pady=(app.S(12), app.S(4)))
    box = tk.Text(li, height=3, wrap="word", undo=True, relief="flat", bd=0,
                  highlightthickness=1, highlightbackground=app.P["border"],
                  font=app.F(11), bg="#FFFFFF", fg=app.P["text"])
    box.pack(fill="both", expand=True)
    app.attach_text_box(box)

    # ---- 右：选项 ----
    right = _card(app, row)
    right.pack(side="left", fill="y", padx=(app.S(16), 0))
    ri = tk.Frame(right, bg=app.P["card"])
    ri.pack(fill="both", expand=True, padx=app.S(20), pady=app.S(12))
    tk.Label(ri, text=app.T("output.options"), font=app.F(12, True), fg=app.P["text"],
             bg=app.P["card"], anchor="w").pack(fill="x", pady=(0, app.S(10)))

    from tkinter import ttk

    def group(label_key):
        tk.Label(ri, text=app.T(label_key), font=app.F(10), fg=app.P["muted"],
                 bg=app.P["card"], anchor="w").pack(fill="x", pady=(app.S(4), 0))

    group("output.pages")
    pages = tk.Frame(ri, bg=app.P["card"])
    pages.pack(fill="x")
    for key, value in (("output.pages_all", False), ("output.pages_first", True)):
        ttk.Radiobutton(pages, text=app.T(key), value=value, variable=app.first_page_only,
                        command=app.on_options).pack(side="left", padx=(0, app.S(10)))

    group("output.text_align")
    aligns = tk.Frame(ri, bg=app.P["card"])
    aligns.pack(fill="x")
    for key, value in (("output.align_left", "left"), ("output.align_center", "center"),
                       ("output.align_right", "right")):
        ttk.Radiobutton(aligns, text=app.T(key), value=value, variable=app.text_align,
                        command=app.on_options).pack(side="left", padx=(0, app.S(10)))
    ttk.Checkbutton(ri, text=app.T("output.uniform"), variable=app.text_uniform,
                    command=app.on_options).pack(anchor="w", pady=(app.S(2), 0))

    group("output.options")
    opts = tk.Frame(ri, bg=app.P["card"])
    opts.pack(fill="x")
    ttk.Checkbutton(opts, text=app.T("output.proof"), variable=app.make_proof,
                    command=app.on_options).pack(side="left", padx=(0, app.S(10)))
    ttk.Checkbutton(opts, text=app.T("output.csv"), variable=app.make_csv,
                    command=app.on_options).pack(side="left")
    opts2 = tk.Frame(ri, bg=app.P["card"])
    opts2.pack(fill="x")
    ttk.Checkbutton(opts2, text=app.T("output.marks"), variable=app.make_marks,
                    command=app.on_options).pack(side="left")

    group("output.out_dir_hint")
    dirrow = tk.Frame(ri, bg=app.P["card"])
    dirrow.pack(fill="x")
    ttk.Entry(dirrow, textvariable=app.out_dir, width=22, font=app.F(10)).pack(side="left")
    _button(app, dirrow, app.T("output.browse"), app.pick_out_dir, kind="ghost",
            size=9).pack(side="left", padx=(app.S(6), 0))


    group("output.base_name")
    ttk.Entry(ri, textvariable=app.base_name, width=20, font=app.F(10)).pack(anchor="w")

    act = tk.Frame(body, bg=app.P["bg"])
    act.pack(fill="x", pady=(app.S(10), 0))
    _button(app, act, app.T("output.generate"), app.generate, kind="solid",
            size=13).pack(side="left")
    if app.output_path:
        tk.Label(act, text=app.T("output.done", name=Path(app.output_path).name),
                 font=app.F(11, True), fg=app.P["soft_text"], bg=app.P["soft"],
                 padx=app.S(12), pady=app.S(8)).pack(side="left", padx=(app.S(14), 0))
        _button(app, act, app.T("output.open"), app.open_output, kind="solid",
                size=11).pack(side="left", padx=(app.S(8), 0))
        _button(app, act, app.T("output.again"), app.generate, kind="ghost",
                size=10).pack(side="left", padx=(app.S(8), 0))
    if app.output_error:
        tk.Label(act, text=app.T("output.fail", err=app.output_error), font=app.F(11),
                 fg="#B91C1C", bg=app.P["bg"], anchor="w", justify="left",
                 wraplength=app.S(620)).pack(side="left", padx=(app.S(14), 0))
    _tip(app, body, "output")



BUILDERS: Dict[str, Callable] = {"sheet": build_sheet, "orient": build_orient,
                               "output": build_output}


def build(app, parent) -> None:
    BUILDERS.get(app.flow.current, build_sheet)(app, parent)
