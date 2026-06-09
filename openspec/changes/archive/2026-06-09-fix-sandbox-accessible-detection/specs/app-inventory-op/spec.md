## MODIFIED Requirements

### Requirement: 列出已安装 App 及元数据

`ios_toolkit.toolkit_api` SHALL 提供 `list_apps(target)`，通过 `pymobiledevice3` 的 `InstallationProxyService.get_apps()` 返回设备上已安装 App 列表，每项至少包含 `bundleId`、`name`、`appType`，以及 `fileSharing`（是否开启 `UIFileSharingEnabled`）与 `sandboxAccessible`（沙盒容器是否可经 house-arrest `VendContainer` 访问）两个布尔标志。

`sandboxAccessible` 判定 SHALL 以 `Entitlements` 中的 **`get-task-allow`** 为真为准（即该 App 可调试，其容器方可被 house-arrest vend）；MAY 兼容带 `com.apple.security.` 前缀的等价键作为次要回退。判定 MUST NOT 以「存在 `SignerIdentity`」作为依据——App Store 应用同样带 `SignerIdentity`（`Apple iPhone OS Application Signing`）却不可访问容器，会造成误判。

#### Scenario: 成功返回 App 列表

- **WHEN** 调用 `list_apps(target)` 且设备在线
- **THEN** 返回 `ok` 包络，`data.apps` 为 App 列表
- **AND** 每个 App 含 `bundleId`、`name`、`appType`、`fileSharing`、`sandboxAccessible` 字段

#### Scenario: 设备不存在或不可达

- **WHEN** 以未知 / 离线 `target` 调用 `list_apps`
- **THEN** 返回 `error` 包络，`error.kind` 标识失败原因（如 `BAD_TARGET` 或 `SUBPROCESS`）

#### Scenario: 标记文件共享与沙盒可访问

- **WHEN** 某 App 的 `UIFileSharingEnabled` 为真
- **THEN** 其 `fileSharing` 为 `true`
- **AND** 当其 `Entitlements` 含 `get-task-allow=true` 时 `sandboxAccessible` 为 `true`，否则为 `false`

#### Scenario: App Store 应用不误判为可访问

- **WHEN** 某 App 为 App Store 签名（带 `SignerIdentity` 但 `Entitlements` 不含 `get-task-allow=true`）
- **THEN** 其 `sandboxAccessible` 为 `false`
