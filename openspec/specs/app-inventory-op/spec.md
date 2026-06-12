# app-inventory-op Specification

## Purpose
定义应用清单查询能力：枚举设备已安装应用并输出名称、bundle id、版本、应用类型，以及文件共享与沙盒可访问性等能力标记，供上层 UI 进行筛选和动作决策。
## Requirements
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

### Requirement: 从本地 IPA 安装 App

`ios_toolkit.toolkit_api` SHALL 提供 `install_app(target, ipa_path)`，通过 `InstallationProxyService.install_from_local()` 将本地 `.ipa` 安装到设备，并以统一包络返回结果。

#### Scenario: 安装成功

- **WHEN** 调用 `install_app(target, ipa_path)` 且 IPA 可被设备接受
- **THEN** 安装完成后返回 `ok` 包络

#### Scenario: IPA 路径无效

- **WHEN** `ipa_path` 不存在或扩展名不是 `.ipa`
- **THEN** 返回 `error` 包络，`error.kind` 为 `BAD_TARGET`，且不调用安装服务

#### Scenario: 设备拒绝安装（签名不匹配）

- **WHEN** 设备因签名/证书校验拒绝安装
- **THEN** 返回 `error` 包络，`error.message` 携带可读失败原因，不抛出未捕获异常

### Requirement: 卸载 App

`ios_toolkit.toolkit_api` SHALL 提供 `uninstall_app(target, bundle_id)`，通过 `InstallationProxyService.uninstall()` 卸载指定 App。

#### Scenario: 卸载成功

- **WHEN** 调用 `uninstall_app(target, bundle_id)` 且该 App 已安装
- **THEN** 卸载完成后返回 `ok` 包络

#### Scenario: 缺少 bundleId

- **WHEN** `bundle_id` 为空
- **THEN** 返回 `error` 包络，`error.kind` 为 `BAD_TARGET`，且不调用卸载服务

