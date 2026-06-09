## ADDED Requirements

### Requirement: 导出配置描述文件

平台能力层 SHALL 提供 `export_profile(target, identifier, local_path)`，将设备上指定标识符的配置描述文件原始内容导出到本地文件，使用统一 `{ok, data}` 信封。该操作 MUST 基于 lockdown `MobileConfigService`，且 MUST NOT 依赖 WDA 或 XPC tunnel。

实现 SHALL 复用 `MobileConfigService.get_profile_list()` 返回中的 `ProfileManifest`，按 `identifier` 取出其原始字节（`Data`）并写入 `local_path`；字节 MUST 原样落地（签名描述文件即为其 CMS 签名包，不做解签 / 改写）。`identifier` 为空时 MUST 返回 `BAD_TARGET`；当返回中不含该标识符或缺少 `ProfileManifest` 时 MUST 以 `{ok: False}` 信封回显可读错误，而非抛出未捕获异常。

#### Scenario: 导出已安装描述文件

- **WHEN** 以有效 `identifier` 与可写 `local_path` 调用 `export_profile`
- **THEN** 返回 `ok=True`，`data` 标识已导出路径，且 `local_path` 为该描述文件的原始字节

#### Scenario: 标识符不存在

- **WHEN** 以设备上不存在的 `identifier` 调用 `export_profile`
- **THEN** 返回 `ok=False`，`error` 说明未找到该描述文件

#### Scenario: 标识符为空

- **WHEN** 以空 `identifier` 调用 `export_profile`
- **THEN** 返回 `ok=False`，`error.kind` 为 `BAD_TARGET`，且不发起设备请求
