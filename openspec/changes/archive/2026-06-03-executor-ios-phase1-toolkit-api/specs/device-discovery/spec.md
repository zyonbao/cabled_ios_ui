## ADDED Requirements

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
