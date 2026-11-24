# -*- coding: utf-8 -*-
"""v2 外壳（全流程向导）—— M0 骨架。

模块分工：

- ``scale``   DPI 感知 / 按 ``tk scaling`` 缩放 / 配色字体
- ``flow``    六站状态机 + 存档（纯逻辑，可单测）
- ``screens`` 六屏内容与文案（中英）
- ``shell``   窗口骨架与页脚导航，入口 ``ulpp.ui.shell.main``

老界面 ``ulpp.gui`` / ``ulpp.partial_gui`` 保持不变；2.0 起 ``python -m ulpp`` 默认进这里，
老界面用 ``--v1``。
"""
