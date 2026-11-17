# -*- coding: utf-8 -*-
"""接着打的纯逻辑：把"内容"按顺序塞进"还能打的格子"。

不碰 Tk、不碰 PDF —— 只决定哪个内容进哪一格：
- ``placements`` 直接喂给 ``builder.build_partial_all``；
- ``leftover`` 是塞不下的条数（内容比空格子多时会截断，界面据此提示）。
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple


def plan_placements(free_cells: Sequence[int],
                    entries: Sequence[object]) -> Tuple[Dict[int, object], int]:
    """按格子顺序填内容；返回 ({格号: 内容}, 没塞下的条数)。"""
    slots: List[int] = list(free_cells)
    usable = slots[:len(entries)]
    placements = dict(zip(usable, entries))
    return placements, max(0, len(entries) - len(usable))
