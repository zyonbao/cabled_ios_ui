# diagnostics-op Specification

## Purpose
定义诊断工具层能力：电源控制（重启/关机/睡眠）与诊断信息读取（电池、Wi-Fi、ioregistry 等），并统一成功/失败返回结构与错误本地化入口。
## Requirements
### Requirement: 诊断服务版本感知连接

`ios_toolkit` SHALL 提供诊断 API，内部以版本感知方式打开 `pymobiledevice3` 的 `DiagnosticsService`：iOS < 17 经 usbmux/lockdown 连接，iOS 17+ 经 RSD（依赖 XPC tunnel）连接。逻辑层 MUST 保持零 i18n，对外仅返回统一错误信封（`ok` / `error` 含 `kind`、英文 debug `message`、可选稳定 `code`、`details`）。当 iOS 17+ 缺少 XPC tunnel 时，MUST 返回 `code = TUNNEL_REQUIRED` 的错误信封。

#### Scenario: iOS 17 以下经 usbmux 连接

- **WHEN** 目标设备 iOS 主版本 < 17 且调用任一诊断 API
- **THEN** 经 usbmux/lockdown 打开 `DiagnosticsService` 并返回结果信封

#### Scenario: iOS 17+ 缺少 tunnel

- **WHEN** 目标设备 iOS 主版本 ≥ 17 且 XPC tunnel 未运行时调用诊断 API
- **THEN** 返回 `ok=false`、`error.code = TUNNEL_REQUIRED` 的错误信封，不抛未捕获异常

### Requirement: 电源控制操作

`ios_toolkit` SHALL 提供 `device_restart` / `device_shutdown` / `device_sleep` 三个电源操作 API，分别经 `DiagnosticsService` 下发 Restart / Shutdown / Sleep 请求。操作下发成功（服务返回 Success）即返回 `ok=true`，MUST NOT 轮询设备侧重启/关机回执。下发失败 MUST 返回带稳定 `code` 的错误信封。

#### Scenario: 重启下发成功

- **WHEN** 调用 `device_restart` 且服务返回 Success
- **THEN** 返回 `ok=true`

#### Scenario: 关机后设备断连

- **WHEN** 调用 `device_shutdown`，请求已成功下发
- **THEN** 返回 `ok=true`，不因随后设备断连而判定为失败

### Requirement: 诊断信息查询

`ios_toolkit` SHALL 提供 `diagnostics_battery` / `diagnostics_wifi` / `diagnostics_info` / `diagnostics_ioregistry` API，返回对应的结构化诊断数据（dict）置于结果信封的数据字段中。任一查询失败 MUST 返回带稳定 `code` 的错误信封。

#### Scenario: 查询电池状态

- **WHEN** 调用 `diagnostics_battery` 且设备就绪
- **THEN** 返回 `ok=true` 且数据字段为电池信息字典

#### Scenario: 查询 IORegistry

- **WHEN** 调用 `diagnostics_ioregistry` 且设备就绪
- **THEN** 返回 `ok=true` 且数据字段为 IORegistry 结构

### Requirement: MobileGestalt 查询与弃用处理

`ios_toolkit` SHALL 提供 `diagnostics_mobilegestalt` API。当目标设备 iOS ≥ 17.4（Apple 弃用 MobileGestalt）导致底层抛出 `DeprecationError` 时，MUST 兜底为 `ok=false`、`error.code = MOBILEGESTALT_DEPRECATED` 的错误信封，而非未捕获异常。

#### Scenario: 低版本查询成功

- **WHEN** 目标设备 iOS < 17.4 调用 `diagnostics_mobilegestalt`
- **THEN** 返回 `ok=true` 且数据字段为 MobileGestalt 键值

#### Scenario: 高版本弃用兜底

- **WHEN** 目标设备 iOS ≥ 17.4 调用 `diagnostics_mobilegestalt` 触发库的 `DeprecationError`
- **THEN** 返回 `ok=false`、`error.code = MOBILEGESTALT_DEPRECATED`

