# device-info-op Specification

## Purpose
TBD - created by archiving change add-app-list-and-file-manager. Update Purpose after archive.
## Requirements
### Requirement: 读取设备信息

`executor_ios.toolkit_api` SHALL 提供 `device_info(target)`，通过 lockdown（usbmux，无需配对）读取设备的全量公开属性并返回。返回值 SHALL 为 `ok` 包络，`data.info` 为字段名到值的扁平映射；原始字节类字段（如配对/证书 blob）SHALL 被剔除，嵌套结构 SHALL 以字符串形式呈现。该能力无需 WDA 或 XPC tunnel。

#### Scenario: 读取成功

- **WHEN** 对一台已连接设备调用 `device_info(target)`
- **THEN** 返回 `ok` 包络，`data.info` 至少包含可用的标识字段（如 `DeviceName`、`ProductType`、`ProductVersion`、`BuildVersion`、`SerialNumber`、`UniqueDeviceID`，有则返回）

#### Scenario: 设备不存在

- **WHEN** `target` 不对应任何已注册设备
- **THEN** 返回 `error` 包络，`error.kind` 为 `BAD_TARGET`

#### Scenario: 字节类字段被剔除

- **WHEN** lockdown 返回的属性包含字节类型的值
- **THEN** 这些字段不出现在 `data.info` 中（仅保留可读字段）

