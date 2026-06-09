## Why

`slide6_ui` 已覆盖设备信息 / 相册 / 文件系统 / App 列表 / 键鼠等高频场景，但缺少三类排障与管理刚需能力：配置描述文件管理、设备崩溃日志（crash）导出、系统日志实时流查看。三者底层均依赖成熟的 lockdown 服务（`mobile_config` / `crash_reports` / `syslog` + `os_trace`），无需 WDA 或 XPC tunnel，实现成本低、价值明确，是 `TODO.md` 路线图中优先级最高的待办。

## What Changes

- **描述文件管理（融入「App 列表」Tab）**：在 App 列表工具栏新增「描述文件…」按钮，打开独立对话框，支持：
  - 列出当前设备已安装的配置描述文件（标识符 / 名称 / 类型 / 组织等）。
  - 拖拽 `.mobileconfig` 文件或点击安装（安装通常需设备端「设置」手动确认，UI 给出明确提示）。
  - 多选 + 移除（受监管 / MDM 描述文件可能拒绝移除，错误回显）。
- **Crash 报告（新增独立 Tab）**：列出当前设备所有崩溃日志（`.ips` / `.crash` 等），支持：
  - 按文件名过滤（大小写不敏感子串，仅作用于渲染）。
  - 多选导出、多选删除；右键弹出菜单提供导出 / 删除。
  - 导出时可选「保留设备原文件」，不保留则导出成功后从设备删除对应 crash。
- **App 列表（增强既有 Tab）**：系统应用（`appType` 为 `System`）不再提供「卸载」入口（设备本就拒绝卸载系统应用）。
- **系统日志实时流（新增独立 Tab）**：下拉选择 `syslog`（传统 syslog_relay）或 `oslog`（`os_trace` 结构化流），支持：
  - 实时流式展示 + 关键字过滤 + 暂停 / 清空 / 另存为文本。
  - 后台线程采集、主线程限速渲染（参考 `mirror.py` 线程模型），避免刷爆 UI。
- **toolkit_api 契约扩展**：在平台能力层新增描述文件、crash、日志流相关同步函数与流式订阅接口，沿用现有 `{ok, data}` 信封约定。

## Capabilities

### New Capabilities

- `mobile-config-op`: toolkit_api 描述文件契约——列出 / 安装 / 移除配置描述文件（基于 `MobileConfigService`，lockdown，免 WDA/tunnel）。
- `crash-reports-op`: toolkit_api crash 契约——列出 / 导出（pull）/ 删除（clear）设备崩溃日志（基于 `CrashReportsManager`，AFC2，免 WDA/tunnel）。
- `syslog-stream-op`: toolkit_api 日志流契约——订阅 / 停止 `syslog` 与 `oslog` 实时流（基于 `SyslogService` 与 `OsTraceService`，免 WDA/tunnel）。
- `slide6-profile-management`: 桌面应用「App 列表」Tab 内的描述文件管理对话框（拖拽安装、列表、多选移除）。
- `slide6-crash-reports`: 桌面应用独立「Crash 报告」Tab（列表、多选 / 右键导出与删除、导出可选保留原文件）。
- `slide6-syslog-stream`: 桌面应用独立「系统日志」Tab（syslog/oslog 下拉、实时流、关键字过滤、暂停 / 清空 / 另存）。

### Modified Capabilities

- `slide6-app-manager`: 「卸载」按钮由「始终展示」改为「仅对非系统应用展示」；系统应用不提供卸载能力。

## Impact

- **新增代码**：
  - `ios_toolkit/device.py`：新增 `iOSDevice` 上的描述文件 / crash / 日志流方法（沿用 `_bg_loop` + `run_coroutine_threadsafe`，流式接口为长生命周期生成器）。
  - `ios_toolkit/toolkit_api.py`：新增对应的 `{ok, data}` 包装函数。
  - `slide6_ui/profiles/`（描述文件对话框）、`slide6_ui/crash/`（Crash Tab）、`slide6_ui/syslog/`（系统日志 Tab）三个新模块。
  - `slide6_ui/app_manager/app_manager.py`：新增「描述文件…」按钮入口。
  - `slide6_ui/main_window.py`：注册两个新 Tab，并在设备切换时分发 `set_target`。
- **依赖**：复用现有 `pymobiledevice3`（9.16.0，已含 `mobile_config` / `crash_reports` / `syslog` / `os_trace`），无新增第三方依赖。
- **安全 / 合规**：日志流可能含敏感信息，仅落地用户显式「另存」的本地文件；描述文件 / crash 删除为破坏性操作，统一二次确认；不写入任何凭据 / 令牌到日志。
- **不受影响**：现有 Tab、WDA / tunnel 生命周期、JSON CLI 既有命令保持不变。
