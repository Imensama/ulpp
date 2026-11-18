# 按钮体系：单一 `AppButton` + 固定语义样式

**状态：已实施（P1–P3 完成，P4 剩视觉/键盘微调）。**

目标：全应用只允许一种按钮构造方式，
样式固定在类内部，调用方只能用 `button_type` 选 5 种语义之一，避免每个界面
各写一套 `tk.Button(...)` 然后颜色/字号/内边距慢慢漂移。

## 1. 现状盘点

实施前 `grep "tk.Button\|ttk.Button" src/ulpp`：**47 处，分布在 8 个模块**；
实施后只剩 `ui/buttons.py` 一处（其余全部改用 `AppButton`）。

| 模块 | 处数 | 现在怎么建按钮 |
|---|---:|---|
| `partial_gui.py` | 18 | 到处 `ttk.Button(...)`，样式靠默认 theme |
| `gui.py`（v1） | 9 | 同上 |
| `wizard.py` | 6 | `tk.Button(...)` 手写 fg/bg/padx/pady |
| `ui/shell.py` | 5 | 内联 `tk.Button(...)` + `_wizard_button()` |
| `ui/partial.py` | 4 | `ttk.Button(...)` |
| `ui/advanced.py` | 2 | `ttk.Button(...)` |
| `ui/calibrate.py` | 2 | `_button()` 辅助 + Canvas 圆角按钮 |
| `ui/screens.py` | 1 | `_button()` 辅助（大按钮） |

问题不在数量，而在**语义和样式没有绑定**：同一个"危险操作"在一个窗口是
`ttk` 默认灰、在另一个窗口是手写红底；同一个"主操作"有的 12pt 有的 13pt。
换主题/加 DPI 缩放时只能逐处改。

## 2. 目标 API

新增 `src/ulpp/ui/buttons.py`（唯一允许构造按钮的模块）：

```python
class ButtonType(str, Enum):
    SUBMIT = "submit"      # 主操作：保存 / 生成 / 下一步 / 打开
    CANCEL = "cancel"      # 次要 / 取消 / 返回 / 关闭
    WARNING = "warning"    # 需要留意的不可逆操作：覆盖、清空
    DANGER = "danger"      # 破坏性：删除纸张记录、抹掉配置
    INFO = "info"          # 说明性 / 帮助 / 查看


class AppButton(tk.Button):
    def __init__(self, master, text, command=None, *,
                 button_type: ButtonType | str, ctx, size="md",
                 state="normal", width=None):
        ...


class ButtonContext(Protocol):
    P: dict          # 调色板
    def F(self, size, bold=False): ...
    def S(self, px): ...
```

约束（在类内部强制，调用方绕不过去）：

- `button_type` 只接受 `ButtonType` 或 5 个字符串；其它值 → `ValueError`；
- 禁止传入 `bg/fg/font/padx/pady/relief/bd/highlightthickness/activebackground/...`；
  传了 → `TypeError`（样式只能由类型决定）；
- 允许的额外参数只有：`text/command/size/state/width`；
- `size` 只有 `sm|md|lg`；
- 禁用态、悬停态、按下态、边框、光标、焦点环都在类内根据类型推导。

### 2.1 五种类型的固定视觉

| 类型 | 用途 | 背景 | 文字 | 悬停背景 | 边框 |
|---|---|---|---|---|---|
| `submit` | 主操作 | `P["accent"]` | `P["accent_text"]` | `P["soft_text"]` | 无 |
| `cancel` | 取消/返回 | `P["card"]` | `P["text"]` | `P["chip"]` | `P["border"]` 1px |
| `warning` | 覆盖/清空 | `#B45309` | `#FFFFFF` | `#92400E` | 无 |
| `danger` | 删除/抹除 | `#B91C1C` | `#FFFFFF` | `#991B1B` | 无 |
| `info` | 帮助/查看 | `P["soft"]` | `P["soft_text"]` | `P["chip"]` | 无 |

`warning` 与 `danger` 的区别写死：**amber = 提醒但仍可继续；red = 破坏性操作**。

### 2.2 尺寸

| size | 字号 | padx | pady | 最小高度 |
|---|---|---|---:|---:|---:|
| `sm` | 10 | S(10) | S(5) | S(28) |
| `md` | 11 | S(16) | S(9) | S(36) |
| `lg` | 13（bold） | S(24) | S(13) | S(48) |

所有像素过 `ctx.S()`，DPI 缩放自动一致。

## 3. 落地阶段

