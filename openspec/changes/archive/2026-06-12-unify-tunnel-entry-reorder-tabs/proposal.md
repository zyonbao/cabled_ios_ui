## Why

XPC tunnel 目前有三个分散的入口（开发者工具、诊断各有一套完整的启动/停止/重启面板，键鼠操作还会弹模态框追问是否启动 tunnel），用户对“到底在哪管理 tunnel”感到混乱，且重复实现增加维护成本。应将 tunnel 管理收敛到单一入口（开发者工具），其余功能在前置条件缺失时只做**非模态**的就地提示，引导用户去开发者工具完成启动/挂载。

## What Changes

- **统一 tunnel 管理入口**：仅「开发者工具」tab 保留 XPC tunnel 的启动 / 停止 / 重启 / 刷新控制面板，作为唯一入口。
- **诊断 tab 去除 tunnel 面板**：移除「诊断」tab 顶部的 tunnel 状态条与启停/重启按钮；当 iOS 17+ 设备 tunnel 未启用时，功能卡片置灰并就地提示「这些功能需要先启用 XPC tunnel，请到开发者工具启动 tunnel」（非模态）。
- **键鼠操作去除模态框**：移除选中设备后弹出的「是否启动 tunnel」模态 `QMessageBox`（`_gate_tunnel`）。当 tunnel 未启用或 DDI 未挂载时，直接在画面区 overlay / 状态栏给出提示，引导用户先去开发者工具启动 XPC tunnel 并挂载 DeveloperDiskImage，不再弹任何模态框、不再从键鼠侧自动拉起 tunnel。
- **sidebar 顺序调整**：将「开发者工具 / 键鼠操作 / 诊断」按此顺序连续排列。
- i18n 文案相应新增 / 调整（诊断的 tunnel 缺失提示、键鼠的 tunnel/DDI 缺失引导）。

## Capabilities

### New Capabilities
<!-- 无新增能力，均为对既有能力的需求调整 -->

### Modified Capabilities
- `slide6-tunnel-bootstrap`: tunnel 管理（启动/停止/重启）收敛为「开发者工具」单一入口；选中 iOS 17+ 设备且 tunnel 未就绪时不再弹模态提示与自动拉起，改为非模态就地引导。
- `slide6-diagnostics`: 移除诊断 tab 自带的 tunnel 状态条/控制；tunnel 未启用时卡片置灰并提示去开发者工具启动，不在本 tab 提供 tunnel 控制。
- `slide6-screen-mirror`: 键鼠操作在 tunnel 未启用或 DDI 未挂载时以非模态 overlay/状态提示引导去开发者工具，移除模态确认框。
- `slide6-desktop-shell`: 更新侧边 Tab 顺序需求，使「开发者工具 / 键鼠操作 / 诊断」按此顺序排列。

## Impact

- 代码：
  - `slide6_ui/diagnostics/diagnostics_tab.py`（移除 tunnel 面板与相关 handler，改门控提示）
  - `slide6_ui/keymouse/keymouse_tab.py`（移除 `_gate_tunnel` 模态与自动拉起，改 overlay/状态引导）
  - `slide6_ui/main_window.py`（调整 sidebar `addTab` 顺序）
  - `slide6_ui/languages/zh-CN.json`、`en-US.json`（文案增改）
- 不改动 `slide6_ui/common/tunnel.py` 与 `slide6_ui/common/readiness.py` 的底层能力；开发者工具的 tunnel 面板保持不变。
- 行为变化：键鼠/诊断不再能直接启动 tunnel；用户需先到开发者工具启动（单一入口）。
