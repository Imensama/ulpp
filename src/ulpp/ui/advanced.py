# -*- coding: utf-8 -*-
"""高级参数对话框：把"我想细调的那些数"放回来。

老界面里那 8 个数字（列/行/格宽高/节距/上边距/安全边）+ 左右上下微调，都在这一屏；
保存后变成一张"我的纸"（模板），第 1 屏下拉里能直接选，不用每次都填。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional, Tuple

from ..templates import Template, adjusted
from . import screens

FIELDS: Tuple[Tuple[str, str], ...] = (
    ("cols", "adv.cols"), ("rows", "adv.rows"),
    ("cell_w_mm", "adv.cell_w"), ("cell_h_mm", "adv.cell_h"),
    ("pitch_x_mm", "adv.pitch_x"), ("pitch_y_mm", "adv.pitch_y"),
    ("origin_x_mm", "adv.origin_x"), ("origin_y_mm", "adv.origin_y"),
    ("inset_mm", "adv.inset"),
)


class AdvancedDialog(tk.Toplevel):
    """模态小窗：改数 → 存成模板 → 回第 1 屏。"""

    def __init__(self, app) -> None:
        super().__init__(app.root)
        self.app = app
        P, S = app.P, app.S
        self.title(app.T("adv.title"))
        self.configure(bg=P["bg"])
        self.transient(app.root)
        self.resizable(False, False)

        base = screens._selected(app)
        grid = base.to_grid()
        values = {
            "cols": grid.cols, "rows": grid.rows,
            "cell_w_mm": grid.cell_w, "cell_h_mm": grid.cell_h,
            "pitch_x_mm": grid.pitch_x, "pitch_y_mm": grid.pitch_y,
            "origin_x_mm": grid.margin_x, "origin_y_mm": grid.margin_top,
            "inset_mm": grid.inset,
        }
        self.base_name = screens._name(base)
        self.vars: Dict[str, tk.StringVar] = {}
        self.dx = app.keep(tk.StringVar(value="0"))
        self.dy = app.keep(tk.StringVar(value="0"))

        wrap = tk.Frame(self, bg=P["bg"])
        wrap.pack(fill="both", expand=True, padx=S(24), pady=S(20))
        tk.Label(wrap, text=app.T("adv.title"), font=app.F(16, True), fg=P["text"],
                 bg=P["bg"], anchor="w").pack(fill="x")
        tk.Label(wrap, text=app.T("adv.body"), font=app.F(10), fg=P["muted"],
                 bg=P["bg"], anchor="w", justify="left",
                 wraplength=S(560)).pack(fill="x", pady=(S(4), S(14)))

        form = tk.Frame(wrap, bg=P["bg"])
        form.pack(fill="x")
        for i, (key, label_key) in enumerate(FIELDS):
            row, col = divmod(i, 2)
            cell = tk.Frame(form, bg=P["bg"])
            cell.grid(row=row, column=col, sticky="w", pady=S(5), padx=(0, S(18)))
            tk.Label(cell, text=app.T(label_key), font=app.F(10), fg=P["muted"],
                     bg=P["bg"], width=10, anchor="w").pack(side="left")
            var = app.keep(tk.StringVar(value=_fmt(values[key])))
            self.vars[key] = var
            ttk.Entry(cell, textvariable=var, width=8, font=app.F(11)).pack(side="left")

        tune = tk.Frame(wrap, bg=P["bg"])
        tune.pack(fill="x", pady=(S(14), 0))
        tk.Label(tune, text=app.T("adv.tune"), font=app.F(10), fg=P["muted"],
                 bg=P["bg"]).pack(side="left")
        for label_key, var in (("adv.dx", self.dx), ("adv.dy", self.dy)):
            tk.Label(tune, text=app.T(label_key), font=app.F(10), fg=P["muted"],
                     bg=P["bg"]).pack(side="left", padx=(S(12), S(4)))
            ttk.Entry(tune, textvariable=var, width=6, font=app.F(11)).pack(side="left")
        tk.Label(tune, text=app.T("adv.tune_hint"), font=app.F(9), fg=P["muted"],
                 bg=P["bg"]).pack(side="left", padx=(S(10), 0))

        self.error = tk.Label(wrap, text="", font=app.F(10), fg="#B91C1C", bg=P["bg"],
                              anchor="w", justify="left", wraplength=S(560))
        self.error.pack(fill="x", pady=(S(8), 0))

        foot = tk.Frame(wrap, bg=P["bg"])
        foot.pack(fill="x", pady=(S(12), 0))
        ttk.Button(foot, text=app.T("adv.cancel"), command=self.destroy).pack(side="right")
        ttk.Button(foot, text=app.T("adv.save"), command=self._save).pack(
            side="right", padx=(0, S(10)))

        self.update_idletasks()
        self._centre()
        self.bind("<Escape>", lambda _e: self.destroy())
        try:
            self.grab_set()
        except tk.TclError:      # pragma: no cover - 少数环境不允许模态
            pass

    # ------------------------------------------------------------ 内部
    def _centre(self) -> None:
        self.update_idletasks()
        host = self.app.root
        x = host.winfo_rootx() + (host.winfo_width() - self.winfo_width()) // 2
        y = host.winfo_rooty() + (host.winfo_height() - self.winfo_height()) // 3
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))

    def _numbers(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key, _ in FIELDS:
            text = self.vars[key].get().strip().replace(",", ".")
            try:
                out[key] = float(text)
            except ValueError:
                raise ValueError(self.app.T("adv.bad_number", field=self.app.T("adv." + key)))
        out["cols"] = int(out["cols"])
        out["rows"] = int(out["rows"])
        return out

    def _save(self) -> None:
        try:
            numbers = self._numbers()
            dx = float(self.dx.get().strip() or 0)
            dy = float(self.dy.get().strip() or 0)
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return
        base = screens._selected(self.app)
        if hasattr(base, "to_dict"):            # 已经是我的纸：沿用名字，不再叠后缀
            name = base.name
        else:                                    # 预设 → 包成模板，名字标一下改
            name = screens._name(base) + self.app.T("tpl.suffix_edited")
            base = Template.from_grid(base.to_grid(), name=name,
                                      source="preset:" + getattr(base, "key", "x"))
        try:
            tpl = adjusted(base, name=name, dx_mm=dx, dy_mm=dy,
                           **{k: v for k, v in numbers.items()})
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return
        self.app.apply_advanced(tpl)
        self.destroy()


def _fmt(value: float) -> str:
    if isinstance(value, int) or float(value) == int(value):
        return str(int(value))
    return ("%.2f" % float(value)).rstrip("0").rstrip(".")