### P0 盘点与护栏（已完成）

- 写 `scripts/button_inventory.py`：ast 扫描 `tk.Button`/`ttk.Button`/自定义
  `_button()` 的调用点，输出 `模块:行:类型` 表格（先只报告，不阻断）；
- 存一份 v2 主界面截图 + v1 主界面截图作为视觉基线；
- 把 `docs/design/button-system.md`（本文）挂到 README 索引。

### P1 类与测试（已完成）

- 实现 `AppButton` + `ButtonType`；
- 单元测试（不建窗的映射测试 + 建窗冒烟）：
  - 五种类型 → 颜色/边框/字号与表一致；
  - 未知类型 / 禁用关键字参数立即报错；
  - 禁用态颜色、`command` 触发、`size` 缩放；
  - 主题切换后颜色来自新调色板。
- **CI 检查点**：`tests/test_buttons.py`（新增独立 job，同语言检查点）。

### P2 迁移（已完成）

顺序（先 v2，后 v1；先低风险，后主界面）：

1. `ui/advanced.py`、`ui/partial.py`（单纯 ttk → AppButton）；
2. `ui/screens.py` 的 `_button()` 删除，改调 `AppButton`；
3. `ui/shell.py`（含 `_wizard_button`）；
4. `ui/calibrate.py`（`_button` + `_choice`；Canvas 圆角按钮统一改为
   `lg submit/cancel`，删掉 `_round_button`/`_gradient_image`）；
5. `partial_gui.py`（18 处，先换危险/主操作，再换普通）；
6. `gui.py`（9 处）；
7. `wizard.py`（6 处，注意它有自己的 9 步布局）。

每个模块迁移后跑该模块的 UI 测试 + 截图对比；不允许"先合代码后补测试"。

### P3 强制（已完成）

- 在 `tests/test_constraints.py` 增加：
  ```python
  def test_no_raw_buttons_outside_buttons_module(self):
      # ast 扫描：src/ulpp 下除 ui/buttons.py 外不得出现
      # tk.Button / ttk.Button / 函数名 _button 的调用
  ```
- 保留白名单：`ui/buttons.py`（以及迁移完成前的 `# TODO(button):` 行清单，
  每项带 issue 编号，P3 结束清零）；
- CI 失败信息直接给出 `file:line`，修起来明确。

### P4 收尾（剩余）

- 删除旧的 `_button` / `_wizard_button` / `_round_button` / `_gradient_image`；
- 键盘可达性：Tab 顺序、空格/回车触发、焦点环；
- 英文文案变长时按钮不截断（中英都测）；
- 对比度检查（红/琥珀底 + 白字 ≥ WCAG AA）。

## 4. 测试与 CI 检查点

| 检查点 | 内容 | 何时跑 |
|---|---|---|
| `test_buttons.py` | 5 类型样式表、非法类型/参数、禁用、缩放、command | PR（独立 job） |
| 现有 UI 测试 | 每个界面的按钮仍可点、文案正确 | PR（全量） |
| 约束测试 | 除 `buttons.py` 外禁止 raw button | PR（全量，P3 起） |
| 视觉基线 | 8 个模块迁移前后截图对比 | 手动 + PR 附件（可选） |
| 语言检查点 | 按钮文案跟随语言切换 | PR（已有 job） |

## 5. 验收标准

- `grep -rn "tk.Button\|ttk.Button" src/ulpp --include="*.py"` 只命中
  `ui/buttons.py`；
- 全部按钮只传 `button_type`，没有调用方再传颜色/字体；
- 五个类型在浅色/单色/暖色/铜色/vista/teal/aero 七个主题下都有定义，
  缺失主题键时回退到 LIGHT，不允许某个主题"按钮看不见"；
- `tests/test_buttons.py` 在 Linux（Xvfb）+ macOS + Windows 三条线都通过；
- 语言切换后按钮文案改变、尺寸不溢出。

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| ttk → tk 的观感变化（尤其 v1） | 分模块迁移 + 截图对比；接受"更统一"的轻微视觉差异 |
| Canvas 圆角按钮被删后视觉退化 | `lg` 类型保留更明显的主/次对比；后续可加圆角渲染但不暴露样式参数 |
| 主题扩展时漏配颜色 | `ButtonType → 语义键` 映射 + 缺键回退测试 |
| 英文文案比中文长 | 固定 `width` 只在明确需要时使用；默认随内容 + `wraplength` |
| 迁移期新旧混用 | P3 前用白名单清单，P3 后一次性清零并开约束测试 |
