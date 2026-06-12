## Context

XPC tunnel（iOS 17+ 才需要）的管理目前散落在三处：

- `developer_tools_tab.py`：完整 tunnel 面板（启动/停止/重启/刷新），并在 DDI 挂载后按需重启 tunnel。这是功能最完整、语义最贴合的入口。
- `diagnostics_tab.py`：复制了一套同样的 tunnel 面板（`tunnel_label` + start/stop/restart/refresh），逻辑与 dev_tools 几乎重复。
- `keymouse_tab.py`：选中设备后用 `_gate_tunnel()` 弹模态 `QMessageBox` 追问是否启动 tunnel，确认则从键鼠侧 `tunnel.launch_tunneld()`。

底层能力已经很完善：`common/tunnel.py`（探测/启停/重启）与 `common/readiness.py`（`evaluate`/`probe` + `MISSING_TUNNEL/DDI/RSD` 引导文案）都是纯逻辑、可复用。本次只调整 UI 层的入口收敛与提示方式，不动底层。

## Goals / Non-Goals

**Goals:**
- tunnel 的启动/停止/重启控制只在「开发者工具」tab 出现，作为唯一入口。
- 诊断、键鼠在前置条件（tunnel / DDI）缺失时，仅做**非模态**就地提示，引导去开发者工具，不再各自提供 tunnel 控制、不再弹模态框、不再自行拉起 tunnel。
- sidebar 中「开发者工具 / 键鼠操作 / 诊断」按此顺序连续排列。

**Non-Goals:**
- 不改 `common/tunnel.py` / `common/readiness.py` 的行为与 API。
- 不改开发者工具 tab 现有 tunnel 面板及 DDI 挂载后“按需重启 tunnel”逻辑。
- 不调整 sidebar 中其它 tab（设备信息/相册/文件系统/App 列表/描述文件/Crash 报告）的相对位置（仅安排三者顺序）。

## Decisions

**1. 唯一入口 = 开发者工具。**
保留 `developer_tools_tab.py` 的 tunnel 面板原样；删除 `diagnostics_tab.py` 的 tunnel 面板与其 `_on_start/stop/restart/refresh_tunnel`、`_refresh_tunnel_panel`、`_set_tunnel_busy`、`tunnel_widget` 等。理由：dev_tools 同时管理 DDI，是 tunnel + DDI 的自然归属地，避免多入口状态不一致。

**2. 诊断改为“门控 + 非模态提示”。**
`diagnostics_tab._refresh_features()` 已经在 tunnel 缺失时把卡片置灰并设 tooltip。改动点：
- 删除顶部 tunnel 面板（UI 与 handlers）。
- tunnel 缺失时除 tooltip 外，把底部状态栏文案设为“需先到开发者工具启动 XPC tunnel”的引导（i18n 新键 `diagnostics.tunnel_required_goto_devtools`）。
- `on_tab_activated()` 仍重新探测 tunnel 状态并刷新门控（用户在开发者工具启动后切回诊断即可自动启用）。

**3. 键鼠改为“非模态 overlay/状态引导”，移除模态与自动拉起。**
`select_device()` 当前逻辑：`need and not running → _gate_tunnel(模态)`，否则 `_check_readiness`。改为：不再调用 `_gate_tunnel`；统一走就绪检查并把结果用 overlay/状态呈现：
- iOS 17+ 且 tunnel 未启用：overlay/状态提示“请先到开发者工具启动 XPC tunnel 并挂载 DeveloperDiskImage”。
- DDI 未挂载（含 iOS<17）：overlay 提示去开发者工具挂载 DDI（沿用既有 `keymouse.overlay_need_ddi` 思路）。
- 复用 `readiness.probe()` 的结构化结果与 `MISSING_*`；tunnel 缺失分支不再尝试启动，只提示。
- 删除 `_gate_tunnel`、`_after_tunnel`、`_tunnel_failed` 中与“自动拉起 tunnel”相关的路径（保留必要的状态/overlay 设置或合并到就绪分支）。

**4. sidebar 顺序。**
`main_window._build_ui()` 调整 `addTab` 调用顺序，使三者为「开发者工具 → 键鼠操作 → 诊断」。其余 tab 维持原相对顺序，三者整体放在末尾（它们是偏“高级/重”的能力）。`slide6-desktop-shell` 的 Tab 顺序需求同步更新。注意 `_on_tab_changed`/`_on_keymouse_tab` 依赖的是对象引用而非索引，重排不影响。

## Risks / Trade-offs

- [键鼠不能再一键拉起 tunnel，多一步操作] → 通过清晰的 overlay 文案直接告知去开发者工具；单一入口反而减少“在不同地方启动、状态不同步”的困惑。
- [诊断/键鼠与开发者工具的 tunnel 运行态需保持同步] → 已有 `on_tab_activated()` 在切回时重新探测；键鼠 `select_device` 每次重新就绪检查，能反映最新状态。
- [i18n 漏改导致出现键名] → 同步更新 zh-CN/en-US，并保留/复用现有 `readiness.*` 文案，新增键集中在 diagnostics/keymouse。
- [删除诊断/键鼠 tunnel 代码可能遗留无用 import/handler] → 改完用 lint 检查清理未使用引用。
