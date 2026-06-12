# mobile-config-op Specification

## Purpose
定义描述文件（mobileconfig）工具层能力：列出已安装描述文件、安装新描述文件、删除指定描述文件，并提供一致的错误包络与状态返回。
## Requirements
### Requirement: 列出配置描述文件

平台能力层 SHALL 提供 `list_profiles(target)`，返回设备上已安装的配置描述文件清单，使用统一 `{ok, data}` 信封。该操作 MUST 基于 lockdown `MobileConfigService`，且 MUST NOT 依赖 WDA 或 XPC tunnel。

成功时 `data` MUST 形如 `{"profiles": [{"identifier", "name", "type", "organization", "payloadCount"}, ...]}`；当某字段在设备返回中缺失时，该字段 SHALL 以空字符串或 0 兜底，而不是整体失败。

#### Scenario: 设备存在描述文件

- **WHEN** 调用 `list_profiles(target)` 且目标设备在线
- **THEN** 返回 `ok=True`，且 `data.profiles` 为数组，每项至少包含 `identifier` 与 `name`

#### Scenario: 设备无描述文件

- **WHEN** 调用 `list_profiles(target)` 且设备未安装任何描述文件
- **THEN** 返回 `ok=True` 且 `data.profiles` 为空数组

#### Scenario: 目标不存在

- **WHEN** 以未知 `target` 调用 `list_profiles`
- **THEN** 返回 `ok=False`，`error.kind` 为 `BAD_TARGET`

### Requirement: 安装配置描述文件

平台能力层 SHALL 提供 `install_profile(target, path)`，将本地 `.mobileconfig` 文件下发到设备。该操作 MUST 读取文件字节并调用 `MobileConfigService.install_profile`。由于系统行为，安装通常需用户在设备「设置」中手动确认，因此返回成功 MUST 表示「已成功下发」而非「已完成安装」。

调用前 MUST 校验 `path` 指向存在的 `.mobileconfig` 文件，否则返回 `BAD_TARGET`。

#### Scenario: 下发合法描述文件

- **WHEN** 以指向有效 `.mobileconfig` 的 `path` 调用 `install_profile`
- **THEN** 服务接受请求并返回 `ok=True`，`data` 标识已下发

#### Scenario: 文件不存在或扩展名不符

- **WHEN** `path` 不存在或不以 `.mobileconfig` 结尾
- **THEN** 返回 `ok=False`，`error.kind` 为 `BAD_TARGET`，且不发起设备请求

### Requirement: 移除配置描述文件

平台能力层 SHALL 提供 `remove_profile(target, identifier)`，按标识符移除设备上的描述文件，调用 `MobileConfigService.remove_profile`。`identifier` 为空时 MUST 返回 `BAD_TARGET`。当设备因受监管 / MDM 策略拒绝移除时，MUST 以 `{ok: False}` 信封回显底层错误，而非抛出未捕获异常。

#### Scenario: 移除可移除的描述文件

- **WHEN** 以有效 `identifier` 调用 `remove_profile`
- **THEN** 返回 `ok=True`，`data` 标识已移除

#### Scenario: 受限描述文件被拒绝移除

- **WHEN** 目标描述文件受监管 / MDM 限制无法移除
- **THEN** 返回 `ok=False`，`error.message` 包含底层拒绝原因

