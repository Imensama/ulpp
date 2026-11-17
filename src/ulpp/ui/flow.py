# -*- coding: utf-8 -*-
"""v2 向导的状态机（2 站：选胶纸 → 放纸方向）：纯逻辑，不依赖 Tk，能单独测。

为什么要单独一层：向导要支持「跳过 / 重跑单项 / 关掉重开接着上次」，
这些规则写在界面里就纠缠不清，单独成一层后 shell 只负责按 ``flow.current`` 渲染。

存档位置：``%APPDATA%\\ulpp\\v2_flow.json``；环境变量 ``ULPP_STATE_DIR`` 可改写到别的目录
（沙箱里 %APPDATA% 只读、测试要用临时目录，都靠它）。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

STEP_IDS: Tuple[str, ...] = ("sheet", "orient", "output")
STATE_VERSION = 3
ENV_STATE_DIR = "ULPP_STATE_DIR"
STATE_FILE = "v2_flow.json"


def default_state_dir() -> Path:
    """配置目录：``ULPP_STATE_DIR`` > ``%APPDATA%\\ulpp`` > 家目录。"""
    override = os.environ.get(ENV_STATE_DIR)
    if override:
        return Path(override)
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "ulpp"
    return Path.home() / ".ulpp"


def state_path(path: Optional[Path] = None, directory: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(directory) / STATE_FILE if directory is not None else default_state_dir() / STATE_FILE


class Flow:
    """六站状态机：位置、跳过、每步答案、是否完成。"""

    def __init__(self, steps: Sequence[str] = STEP_IDS, index: int = 0,
                 skipped: Optional[Sequence[str]] = None,
                 answers: Optional[Dict[str, object]] = None,
                 finished: bool = False) -> None:
        self.steps: Tuple[str, ...] = tuple(steps) or STEP_IDS
        self.index = max(0, min(int(index), len(self.steps) - 1))
        self.skipped: List[str] = [s for s in (skipped or ()) if s in self.steps]
        self.answers: Dict[str, object] = dict(answers or {})
        self.finished = bool(finished)
        self.last_error: Optional[str] = None

    # ---------------- 位置 ----------------
    @property
    def current(self) -> str:
        return self.steps[self.index]

    @property
    def total(self) -> int:
        return len(self.steps)

    @property
    def number(self) -> int:
        """给人看的第几步（1 起）。"""
        return self.index + 1

    @property
    def is_first(self) -> bool:
        return self.index == 0

    @property
    def is_last(self) -> bool:
        return self.index == len(self.steps) - 1

    def next(self) -> bool:
        """前进一步；已经在最后一站则返回 False。"""
        if self.is_last:
            return False
        self.index += 1
        return True

    def prev(self) -> bool:
        if self.is_first:
            return False
        self.index -= 1
        return True

    def goto(self, target) -> bool:
        """跳到某站（id 或下标）；不认识的目标不动，返回 False。"""
        if isinstance(target, int):
            if 0 <= target < self.total:
                self.index = target
                return True
            return False
        if target in self.steps:
            self.index = self.steps.index(target)
            return True
        return False

    def skip(self) -> bool:
        """跳过当前站：记下来并前进；已到最后一站则视为完成。"""
        if self.current not in self.skipped:
            self.skipped.append(self.current)
        if self.is_last:
            self.finished = True
            return False
        return self.next()

    def finish(self) -> None:
        self.finished = True

    def reset(self) -> None:
        self.index = 0
        self.skipped.clear()
        self.answers.clear()
        self.finished = False

    # ---------------- 答案 ----------------
    def answer(self, key: str, value: object = None, *, default: object = None):
        """``answer(k)`` 取；``answer(k, v)`` 存。"""
        if value is None:
            return self.answers.get(key, default)
        self.answers[key] = value
        return value

    def is_skipped(self, step: str) -> bool:
        return step in self.skipped

    # ---------------- 存取 ----------------
    def to_dict(self) -> Dict[str, object]:
        return {
            "version": STATE_VERSION,
            "steps": list(self.steps),
            "index": self.index,
            "skipped": list(self.skipped),
            "answers": self.answers,
            "finished": self.finished,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Flow":
        """尽量读懂；坏数据不抛，退回全新状态（向导不能因为存档坏了就打不开）。"""
        if not isinstance(data, dict):
            return cls()
        raw_steps = data.get("steps")
        steps = tuple(s for s in raw_steps if isinstance(s, str)) if isinstance(raw_steps, list) else None
        index = data.get("index") if isinstance(data.get("index"), int) else 0
        if steps is None:          # 没有 steps 字段：按当前布局，位置夹紧
            steps = STEP_IDS
        elif steps != STEP_IDS:    # 旧版布局（6 站）→ 换当前布局：从头开始，答案保留
            steps = STEP_IDS
            index = 0
        answers = data.get("answers")
        return cls(
            steps=steps,
            index=index,
            skipped=data.get("skipped") if isinstance(data.get("skipped"), list) else None,
            answers=answers if isinstance(answers, dict) else None,
            finished=bool(data.get("finished")),
        )

    def save(self, path: Optional[Path] = None, directory: Optional[Path] = None) -> Optional[Path]:
        """写存档；写不了不抛，记在 ``last_error`` 里返回 None。"""
        target = state_path(path, directory)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".v2_flow.", suffix=".tmp", dir=str(target.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            self.last_error = None
            return target
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    @classmethod
    def load(cls, path: Optional[Path] = None, directory: Optional[Path] = None) -> "Flow":
        """读存档；没有或读坏了就从第 1 站开始（不抛）。"""
        target = state_path(path, directory)
        try:
            with open(target, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(data)

    def saved_at(self, path: Optional[Path] = None, directory: Optional[Path] = None) -> bool:
        return state_path(path, directory).is_file()
