# AGENTS.md

给 AI 编程助手（以及新接手的人）的入场说明。**先读这份，再动代码。**

## 这是什么

`ulpp`（通用标签打印平台 / Universal Label Printing Platform）：把 PDF 里的卡片或一段文字，
按份数排进 A4 不干胶标签纸，并保证 100% 不缩放；支持"接着打"（用掉上次没用完的半张）。
纯离线、单文件分发、tkinter 界面。

## 目录

```
src/ulpp/            包代码
  parser.py          解析 PDF 里的"卡片"（名称/编号/尺寸/数量…）
  builder.py         排版并输出 PDF（含网格参考版、清单 CSV、边缘对位刻度）
  sheets.py          打印机配置 + 胶纸记录（%APPDATA%\ulpp\sheets.json）
  scan.py            从扫描件/校正后的照片量格阵（节距、相位、置信度）
  scan_photo.py      手机照片：找 A4 四边 → 单应 → 交给 scan
  scan_calib.py      标定板模式（先解镜头畸变 k1，再量）+ 手动点四角兜底
  scan_board.py      生成标定板 PDF
  templates.py       胶纸模板库（Template → GridSpec）
  partial.py         接着打的内容分配（纯逻辑）
  ui/                v2 外壳：shell / screens / texts / flow / scale / calibrate / advanced / partial
  gui.py             v1 老界面（**不要动**，入口 python -m ulpp）
  wizard.py          v1 的 9 步位置校准向导（v2 复用，不要重写）
tests/               140+ 个 unittest（pytest 未引入，机器上没装）
docs/design/         设计记录：为什么这么做、试过什么失败了
packaging/           PyInstaller 配置（ulpp.spec 单文件 / ulpp_onedir.spec / ulpp_v2.spec）
```

## 跑起来

```powershell
cd <repo>
$env:PYTHONPATH = "$PWD\src"
python -m ulpp            # 新外壳（2.0 起默认）
python -m ulpp --v1       # 老界面（兼容模式）
python -m ulpp --help     # 命令行
python -m unittest discover -s tests -t .    # 全部测试
```

## 打包

```powershell
python -m PyInstaller --noconfirm packaging/ulpp_v2.spec   # dist/ulpp2/ulpp2.exe（含 OpenCV，约 168MB）
python -m PyInstaller --noconfirm packaging/ulpp_onedir.spec
```

## 硬约束（改代码前先看）

1. **离线**：不联网、不依赖 AI/云。识别与测量必须本地完成。
2. **不用 Qt / PySide / customtkinter / WebView**：只用 tkinter（体积与内网部署原因）。
3. **不改名字**：包名、exe、配置目录都叫 `ulpp`；不要再出现 `label_sheet` / `ULP`。
4. **v1 的界面与向导不要重写**：`gui.py`、`partial_gui.py`、`wizard.py` 保持可用，
   v2 是"新入口 + 新外壳"，两者并存。
5. **最小可用**：不要主动加安全层、不要顺手重构没被要求改的地方。
6. **版本号只在发版时改**（`pyproject.toml` + `src/ulpp/__init__.py` 两处一起改）。

## 已知的坑（踩过，别重踩）

- 本机 PowerShell 的 `Set-Content -Encoding UTF8` 会写 **BOM**；`locales/*.json` 带 BOM 会让测试挂。
  用 `python -c` 或 `[System.IO.File]::WriteAllText` 写文件。
- Windows 沙箱里：`%APPDATA%` 只读、`tempfile.mkdtemp()` 建的目录不可写（用 `os.makedirs`）、
  目录删不掉（测试别用 `TemporaryDirectory`）。
- 拍照量纸的精度上限由**纸的平整度**决定（0.3~0.6 mm），不是算力；详见 `docs/design/photo-measurement.md`。
- **断言“不存在”前必须先查**（2026-11-18 踩过）：我按旧知识断言 `actions/checkout@v7` 和
  Python 3.15 不存在，实际两者都已发布——外部事实（版本、API 行为、字段名）必须现场查证
  （`web_search`/`web_fetch` 或本地实测），查不到就写“未核实”，不要凭记忆下结论。
- PDF 解析里"相邻两格文字坐标重叠"会把两张卡粘成一张：取词必须同时尝试
  `use_text_flow=True/False` 并取锚点多的那份。


## 发版检查清单（打 tag 前逐条过）

1. **版本号三处一致**：`pyproject.toml`、`src/ulpp/__init__.py`、tag 名（`v1.4.3` ↔ `1.4.3`），
   否则 `publish.yml` 的校验会直接失败。
2. **脱敏**：
   - 仓库里不能有客户图纸、真实扫描件、截图里的公司名/型号；
   - 不能出现 `C:\Users\...` 这类本机路径；
   - 打包产物里不能带 `ulpp.log`、`v2_flow.json`、`templates.json`、测试脚本；
   - README 里的图片用 `raw.githubusercontent.com/...` 绝对链接（相对路径在 PyPI 上是破图）。
3. **双语**：新增/修改的文案必须同时写 `zh_CN` 和 `en_US`（`tests/test_v2_texts.py` 会校验 key 与占位符）；
   **禁止在界面代码里硬编码中文**（错误信息、默认文件名也算），要进文案表。
4. **本地验证**：`python -m unittest discover -s tests -t .` 全绿；界面至少手点一遍主流程。
5. **先提交、再打 tag**：tag 一旦推送就会发 PyPI，而 PyPI 不可覆盖；改完必须重新发版本号。
6. **Release 附件**：轻量 `ulpp.exe`（无 OpenCV）+ 全功能 `ulpp-<tag>-full-windows-x64.zip`（含 OpenCV），
   发版说明里写清“下载哪个”（中英双语）。
7. **README 截图与渲染**：界面动过就重新截图（`docs/v2-*.png` 用绝对 raw 链接引用）；
   发版后要真的打开看一眼——
   - GitHub 首页：图片、徽章、目录锚点是否正常；
   - PyPI 项目页：描述里的图片是否显示（**PyPI 描述只在发新版时更新**，改 README 不会自动生效）；
   - Release 页：附件名、下载说明是否与正文一致。

## 交付方式（每轮工作结束都要做）

用户不会记上下文，隔天回来只想要「复制 → 运行 → 看结果」。所以每次收尾必须给：

1. **绝对路径**：文件在哪、产物在哪，别写“工作区里那个文件”。
2. **可复制的命令块**：一条一条，带**预期输出**（比如 `Ran 153 tests ... OK`）。
3. **验收清单**：点哪里、看到什么算通过，3~5 条就够。
4. **提交与发版**：commit message 原文、要不要打 tag、打完去哪看结果。
5. 如果中间需要用户做选择，给**编号选项 + 推荐项**，不要开放式提问。

## 测试约定

- 只用 `unittest`，不加新依赖。
- 涉及客户的图纸**不进仓库**：需要真实样本时用代码合成 PDF（见 `tests/test_parser_overlap.py`）。
- 涉及图像处理的用例，没装 OpenCV 时用 `skipUnless` 跳过。
