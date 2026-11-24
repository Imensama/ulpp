# Contributing

欢迎帮忙。这个项目**很小、很实用**：把 PDF 卡片或一段文字排进 A4 标签纸，离线、不联网、不依赖 AI。

## 先跑起来

```powershell
git clone https://github.com/Imensama/ulpp.git
cd ulpp
python -m pip install -r requirements.txt
python -m pip install -e .
$env:PYTHONPATH = "$PWD\src"
python -m ulpp            # 新外壳（2.0 起默认）
python -m ulpp --v1       # 老界面（兼容模式）
python -m unittest discover -s tests -t .    # 782 个用例
```

> 拍照量纸需要可选依赖：`pip install -e ".[photo]"`（会装 OpenCV）。

## 目录速查

| 路径 | 干什么 |
|---|---|
| `src/ulpp/parser.py` | 从 PDF 里找"卡片"、读字段、算内容框 |
| `src/ulpp/builder.py` | 排版与输出（含网格参考版、CSV、边缘刻度） |
| `src/ulpp/scan*.py` | 扫描件 / 照片 / 标定板 → 量出格阵 |
| `src/ulpp/templates.py` | 胶纸模板库（双语名字就存在这里） |
| `src/ulpp/ui/` | v2 外壳：`shell` / `screens` / `texts` / `calibrate` |
| `src/ulpp/gui.py`、`wizard.py` | v1 老界面与 9 步向导（**别重写**，v2 复用） |
| `tests/` | 只用 `unittest`，不引 pytest |
| `docs/design/` | 为什么这么做、试过什么失败 |

## 硬规矩（PR 会被检查这几条）

1. **离线**：不能引入联网、云服务、AI 调用的硬依赖。
2. **不用 Qt / WebView / customtkinter**：只用 tkinter（体积与内网部署）。
3. **双语**：新增文案必须同时写 `zh_CN` 和 `en_US`（`tests/test_v2_texts.py` 会校验）；
   界面代码里**不要硬编码中文**，报错和默认文件名也要进文案表。
4. **测试**：`python -m unittest discover -s tests -t .` 必须全绿；新逻辑尽量配用例。
5. **不含客户数据**：仓库里不放客户图纸、真实扫描件、带公司名的截图；
   复现问题请用代码合成 PDF（参考 `tests/test_parser_overlap.py`）。
6. **最小改动**：不要顺手重构没被要求改的地方。

## 提交信息

```
fix(parser): 相邻格文字重叠不再并卡
feat(v2): 初次校准改为二选一
docs: 补发版检查清单
ci: 打 tag 时同时产出全功能包
```

## 发版（维护者）

见 [`AGENTS.md`](AGENTS.md) 的「发版检查清单」：版本号三处一致、脱敏、双语、先提交后打 tag、
Release 两个附件（轻量 exe + 全功能 zip）。

## 想做什么

看 [`ROADMAP.md`](ROADMAP.md) 和 Issues；带 `good first issue` 的适合第一次提交。
不确定就先开个 Issue 描述思路，别直接写一大堆代码。
