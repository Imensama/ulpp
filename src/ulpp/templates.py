# -*- coding: utf-8 -*-
"""胶纸模板库：把"量出来/手填的规格"存起来，排版时先选模板。

和 ``GridSpec`` 的分工：``GridSpec`` 是**排版引擎**用的几何（老代码只认它），
``Template`` 是**用户资产**（一台机器可以有多张纸，含扫描得到的置信度、来源）。
``Template.to_grid()`` 负责把模板翻译成 ``GridSpec``，排版引擎一行不用改。

存档：``%APPDATA%\\ulpp\\templates.json``；``ULPP_STATE_DIR`` 可改路径（测试/沙箱用）。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import GridSpec

STATE_FILE = "templates.json"
ENV_STATE_DIR = "ULPP_STATE_DIR"


def _state_dir() -> Path:
    override = os.environ.get(ENV_STATE_DIR)
    if override:
        return Path(override)
    base = os.environ.get("APPDATA")
    return Path(base) / "ulpp" if base else Path.home() / ".ulpp"


@dataclass(frozen=True)
class Template:
    """一张胶纸的规格。单位 mm，origin 是第一条切割线的位置（纸左上角为原点）。"""

    id: str
    name: str
    cols: int
    rows: int
    cell_w_mm: float
    cell_h_mm: float
    pitch_x_mm: float
    pitch_y_mm: float
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0
    page_w_mm: float = 210.0
    page_h_mm: float = 297.0
    rotation_deg: float = 0.0
    shape: str = "rect"           # rect | circle | triangle（M4）
    shape_param: float = 0.0
    inset_mm: float = 2.0         # 安全边
    confidence: float = 1.0       # 扫描得到的置信度；手填 = 1.0
    source: str = "manual"        # preset:45 / scan:文件名 / manual
    created: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M"))

    @property
    def count(self) -> int:
        return self.cols * self.rows

    def to_grid(self) -> GridSpec:
        """翻成老排版引擎的 GridSpec（旋转先不参与，M1 只量不转）。"""
        return GridSpec(
            page_w=self.page_w_mm, page_h=self.page_h_mm,
            cols=self.cols, rows=self.rows,
            cell_w=self.cell_w_mm, cell_h=self.cell_h_mm,
            pitch_x=self.pitch_x_mm, pitch_y=self.pitch_y_mm,
            margin_top=self.origin_y_mm, margin_left=self.origin_x_mm,
            inset=self.inset_mm,
        )

    def label(self) -> str:
        return "%s（%d×%d · %.1f×%.1f）" % (
            self.name, self.cols, self.rows, self.pitch_x_mm, self.pitch_y_mm)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> Optional["Template"]:
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                id=str(data["id"]), name=str(data.get("name") or data["id"]),
                cols=int(data["cols"]), rows=int(data["rows"]),
                cell_w_mm=float(data["cell_w_mm"]), cell_h_mm=float(data["cell_h_mm"]),
                pitch_x_mm=float(data["pitch_x_mm"]), pitch_y_mm=float(data["pitch_y_mm"]),
                origin_x_mm=float(data.get("origin_x_mm", 0.0)),
                origin_y_mm=float(data.get("origin_y_mm", 0.0)),
                page_w_mm=float(data.get("page_w_mm", 210.0)),
                page_h_mm=float(data.get("page_h_mm", 297.0)),
                rotation_deg=float(data.get("rotation_deg", 0.0)),
                shape=str(data.get("shape", "rect")),
                shape_param=float(data.get("shape_param", 0.0)),
                inset_mm=float(data.get("inset_mm", 2.0)),
                confidence=float(data.get("confidence", 1.0)),
                source=str(data.get("source", "manual")),
                created=str(data.get("created", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def from_grid(cls, grid, name: str, source: str = "manual",
                  confidence: float = 1.0) -> "Template":
        """把一个 GridSpec（预设/手填）包成模板。"""
        return cls(
            id=cls.new_id(source), name=name, cols=grid.cols, rows=grid.rows,
            cell_w_mm=grid.cell_w, cell_h_mm=grid.cell_h,
            pitch_x_mm=grid.pitch_x, pitch_y_mm=grid.pitch_y,
            origin_x_mm=grid.margin_x, origin_y_mm=grid.margin_top,
            page_w_mm=grid.page_w, page_h_mm=grid.page_h,
            inset_mm=grid.inset, confidence=confidence, source=source)

    @classmethod
    def new_id(cls, source: str = "manual") -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return "%s-%s-%s" % (source.split(":")[0], stamp, uuid.uuid4().hex[:4])


def adjusted(base: Template, *, cols=None, rows=None, cell_w_mm=None, cell_h_mm=None,
             pitch_x_mm=None, pitch_y_mm=None, origin_x_mm=None, origin_y_mm=None,
             inset_mm=None, dx_mm=0.0, dy_mm=0.0, name=None) -> Template:
    """在现有模板上改几个数（None = 不动），并可选整体微调 dx/dy（等效挪格阵）。"""
    data = base.to_dict()
    for key, value in (("cols", cols), ("rows", rows), ("cell_w_mm", cell_w_mm),
                       ("cell_h_mm", cell_h_mm), ("pitch_x_mm", pitch_x_mm),
                       ("pitch_y_mm", pitch_y_mm), ("origin_x_mm", origin_x_mm),
                       ("origin_y_mm", origin_y_mm), ("inset_mm", inset_mm)):
        if value is not None:
            data[key] = value
    data["origin_x_mm"] = float(data["origin_x_mm"]) + float(dx_mm)
    data["origin_y_mm"] = float(data["origin_y_mm"]) + float(dy_mm)
    if name:
        data["name"] = name
    item = Template.from_dict(data)
    if item is None:
        raise ValueError("模板参数不合法")
    if item.cols < 1 or item.rows < 1:
        raise ValueError("列数/行数必须 ≥ 1")
    if item.pitch_x_mm < item.cell_w_mm or item.pitch_y_mm < item.cell_h_mm:
        raise ValueError("节距不能小于格子尺寸")
    return item


class TemplateStore:
    """模板库：读写一个 JSON 列表；坏文件不抛，退化成空库。"""

    def __init__(self, path: Optional[Path] = None, directory: Optional[Path] = None) -> None:
        self.path = Path(path) if path else (
            Path(directory) / STATE_FILE if directory else _state_dir() / STATE_FILE)
        self.items: List[Template] = []
        self.last_error: Optional[str] = None
        self.load()

    # ---------------- 读写 ----------------
    def load(self) -> "TemplateStore":
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            self.items = []
            return self
        items = []
        for entry in raw if isinstance(raw, list) else []:
            item = Template.from_dict(entry)
            if item is not None:
                items.append(item)
        self.items = items
        return self

    def save(self) -> Optional[Path]:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".templates.", suffix=".tmp", dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump([t.to_dict() for t in self.items], fh, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            self.last_error = None
            return self.path
        except OSError as exc:
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            return None

    # ---------------- 查询 / 增删 ----------------
    def get(self, template_id: str) -> Optional[Template]:
        for item in self.items:
            if item.id == template_id:
                return item
        return None

    def upsert(self, template: Template) -> Template:
        for i, item in enumerate(self.items):
            if item.id == template.id:
                self.items[i] = template
                break
        else:
            self.items.append(template)
        self.save()
        return template

    def remove(self, template_id: str) -> bool:
        before = len(self.items)
        self.items = [t for t in self.items if t.id != template_id]
        if len(self.items) != before:
            self.save()
            return True
        return False

    def __len__(self) -> int:
        return len(self.items)
