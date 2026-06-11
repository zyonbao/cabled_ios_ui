# 移除描述文件导出功能

## Why

「描述文件」Tab 的导出功能在 iOS 上**根本无法实现**：

- iOS 的 MCInstall（`MobileConfigService.get_profile_list()`）出于安全设计，只返回已安装描述文件的**元数据**（`ProfileMetadata`：显示名 / 组织 / UUID / 版本），以及 `ProfileManifest`（仅含 `Description` / `IsActive`），**不返回任何原始字节**。
- 现有 `export_profile` 实现基于「`ProfileManifest[identifier]['Data']` 携带原始字节」这一错误假设，实测 `Data` 恒为 `None`，因此对任何描述文件导出都会失败（`NOT_FOUND` 或空文件）。
- 佐证：`pymobiledevice3` 官方 CLI 仅提供 `list / install / remove / store / supervise`，**没有任何 export / get / download** 命令。

该能力无法在 iOS 平台兑现，保留只会误导用户并产生噪声错误日志（如线上观察到的 `NOT_FOUND: profile not found on device: ...`）。决定彻底移除导出入口与相关平台能力。

## What Changes

- **移除** UI 层「导出选中」按钮及其全部导出流程（单选另存为 / 多选选目录）。
- **移除** 平台能力 `export_profile`（`ios_toolkit/toolkit_api.py` 与 `ios_toolkit/device.py`）。
- **移除** 相关 i18n 键（`profiles.export_*` 等），保留安装 / 移除 / 列表相关文案。
- 「描述文件」Tab 仍保留：列表展示、安装（点击 / 拖拽）、多选移除。

## Impact

- Affected specs: `slide6-profile-management`（移除「导出描述文件」需求）、`mobile-config-op`（移除「导出配置描述文件」需求）。
- Affected code: `slide6_ui/profiles/profiles_tab.py`、`ios_toolkit/toolkit_api.py`、`ios_toolkit/device.py`、`slide6_ui/languages/zh-CN.json`、`slide6_ui/languages/en-US.json`。
- 无数据迁移；纯功能下线，不影响列表 / 安装 / 移除。
