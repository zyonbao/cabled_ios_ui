## Purpose

设备发现能力——枚举 USB 连接的物理 iOS 设备及其元数据，`list_targets` 不触发端口转发。
## Requirements
### Requirement: 枚举 USB 连接的物理 iOS 设备
系统 SHALL 通过 `pymobiledevice3` 的 `usbmux.list_devices()` 获取当前已连接的 iOS 设备列表，并仅保留 `connection_type == "USB"` 的条目，过滤所有 Wi-Fi 配对设备。

#### Scenario: 有 USB 设备连接时返回设备列表
- **WHEN** 调用 `list_targets()`，且有一台或多台 USB 物理 iOS 设备已连接
- **THEN** 返回 `{"ok": true, "data": {"targets": [...]}}` 其中每个 target 包含 `id`（UDID）、`platform`（固定为 `"ios"`）、`name`、`state`（固定为 `"online"`）、`metadata.model`、`metadata.os_version`

#### Scenario: 无设备连接时返回空列表
- **WHEN** 调用 `list_targets()`，且没有任何 USB 物理 iOS 设备连接
- **THEN** 返回 `{"ok": true, "data": {"targets": []}}` 且不报错

#### Scenario: Wi-Fi 配对设备不出现在结果中
- **WHEN** 调用 `list_targets()`，且只有 Wi-Fi 配对设备（`connection_type != "USB"`）可见
- **THEN** 返回 `{"ok": true, "data": {"targets": []}}` 不包含任何 Wi-Fi 设备

### Requirement: 读取设备元数据并降级处理失败
系统 SHALL 通过 lockdown 读取每台 USB 设备的 `DeviceName`、`ProductType`、`ProductVersion`，读取失败时降级为空字符串，不阻塞其他设备的处理。

#### Scenario: 元数据读取成功
- **WHEN** `list_targets()` 发现一台 USB 设备且 lockdown 可访问
- **THEN** target 的 `name`、`metadata.model`、`metadata.os_version` 填入实际值

#### Scenario: 元数据读取失败时降级为空字符串
- **WHEN** `list_targets()` 发现一台 USB 设备但 lockdown 连接失败
- **THEN** target 的 `name`、`metadata.model`、`metadata.os_version` 均为空字符串，该设备仍出现在结果中

### Requirement: list_targets 不启动端口转发
系统 SHALL 在 `list_targets()` 的实现中仅做设备发现和元数据读取，不启动任何 usbmux 端口转发，整体耗时目标 < 1 秒。

#### Scenario: list_targets 不依赖 WDA
- **WHEN** 调用 `list_targets()`，且设备上 WDA 未运行
- **THEN** 仍然正常返回设备信息，不因 WDA 不可用而报错

### Requirement: 未配对设备跳过 WDA 安装探测

`list_targets()` 在判定每台设备的 `state`（`"online"` 表示 WDA 已安装、否则 `"offline"`）时，SHALL 先检查该设备是否已配对：仅当**已配对**时才打开 InstallationProxy 会话探测 WDA 是否安装；**未配对**设备 MUST 跳过 WDA 探测并直接置为 `"offline"`，以避免对依赖配对的服务发起请求而抛出 `NotPairedError`。任一设备的探测异常 MUST 被吞掉并降级为 `"offline"`，不影响其它设备。

#### Scenario: 未配对设备不触发 WDA 探测

- **WHEN** `list_targets()` 发现一台未配对设备
- **THEN** 该设备 `state` 为 `"offline"`，且枚举过程不因其产生 `NotPairedError`

#### Scenario: 已配对设备正常探测 WDA

- **WHEN** `list_targets()` 发现一台已配对设备且 WDA 已安装
- **THEN** 该设备 `state` 为 `"online"`

#### Scenario: 探测异常降级

- **WHEN** 某台设备的配对检查或 WDA 探测抛出异常
- **THEN** 该设备 `state` 降级为 `"offline"` 并仍出现在结果中，不影响其它设备

