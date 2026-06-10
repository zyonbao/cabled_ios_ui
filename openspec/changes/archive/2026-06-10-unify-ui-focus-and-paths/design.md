## Context

- **聚焦**：未发现显式 `setFocus` 强制聚焦输入框（仅 `keymouse_tab` 在键盘捕获时显式 `kbd_capture.setFocus()`）。tab/子页切换时输入框被聚焦是 Qt 默认行为——控件显示后焦点落到 tab 序里第一个可聚焦控件（常是 `QLineEdit` 过滤/路径框）。
- **路径显示**：共享组件 `slide6_ui/common/afc_browser.py` 的 `AfcBrowserPanel._display_path()` / `_parse_path()` 按 `root` 决定显示：`documents` 根映射为 `Documents`（带前缀），`container`/`media` 为绝对路径（`/` 起）。相册 `dcim_album.py` 以 `/DCIM` 为上下文根，显示含 `/DCIM`。Crash 报告与文件系统已显示 `/`。

## Goals / Non-Goals

**Goals:**
- 切 tab / 进子页面不自动聚焦输入框；保留键鼠键盘捕获的自动聚焦。
- 所有文件浏览路径框把当前上下文根统一显示为 `/`（documents、DCIM 也显示 `/`）。

**Non-Goals:**
- 不改底层 AFC 路径解析 / 真实路径映射、不改导航夹紧（clamp）逻辑。
- 不改「上一级」启用/禁用规则（上下文根禁用，非根启用）——仅统一显示串。
- 不涉及日志重构（A）与就绪 / tunnel / 弹窗（B）。

## Decisions

1. **取消默认聚焦（#2）**：在各 tab 根容器/子页面层面避免首个输入框抢焦点。优先方案：进入 tab 时把焦点交给一个中性控件（如 tab 根 widget，`setFocusPolicy(Qt.NoFocus)` 的输入框不可行——会失去手动点选），更稳妥是**进入时不主动调用 setFocus，并把容器设为可接收焦点的初始焦点目标**（如对根 widget `setFocus()` 或对首个输入框 `clearFocus()`）。统一封装一个小助手在 tab `set_target`/显示时调用。键鼠键盘捕获的 `setFocus()` 保留。
2. **路径根统一为 `/`（#9）**：修改 `AfcBrowserPanel._display_path()`——所有 `root` 一律以 `/` 表示上下文根（去掉 `documents` 的 `Documents` 前缀），`_parse_path()` 相应把以 `/` 起的输入解析回该 root 下逻辑路径。相册 `dcim_album.py` 显示层把 `/DCIM` 上下文根渲染为 `/`（导航仍 clamp 在真实 `/DCIM` 内）。「上一级」在显示根（即真实上下文根）禁用。
3. **真实路径不变**：仅显示与回填解析改动；后端 `afc_list/afc_pull/...` 收到的仍是各 root 下的真实逻辑路径。

## Risks / Trade-offs

- documents 浏览失去 `Documents` 前缀的语境提示——符合用户明确诉求（统一为 `/`）；上下文已由所在 tab/对话框标题表达。
- 取消默认聚焦的实现需逐 tab 验证（不同 tab 首控件不同）；用统一助手降低遗漏。键盘捕获例外需回归确认仍自动聚焦。
- 相册 `/DCIM`→`/` 仅显示层变化，导航夹紧逻辑保持，避免越界。
