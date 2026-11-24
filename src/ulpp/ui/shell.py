# -*- coding: utf-8 -*-
"""v2 外壳：页眉 + 进度点 + 内容区 + 页脚（上一步/跳过/下一步）+ 状态条。

M0 只做骨架，规矩三条：
1. 老界面（``gui.py`` / ``partial_gui.py``）一行不动，2.0 起退到 ``python -m ulpp --v1``；
2. 每一步的状态都落盘（``%APPDATA%\\ulpp\\v2_flow.json``），关掉重开能接着上次；
3. 布局从一开始就按 ``Metrics.z`` 缩放，不再写死像素。
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter import font as tkfont
from typing import Optional

from .. import __version__
from ..i18n import current_language, set_language
from ..builder import build_all
from ..parser import parse_many
from ..scan import measure_file
from ..sheets import PrinterProfile, SheetStore
from ..templates import Template, TemplateStore
from ..textlabel import parse_text_block
from . import screens
from .buttons import AppButton
from .texts import TEXTS as _TEXTS, texts as _texts
from .flow import Flow, state_path
from .scale import Metrics, enable_dpi_awareness

FIRST_RUN_MARK = "first_run_done"     # 首次启动引导做过没有（与 v2_flow.json 同目录）

try:                              # 可选：装了 tkinterdnd2 才能拖文件进来
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore

    _HAS_DND = True
except Exception:                 # pragma: no cover - 没装就是没有拖拽
    _HAS_DND = False
    DND_FILES = None
    TkinterDnD = None


class Shell:
    """独立可测：给定 root 就能把六屏搭起来（截图脚本也直接用它）。"""

    def __init__(self, root: tk.Tk, flow: Optional[Flow] = None,
                 lang: Optional[str] = None, autosave: bool = True) -> None:
        self.root = root
        self.flow = flow if flow is not None else Flow.load()
        self.m = Metrics(root, theme=os.environ.get("ULPP_THEME", "aero"))
        _alpha = os.environ.get("ULPP_ALPHA", "")
        if _alpha:                       # 整窗半透明（想试试"玻璃感"时用）
            try:
                root.attributes("-alpha", max(0.5, min(1.0, float(_alpha))))
            except Exception:
                pass
        self.P = self.m.theme
        code = lang or current_language()
        self.lang = code if code in _TEXTS else "zh_CN"
        set_language(self.lang)      # 语言包（预设名等）跟着外壳走，避免中英混排
        self.tx = _texts(self.lang)
        self.autosave = autosave
        self.state_file = state_path()
        self.templates = TemplateStore()
        try:
            self.store = SheetStore.load()
        except Exception:            # 配置目录不可写（沙箱里就是这样）
            self.store = None
        self.feed = self._read_feed()
        self.files: list = []
        self.images: list = []
        self.output_path: Optional[str] = None
        self.output_error: Optional[str] = None
        self._text_box = None
        self.content_text = ""
        a = self.flow.answers
        self.first_page_only = tk.BooleanVar(value=bool(a.get("pages_first", False)))
        self.text_align = tk.StringVar(value=str(a.get("align", "center")))
        self.text_uniform = tk.BooleanVar(value=bool(a.get("uniform", False)))
        self.make_proof = tk.BooleanVar(value=bool(a.get("proof", True)))
        self.make_csv = tk.BooleanVar(value=bool(a.get("csv", True)))
        self.make_marks = tk.BooleanVar(value=bool(a.get("marks", False)))
        self.out_dir = tk.StringVar(value=str(a.get("out_dir", "")))
        self.base_name = tk.StringVar(value=str(a.get("base_name", self.T("base_name.default"))))
        self.measurement = None       # 最近一次量出来的结果（还没存成模板）
        self.scan_error: Optional[str] = None
        self.scan_source = ""
        self.photo_fallback = False
        self._keep_alive = []        # Tk 变量 / 图片必须有人引用，否则被 GC 掉（控件变空）
        self._editor = None          # 内容区容器，render() 时重建
        self._footer = None
        self._dots = None

        self.root.title("%s v%s" % (self.T("app"), __version__))
        w, h = self.m.window_size()
        self.root.geometry("%dx%d" % (w, h))
        self.root.minsize(self.m.s(760), self.m.s(520))
        self.root.configure(bg=self.P["bg"])
        self._build()
        self.render()
        if _HAS_DND:                      # 整个窗口都能拖：不只是那个文字框
            try:
                self.root.drop_target_register(DND_FILES)   # type: ignore[attr-defined]
                self.root.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            except Exception:             # pragma: no cover - 少数环境没有 DND
                pass

    # ------------------------------------------------------------ 基础
    def T(self, key: str, **kw) -> str:
        text = self.tx.get(key, key)
        try:
            return text.format(**kw) if kw else text
        except (KeyError, IndexError, ValueError):
            return text

    def S(self, px: float) -> int:
        return self.m.s(px)

    def F(self, size: float, bold: bool = False):
        return self.m.font(size, bold)

    def keep(self, var):
        """把 Tk 变量 / PhotoImage 挂在壳上，免得局部变量被回收后控件显示为空。"""
        self._keep_alive.append(var)
        return var

    # ------------------------------------------------------------ 骨架
    def _build(self) -> None:
        P, S = self.P, self.S
        head = tk.Frame(self.root, bg=P["bg"])
        head.pack(fill="x", padx=S(28), pady=(S(18), 0))
        tk.Label(head, text=self.T("app"), font=self.F(15, True), fg=P["text"],
                 bg=P["bg"]).pack(side="left")
        tk.Label(head, text="  " + self.T("badge"), font=self.F(9), fg=P["soft_text"],
                 bg=P["soft"], padx=S(8), pady=S(2)).pack(side="left", padx=(S(8), 0))
        AppButton(head, self.T("adv.button"), self.open_advanced,
                  button_type="info", palette=P, font=self.F, scale=S,
                  size="sm").pack(side="right", padx=(0, S(12)))

        # 中 / EN 分段开关（直角、1px 描边，跟旁边按钮同高）
        lang_box = tk.Frame(head, bg=P["card"], highlightthickness=1,
                            highlightbackground=P["border"])
        lang_box.pack(side="right", padx=(0, S(10)))
        for code, label in (("zh_CN", self.T("lang.zh")), ("en_US", self.T("lang.en"))):
            active = self.lang == code
            lbl = tk.Label(lang_box, text=label, font=self.F(9, True),
                           fg=P["accent_text"] if active else P["muted"],
                           bg=P["accent"] if active else P["card"],
                           padx=S(9), pady=S(3), cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e, c=code: self.switch_lang(c))
        tk.Label(head, text="v%s" % __version__, font=self.F(9), fg=P["muted"],
                 bg=P["bg"]).pack(side="right", padx=(0, S(10)))
        self._headline = tk.Label(head, text="", font=self.F(10), fg=P["muted"],
                                  bg=P["bg"])
        self._headline.pack(side="right", padx=(0, S(14)))

        self._dots = tk.Frame(self.root, bg=P["bg"])
        self._dots.pack(fill="x", padx=S(28), pady=(S(10), 0))

        # 先把状态条和页脚用 side="bottom" 钉在底下，再让编辑区吃剩下的空间：
        # 第 3 步内容最高，按原来的 pack 顺序最后两个会被挤出窗口（状态行只剩半截）。
        status_row = tk.Frame(self.root, bg=P["bg"])
        status_row.pack(side="bottom", fill="x", padx=S(28), pady=(0, S(10)))
        self._status = tk.Label(status_row, text="", font=self.F(9), fg=P["muted"],
                                bg=P["bg"], anchor="w")
        self._status.pack(side="left")
        self._progress = ttk.Progressbar(status_row, mode="determinate", length=S(220))
        self._worker = None
        self._queue: "queue.Queue" = queue.Queue()

        self._footer = tk.Frame(self.root, bg=P["bg"])
        self._footer.pack(side="bottom", fill="x", padx=S(28), pady=(S(14), S(6)))

        self._editor = tk.Frame(self.root, bg=P["bg"])
        self._editor.pack(fill="both", expand=True, padx=S(28), pady=(S(6), 0))

    def switch_lang(self, code: str) -> None:
        """界面内切换中英：重建头部与内容，状态和已填写的内容都不丢。"""
        if code == self.lang:
            return
        old_default = self.T("base_name.default")
        self.lang = code
        set_language(code)
        self.tx = _texts(code)
        if self.base_name.get().strip() in (old_default, "标签", "label"):
            self.base_name.set(self.T("base_name.default"))
        for child in self.root.winfo_children():
            child.destroy()
        self.root.title("%s v%s" % (self.T("app"), __version__))
        self._build()
        self.render()

    @staticmethod
    def _clear(frame: tk.Frame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    @staticmethod
    def _widen_at_least(btn: "AppButton", ratio: float = 1.8) -> None:
        """把按钮宽度兜到「高 × ratio」以上，免得短文案把它缩成一个方块。

        tk 的 ``width`` 以字为单位，而中文按字宽直接算是会偏窄、甚至裁字的，
        所以先拿实际字体的单位字宽把差的像素折算回字宽。
        """
        unit = max(1, tkfont.Font(font=btn.cget("font")).measure("0"))
        need = btn.winfo_reqwidth()
        floor = int(round(btn.winfo_reqheight() * ratio))
        if need >= floor:
            return
        padx = int(btn.cget("padx"))
        btn.configure(width=max(1, int(round((floor - 2 * padx) / float(unit)))))

    def _state_label(self) -> str:
        """界面上只显示相对 home 的短路径，别把 C:\\Users\\<名字> 摆给用户看。"""
        raw = str(self.state_file)
        try:
            rel = os.path.relpath(os.path.abspath(raw), os.path.expanduser("~"))
        except (ValueError, OSError):
            return raw
        if rel.startswith(".."):
            return raw
        return "~/" + rel.replace(os.sep, "/")

    def _status_text(self) -> str:
        state = self.T("state_saved") if self.flow.last_error is None else self.T("state_unsaved")
        return self.T("status", n=self.flow.number, total=self.flow.total, state=state) \
            + "   " + self._state_label()

    # ------------------------------------------------------------ 渲染
    def render(self) -> None:
        P, S = self.P, self.S
        self._headline.configure(text=self.T("step_of", title=self.T("step." + self.flow.current),
                                             n=self.flow.number, total=self.flow.total))
        self._clear(self._dots)
        for i, step in enumerate(self.flow.steps, 1):
            if i == self.flow.number:
                fg = P["accent"]
            elif self.flow.is_skipped(step):
                fg = P["muted"]
            elif i < self.flow.number:
                fg = P["dot_done"]
            else:
                fg = P["dot_off"]
            tk.Label(self._dots, text="●", font=self.F(10), fg=fg, bg=P["bg"]).pack(
                side="left", padx=S(2))

        self._clear(self._editor)
        holder = tk.Frame(self._editor, bg=P["bg"])
        holder.pack(fill="both", expand=True)
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=0)   # 内容固定贴顶：换屏时标题不跳
        holder.grid_rowconfigure(2, weight=1)   # 多余空间全留在下面
        middle = tk.Frame(holder, bg=P["bg"])
        middle.grid(row=1, column=0, sticky="ew")
        screens.build(self, middle)

        # 页脚只放导航：选纸那站的「跳过」跟「下一步」做的是同一件事（都带着当前选中的纸型往前），
        # 放纸方向那站的两条路在卡片里，所以这里不再出现「跳过」。
        self._clear(self._footer)
        if not self.flow.is_first:
            AppButton(self._footer, self.T("prev"), self.prev_step,
                      button_type="cancel", palette=P, font=self.F, scale=S,
                      size="md").pack(side="left")

        label = self.T("finish") if self.flow.is_last else self.T("next")
        command = self.finish_step if self.flow.is_last else self.next_step
        primary = AppButton(self._footer, label, command, button_type="submit",
                            palette=P, font=self.F, scale=S, size="lg")
        # 最后一步的「完成」比「下一步 →」短得多，不兜底会缩成方块；只兜到一个
        # 长方形比例（宽 ≥ 高 × 1.8），不强行拉成一样宽，否则文字会显得空荡荡。
        self._widen_at_least(primary, ratio=1.8)
        primary.pack(side="right")

        self._status.configure(text=self._status_text())

    # ------------------------------------------------------------ 动作
    def on_change(self) -> None:
        """任何一步的答案变了都走这里：存档 + 刷新状态条。"""
        self.save()
        self._status.configure(text=self._status_text())

    def save(self) -> None:
        if not self.autosave:
            return
        written = self.flow.save()
        if written is not None:
            self.state_file = written

    def goto(self, target) -> None:
        if self.flow.goto(target):
            self.save()
            self.render()

    def next_step(self) -> None:
        if self.flow.next():
            self.save()
            self.render()

    def prev_step(self) -> None:
        if self.flow.prev():
            self.save()
            self.render()

    def skip_step(self) -> None:
        last = self.flow.is_last
        self.flow.skip()
        self.save()
        if last:                      # 最后一站跳过 = 收工
            self.close()
        else:
            self.render()

    def finish_step(self) -> None:
        self.flow.finish()
        self.save()
        self.close()

    # ------------------------------------------------------------ 扫描
    def ask_scan(self) -> None:
        """选一张扫描件 → 量 → 把结果摆在第 1 屏上（不直接落盘）。"""
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=self.T("sheet.scan"),
            filetypes=[("扫描件", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff"),
                       ("所有文件", "*.*")])
        if not path:
            return
        self.measurement = None
        self.scan_error = None
        self._status.configure(text=self.T("sheet.measuring"))
        self.root.update_idletasks()
        try:
            grid = screens._selected(self).to_grid()
            self.measurement = measure_file(path, expect_cols=grid.cols,
                                            expect_rows=grid.rows)
            self.scan_source = path
        except Exception as exc:      # 扫得太淡 / 不是这张纸 / 文件坏了
            self.scan_error = str(exc)
        self.render()

    def _pick_photo(self):
        from tkinter import filedialog

        return filedialog.askopenfilename(
            title=self.T("sheet.photo"),
            filetypes=[("照片 JPG/PNG", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"),
                       ("所有文件", "*.*")])

    def ask_photo_calibrated(self) -> None:
        """默认路线：标定板 + 胶纸并排拍一张，先解镜头畸变再量。"""
        path = self._pick_photo()
        if not path:
            return
        self.measurement = None
        self.scan_error = None
        self._status.configure(text=self.T("sheet.photo_busy"))
        self.root.update_idletasks()
        try:
            from ..scan_calib import measure_photo_calibrated

            grid = screens._selected(self).to_grid()
            self.measurement = measure_photo_calibrated(path, expect_cols=grid.cols,
                                                        expect_rows=grid.rows)
            self.scan_source = path
            self.photo_fallback = False
        except Exception as exc:
            self.scan_error = str(exc)
        self.render()

    def ask_photo_plain(self) -> None:
        """应急路线：没有标定板，只靠 A4 纸四边——精度低，界面上会明确标出来。"""
        path = self._pick_photo()
        if not path:
            return
        self.measurement = None
        self.scan_error = None
        self._status.configure(text=self.T("sheet.photo_busy"))
        self.root.update_idletasks()
        try:
            from ..scan_photo import measure_photo

            grid = screens._selected(self).to_grid()
            self.measurement = measure_photo(path, expect_cols=grid.cols,
                                             expect_rows=grid.rows)
            self.scan_source = path
            self.photo_fallback = True
        except Exception as exc:
            self.scan_error = str(exc)
        self.render()

    def save_board(self) -> None:
        """把标定板 PDF 存到用户选的位置并打开。"""
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            title=self.T("sheet.board"), defaultextension=".pdf",
            initialfile="ulpp标定板.pdf", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            from ..scan_board import make_board_pdf

            make_board_pdf(path)
            self._status.configure(text=self.T("sheet.board_saved", path=path))
            self._open_path(path)
        except Exception as exc:
            self.scan_error = str(exc)
            self.render()

    def save_measurement(self) -> None:
        m = self.measurement
        if m is None:
            return
        tpl = Template(
            id=Template.new_id("scan"), name="扫描的纸",
            cols=m.cols, rows=m.rows, cell_w_mm=m.cell_w_mm, cell_h_mm=m.cell_h_mm,
            pitch_x_mm=m.pitch_x_mm, pitch_y_mm=m.pitch_y_mm,
            origin_x_mm=m.first_x_mm, origin_y_mm=m.first_y_mm,
            page_w_mm=m.page_w_mm, page_h_mm=m.page_h_mm,
            rotation_deg=m.rotation_deg, confidence=m.confidence,
            source="scan:" + os.path.basename(self.scan_source or ""))
        self.templates.upsert(tpl)
        self.flow.answer("paper", "tpl:" + tpl.id)
        self.measurement = None
        self.scan_error = None
        self.save()
        self.render()

    # ------------------------------------------------------------ 方向
    def _read_feed(self) -> str:
        if self.store is None:
            return ""
        try:
            return str(self.store.get_printer().feed or "")
        except Exception:
            return ""

    def direction_label(self) -> str:
        feed = self.feed or ""
        key = "feed." + feed
        return self.T(key) if key in self.tx else self.T("orient.unknown")

    def open_wizard(self) -> None:
        """复用 v1 的 9 步校准向导，结论写进同一份 PrinterProfile。"""
        from ..wizard import CalibrationWizard

        profile = PrinterProfile()
        if self.store is not None:
            try:
                profile = self.store.get_printer()
            except Exception:
                pass

        def on_save(feed: str, off_x: float, off_y: float) -> None:
            self.feed = feed
            if self.store is not None:
                try:
                    p = self.store.get_printer()
                    p.feed, p.offset_x_mm, p.offset_y_mm = feed, off_x, off_y
                    self.store.save_printer(p)
                    self.store.save()
                except Exception:
                    pass
            self.render()

        CalibrationWizard(self.root, palette="aero", profile=profile, on_save=on_save,
                          output_dir=os.getcwd())

    # ------------------------------------------------------------ 内容 / 输出
    def attach_text_box(self, box) -> None:
        """记住输入框：render() 会重建控件，粘过的文字不能丢；顺手挂上拖拽。"""
        self._text_box = box
        if _HAS_DND:
            try:
                box.drop_target_register(DND_FILES)     # type: ignore[attr-defined]
                box.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            except Exception:      # pragma: no cover - 少数环境没有 DND
                pass
        if self.content_text and not box.get("1.0", "end-1c"):
            box.insert("1.0", self.content_text)
        box.bind("<KeyRelease>", lambda _e: setattr(self, "content_text",
                                                    box.get("1.0", "end-1c")))

    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")

    def pick_pdfs(self) -> None:
        from tkinter import filedialog

        paths = filedialog.askopenfilenames(
            title=self.T("output.pick"),
            filetypes=[("PDF / 图片", "*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                       ("所有文件", "*.*")])
        self._add_inputs(list(paths or ()))

    def bind_drop(self, widget, handler) -> None:
        """给任意控件挂"把文件拖上来"：handler(path) 由调用方提供。"""
        if not _HAS_DND:
            return
        try:
            widget.drop_target_register(DND_FILES)          # type: ignore[attr-defined]
            widget.dnd_bind("<<Drop>>",                    # type: ignore[attr-defined]
                            lambda e: handler(self.drop_path(e)))
        except Exception:                                    # pragma: no cover
            pass

    def drop_path(self, event) -> Optional[str]:
        try:
            paths = list(self.root.tk.splitlist(event.data))
        except Exception:
            return None
        return paths[0] if paths else None

    def _on_drop(self, event) -> None:     # pragma: no cover - 需要真拖拽
        try:
            paths = list(self.root.tk.splitlist(event.data))
        except Exception:
            return
        self._add_inputs(paths)

    def pick_folder(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(title=self.T("output.add_folder"))
        if path:
            self._add_inputs([path])

    def pick_zip(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(title=self.T("output.add_zip"),
                                          filetypes=[("Zip", "*.zip")])
        if path:
            self._add_inputs([path])

    def _add_inputs(self, paths) -> None:
        """PDF 走 expand_inputs（支持文件夹 / zip），图片按扩展名收（每张图一张卡）。"""
        from ..cli import expand_inputs

        images = []
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            if ext in self.IMAGE_EXTS:
                images.append(path)
            elif os.path.isdir(path):
                for root_dir, _dirs, files in os.walk(path):
                    for name in files:
                        if os.path.splitext(name)[1].lower() in self.IMAGE_EXTS:
                            images.append(os.path.join(root_dir, name))
        try:
            found = expand_inputs(list(paths))
        except Exception as exc:
            self.output_error = str(exc)
            found = []
        for path in found:
            if path not in self.files:
                self.files.append(path)
        for path in images:
            if path not in self.images:
                self.images.append(path)
        if found or images:
            self.output_error = None
        self.render()

    def pick_out_dir(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(title=self.T("output.out_dir"))
        if path:
            self.out_dir.set(path)
            self.on_options()

    def clear_files(self) -> None:
        self.files.clear()
        self.images.clear()
        self.output_path = None
        self.render()

    def remove_selected_inputs(self) -> None:
        """内容页的「移除选中」：只删列表里勾中的那几条。"""
        box = getattr(self, "_input_list", None)
        items = getattr(self, "_input_items", None) or []
        if box is None or not items:
            return
        drop = {items[i] for i in box.curselection() if 0 <= i < len(items)}
        if not drop:
            return
        self.files = [p for p in self.files if p not in drop]
        self.images = [p for p in self.images if p not in drop]
        self.output_path = None
        self.output_error = None
        self.save()
        self.render()

    # ------------------------------------------------------------ 首次启动
    def needs_first_run_guide(self) -> bool:
        """第一次用这个程序吗：没存过胶纸、没有自定义模板、也没写过引导标记。"""
        try:
            if (Path(self.state_file).parent / FIRST_RUN_MARK).exists():
                return False
        except OSError:
            return False
        has_sheet = bool(getattr(self.store, "sheets", None))
        has_tpl = bool(getattr(self.templates, "items", None))
        return not has_sheet and not has_tpl

    def mark_first_run_done(self) -> None:
        """写一个标记文件：跳过一次之后别再每次启动都弹校准。"""
        try:
            folder = Path(self.state_file).parent
            folder.mkdir(parents=True, exist_ok=True)
            (folder / FIRST_RUN_MARK).write_text("1", encoding="utf-8")
        except OSError:
            pass

    def on_options(self) -> None:
        """勾选项存进进度存档，下次打开还是这套。"""
        self.flow.answers.update({
            "pages_first": bool(self.first_page_only.get()),
            "align": self.text_align.get(),
            "uniform": bool(self.text_uniform.get()),
            "proof": bool(self.make_proof.get()),
            "csv": bool(self.make_csv.get()),
            "marks": bool(self.make_marks.get()),
            "out_dir": self.out_dir.get(),
            "base_name": self.base_name.get(),
        })
        self.save()

    def clear_content(self) -> None:
        self.files.clear()
        self.images.clear()
        self.content_text = ""
        if self._text_box is not None:
            self._text_box.delete("1.0", "end")
        self.output_path = None
        self.output_error = None
        self.render()

    def _out_dir(self) -> str:
        typed = self.out_dir.get().strip()
        if typed:
            return typed
        if self.files:
            return os.path.join(os.path.dirname(self.files[0]), "ulpp输出")
        return os.path.join(os.path.expanduser("~"), "Documents", "ulpp输出")

    def generate(self) -> None:
        """后台线程出图：主线程只负责进度条，不卡界面。"""
        if self._worker is not None and self._worker.is_alive():
            return
        if self._text_box is not None:
            self.content_text = self._text_box.get("1.0", "end-1c")
        items = parse_text_block(self.content_text)
        if not self.files and not self.images and not items:
            self.output_error = self.T("output.need_content")
            self.output_path = None
            self.render()
            return
        self.output_error = None
        self.output_path = None
        grid = screens._selected(self).to_grid()
        job = dict(
            files=list(self.files), images=list(self.images), items=items,
            first_page=bool(self.first_page_only.get()),
            out_dir=self._out_dir(),
            base_name=self.base_name.get().strip() or "标签",
            proof=bool(self.make_proof.get()),
            csv=bool(self.make_csv.get()),
            marks=bool(self.make_marks.get()),
            align=self.text_align.get(),
            uniform=bool(self.text_uniform.get()),
            grid=grid,
        )
        self._queue = queue.Queue()
        self._worker = threading.Thread(target=self._generate_work, args=(job,), daemon=True)
        self._worker.start()
        self._status.configure(text=self.T("output.busy"))
        self._progress.configure(mode="indeterminate")
        self._progress.pack(side="left", padx=(self.S(12), 0))
        self._progress.start(12)
        self._poll_generate()

    def _generate_work(self, job: dict) -> None:
        """线程里跑：解析 → 排版 → 出图；只往队列里丢消息。"""
        q = self._queue
        try:
            pdfs = [parse_many([f], first_page_only=job["first_page"])[0]
                    for f in job["files"]]
            outs = build_all(
                pdfs, job["grid"], job["out_dir"], base_name=job["base_name"],
                make_proof=job["proof"], make_csv=job["csv"],
                text_items=job["items"], image_paths=job["images"],
                progress=lambda stage, done, total: q.put(("progress", done, max(1, total))),
                log=lambda msg: q.put(("log", msg)),
                text_align=job["align"], text_uniform=job["uniform"])
            q.put(("done", outs))
        except Exception as exc:      # 线程里不能抛给 Tk
            q.put(("error", str(exc)))

    def _poll_generate(self) -> None:
        finished = False
        try:
            while True:
                kind, *payload = self._queue.get_nowait()
                if kind == "progress":
                    done, total = payload
                    self._progress.stop()
                    self._progress.configure(mode="determinate", maximum=total, value=done)
                    self._progress.pack(side="left", padx=(self.S(12), 0))
                    self._status.configure(text=self.T("output.busy") + " %d/%d" % (done, total))
                elif kind == "done":
                    outs = payload[0] if payload else {}
                    self.output_path = next(iter(outs.values())) if outs else None
                    finished = True
                elif kind == "error":
                    self.output_error = payload[0] if payload else "?"
                    finished = True
        except queue.Empty:
            pass
        if finished:
            self._progress.stop()
            self._progress.pack_forget()
            self._worker = None
            self.render()
            return
        self.root.after(120, self._poll_generate)

    def _open_path(self, path: str) -> None:
        """跨平台打开文件：Windows / macOS / Linux。"""
        import subprocess
        import sys

        try:
            if os.name == "nt":
                os.startfile(path)              # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    def open_output(self) -> None:
        if self.output_path:
            self._open_path(self.output_path)

    def _selected_grid(self):
        return screens._selected(self).to_grid()

    def _wizard_button(self, parent, text, command):
        """"初次校准"入口：用强调色、比普通按钮大一号，一眼能看到。"""
        return AppButton(parent, text, command, button_type="submit",
                         palette=self.P, font=self.F, scale=self.S, size="lg")

    def open_calibrate(self) -> None:
        """初次校准向导：新型号的胶纸量一次尺寸。"""
        from .calibrate import CalibrateWizard

        CalibrateWizard(self)

    def open_partial(self) -> None:
        """接着打：用上次没用完的半张纸。"""
        from .partial import PartialWindow

        PartialWindow(self)

    # ------------------------------------------------------------ 高级参数
    def open_advanced(self) -> None:
        from .advanced import AdvancedDialog

        AdvancedDialog(self)

    def apply_advanced(self, template: Template) -> None:
        self.templates.upsert(template)
        self.flow.answer("paper", "tpl:" + template.id)
        self.save()
        self.render()

    def reset_flow(self) -> None:
        self.flow.reset()
        self.save()
        self.render()

    def close(self) -> None:
        self.save()
        self.root.destroy()


def main(lang: Optional[str] = None, flow_path: Optional[str] = None,
         autoplay: bool = False) -> int:
    """``python -m ulpp`` 的入口（2.0 起默认就是这里）。"""
    enable_dpi_awareness()
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()   # type: ignore[misc]
    flow = Flow.load(flow_path) if flow_path else Flow.load()
    shell = Shell(root, flow=flow, lang=lang)
    if shell.needs_first_run_guide():   # 第一次用：直接把初次校准摆到脸上
        shell.mark_first_run_done()
        root.after(300, shell.open_calibrate)
    if autoplay:  # 只给截图/冒烟脚本用：自动一屏屏走到头
        root.after(600, lambda: _autoplay(shell))
    root.mainloop()
    return 0


def _autoplay(shell: "Shell") -> None:
    if not shell.flow.is_last:
        shell.next_step()
        shell.root.after(500, lambda: _autoplay(shell))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
