## Why

两处 UI 一致性问题影响体验：(1) 切到「设备信息 / App 列表 / Crash 报告 / 系统日志」等 tab（含子页面）时会自动把焦点落到输入框，干扰用户；(2) 各路径输入框对「上下文根」的显示不统一——有的显示 `/`、有的显示 `Documents`、相册显示 `/DCIM`，不直观。

## What Changes

- **#2 取消自动聚焦输入框**：tab 切换与进入子页面时 MUST NOT 自动聚焦任何输入框。唯一例外：键鼠操作打开键盘输入捕获时，自动聚焦捕获输入框（保持现状）。
- **#9 路径根统一为 `/`**：所有设备文件浏览路径框 MUST 把**当前上下文的根**显示为 `/`。例如浏览某 App 的 `Documents` 时，根显示为 `/`（而非 `Documents`）；相册根显示为 `/`（而非 `/DCIM`）。底层真实路径映射不变，仅统一显示语义；「上一级」在上下文根禁用、非根启用的规则保持一致。

## Capabilities

### Modified Capabilities

- `slide6-desktop-shell`: tab / 子页面切换默认不自动聚焦输入框（键鼠键盘捕获除外）。
- `slide6-app-manager`: App 文件浏览器路径框将上下文根（含 `Documents` 根）统一显示为 `/`。
- `slide6-dcim-album`: 相册路径框将上下文根（`/DCIM`）显示为 `/`。

## Impact

- 代码：`slide6_ui/common/afc_browser.py`（`_display_path` / `_parse_path` 根显示统一为 `/`）、`slide6_ui/album/dcim_album.py`（DCIM 根显示）、各 tab / 子页面（取消默认聚焦：调整 focusPolicy 或显式聚焦中性控件）、`slide6_ui/keymouse/keymouse_tab.py`（保留键盘捕获聚焦）。
- 行为：documents 浏览不再显示 `Documents` 前缀、相册不再显示 `/DCIM` 前缀，均显示为 `/` 起的相对上下文路径；切 tab 不再抢焦点。
- 文件系统 / Crash 报告路径框现已显示 `/`，无需改动（仅纳入统一规则）。
- 无新增依赖。
