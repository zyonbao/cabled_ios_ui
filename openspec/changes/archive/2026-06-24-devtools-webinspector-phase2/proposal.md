## Why

「开发者工具」缺少 Web 调试入口。排查 Safari 页面 / 应用内 WebView 时，用户需要在外部手动找设备、开 Chrome `chrome://inspect`，上下文割裂。本变更在开发者工具内提供「Web 检查器」子面板：列出可调试页面，并一键起 CDP 桥接，用 Chrome DevTools 获得完整调试体验。

> 真机已验证（iOS 26 + tunnel）：`com.apple.webinspector.shim.remote` 经 tunnel 可启动；开启「Web 检查器」后枚举到真实页面（Safari / YouTube，含 app/bundle/page_id/title/url）；未开开关时报 `WebInspectorNotEnabledError`。**不需要 DDI，仅需 tunnel（17+）。**

## What Changes

- 在 `DeveloperToolsTab` 增加「Web 检查器」功能卡片，打开子面板（非独立 sidebar Tab）。
- 平台层新增 WebInspector 能力：
  - `list_web_pages(target)`：枚举可调试 App + 页面（app 名/bundle、page_id、title、url）；
  - CDP 桥接句柄：在本地起 pymobiledevice3 的 CDP server（默认 `127.0.0.1:9222`），与子面板窗口生命周期绑定，关窗/Stop 回收。
- UI：可刷新的页面列表 + 「启动/停止 CDP 桥接」+ 显示连接入口（`chrome://inspect` 或 `localhost:9222`）。
- 前置检测：未开「Web 检查器」开关时（`WebInspectorNotEnabledError`）给出明确引导（设置 → Safari → 高级 → Web 检查器）。

## Capabilities

### Added Capabilities

- `webinspector-op`：平台层 WebInspector 能力（页面枚举 + CDP 桥接 + 前置/降级语义）。

### Modified Capabilities

- `slide6-developer-tools`：新增「Web 检查器」功能卡片与子面板交互。

## Impact

- 代码：
  - `slide6_ui/developer_tools/developer_tools_tab.py`（入口与单例窗口）
  - `slide6_ui/developer_tools/`（新增 web inspector dialog）
  - `ios_toolkit/toolkit_api.py`（`list_web_pages` + `open_cdp_bridge`）
  - `ios_toolkit/device.py`（WebInspector 枚举 + CDP 桥接句柄、生命周期回收）
  - `slide6_ui/languages/zh-CN.json`、`en-US.json`（文案）
- Spec：`openspec/specs/webinspector-op/spec.md`、`openspec/specs/slide6-developer-tools/spec.md`
- 依赖：复用现有 tunnel；CDP 桥接依赖 `uvicorn`/`fastapi`/`wsproto`（已随 `pymobiledevice3` 安装，无需新增）。
