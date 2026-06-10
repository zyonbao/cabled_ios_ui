## Why

「开发者工具」与「键鼠操作」依赖 XPC tunnel / DDI 挂载 / RSD 开发者服务三类前置条件，但当前缺乏统一、清晰的就绪检查与引导：用户常在条件不满足时直接失败，不知该去挂 DDI 还是重启 tunnel。同时开发者工具有几处体验问题：tunnel 提示只有「启动」按钮、重启要输两次密码、出错文案会把窗口撑宽、子功能弹窗是模态只能逐个打开。

## What Changes

- 新增统一的**设备就绪前置检查与引导**：按设备版本判定并在能力不满足时给出可操作提示，而非直接失败。
  - iOS 17+：需要 tunnel 时检查并提示启用 XPC tunnel；需要 DDI 时提示去「开发者工具」根 tab 挂载 DDI；tunnel ready 且 DDI mounted 但对应 RSD 服务不工作时，提示重新挂载 DDI 或重启 XPC tunnel。
  - iOS 17 以下：需要 DDI 时提示去「开发者工具」根 tab 挂载 DDI，并提供 reload 按钮。
  - 「键鼠操作」与「开发者工具」的 DVT/WDA 相关能力均 MUST 经此前置检查。
- **6.1 tunnel 状态面板（仅 iOS 17+）**：开发者工具顶部仅在 iOS 17+ 设备展示 XPC tunnel 状态；未启动显示「启动」，已启动显示「停止」+「重启」按钮，均复用 osascript 提权逻辑。
- **6.2 单次密码重启**：重启 XPC tunnel 由「停止 + 启动」两次系统授权合并为**一次**授权（单条 `do shell script ... with administrator privileges` 内完成 kill + 后台重启）。
- **5 出错文案不撑宽窗口**：开发者工具底部状态/错误文案 MUST NOT 改变窗口宽度，超过 3 行自动对尾部做省略（`…`），窗口尺寸变化时按同规则重排。
- **8 子功能弹窗非模态**：开发者工具的进程管理 / 虚拟定位等子功能窗口改为非模态，允许同时打开多个并各自独立操作。

## Capabilities

### New Capabilities

- `slide6-device-readiness`: 统一的设备就绪前置检查与引导（按 iOS 版本对 tunnel / DDI / RSD 的检查矩阵与可操作提示），供键鼠操作与开发者工具共用。

### Modified Capabilities

- `slide6-developer-tools`: 顶部 tunnel 状态面板仅 iOS 17+ 展示并提供启动/停止/重启；DVT 功能位经设备就绪前置检查；底部文案不撑宽窗口（3 行省略）；子功能弹窗改非模态。
- `slide6-tunnel-bootstrap`: 重启 tunnel 合并为单次系统授权；提供停止 / 重启控制入口。
- `slide6-screen-mirror`: 键鼠操作的 WDA/DVT 启动流程接入统一的设备就绪前置检查与引导。

## Impact

- 代码：`slide6_ui/developer_tools/developer_tools_tab.py`（tunnel 面板、就绪门控、文案省略、非模态弹窗）、`slide6_ui/developer_tools/process_dialog.py` / `location_dialog.py`（非模态生命周期）、`slide6_ui/common/tunnel.py`（单次授权重启）、`slide6_ui/keymouse/keymouse_tab.py`（接入就绪检查）、可能新增 `slide6_ui/common/readiness.py`（共享前置检查助手）。
- 行为：重启 tunnel 仅一次密码；条件不满足时给出引导而非直接失败；可同时打开多个子功能窗口。
- 无新增第三方依赖。
