# -*- mode: python ; coding: utf-8 -*-
"""v2 打包配置（onedir）：带扫描/拍照量纸，所以要把 OpenCV 和 numpy 打进去。

用法（在项目根目录）：
    python -m PyInstaller --noconfirm packaging/ulpp_v2.spec

产物：``dist/ulpp2/ulpp2.exe``
- 不带参数 → 老界面（v1.3.x 那套）
- 带 ``--v2`` → 新外壳（向导）
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(SPECPATH)) if "SPECPATH" in globals() else os.getcwd()
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

a = Analysis(
    [os.path.join(ROOT, "packaging", "entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=[(os.path.join(SRC, "ulpp", "locales"), "ulpp/locales"),
           (os.path.join(SRC, "ulpp", "assets"), "ulpp/assets")],
    hiddenimports=[
        "tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk",
        "tkinter.font", "PIL.ImageTk",
        "ulpp.partial_gui", "ulpp.ui", "ulpp.ui.shell", "ulpp.ui.screens",
        "ulpp.ui.flow", "ulpp.ui.scale", "ulpp.ui.texts", "ulpp.ui.calibrate",
        "ulpp.ui.advanced", "ulpp.ui.partial",
        "ulpp.scan", "ulpp.scan_photo", "ulpp.scan_calib", "ulpp.scan_board",
        "ulpp.scan_dewarp", "ulpp.templates", "ulpp.partial",
        "cv2", "numpy", "tkinterdnd2",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pytest", "PyInstaller", "pandas",
              "pypdfium2", "PIL.AvifImagePlugin", "PIL.ImageQt"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 瘦身：视频编解码器（opencv 带的 ffmpeg）和 pdfium 我们都不用，直接剔掉
_DROP = ("opencv_videoio_ffmpeg", "pdfium", "avif")
a.binaries = [b for b in a.binaries if not any(k in b[0].lower() for k in _DROP)]
a.datas = [d for d in a.datas if not any(k in d[0].lower() for k in _DROP)]

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ulpp2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # 不压壳：避免杀软误报
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ulpp2",
)
