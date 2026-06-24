# webinspector-op Specification

## Purpose
TBD - created by archiving change devtools-webinspector-phase2. Update Purpose after archive.
## Requirements
### Requirement: 可调试页面枚举

平台层 SHALL 提供 `list_web_pages(target)`：经 WebInspector（lockdown 服务，iOS 17+ 走 tunnel 的 `com.apple.webinspector.shim.remote`，**不需要 DDI**）枚举可调试的 App 与页面，归一化为 `{app, bundle, page_id, title, url}` 列表，失败返回可读错误信封。设备未开启「Web 检查器」开关时（`WebInspectorNotEnabledError`）MUST 返回可读错误码（如 `WEBINSPECTOR_DISABLED`），而非崩溃。

#### Scenario: 枚举可调试页面

- **WHEN** 设备已开启「Web 检查器」且有打开的 Safari 标签 / 含 WebView 的 App
- **THEN** 返回页面列表（含 app/bundle/page_id/title/url）

#### Scenario: 未开启 Web 检查器

- **WHEN** 设备未开启「Web 检查器」开关
- **THEN** 返回可读错误（`WEBINSPECTOR_DISABLED`），UI 据此引导用户开启

### Requirement: CDP 桥接

平台层 SHALL 提供 `open_cdp_bridge(target, host, port)`：在本机起一个 CDP（Chrome DevTools Protocol）server（默认 `127.0.0.1:9222`），把设备 WebInspector（WIP）桥接为 CDP，供 Chrome DevTools 连接。桥接 MUST 在后台运行、不阻塞 UI，并与子面板窗口生命周期绑定：起桥接创建、Stop/关窗 MUST 优雅关闭并释放端口，MUST NOT 残留占用端口的孤儿任务。端口被占用时 MUST 返回可读错误。

#### Scenario: 启动 CDP 桥接并用 Chrome 调试

- **WHEN** 用户对可调试页面启动 CDP 桥接
- **THEN** 本机 `localhost:<port>` 提供 CDP，用户可在 Chrome `chrome://inspect` 连上获得完整 DevTools

#### Scenario: 关闭窗口回收桥接

- **WHEN** Web 检查器子面板窗口被关闭
- **THEN** CDP server 优雅关闭、端口释放，无残留孤儿任务

