## ADDED Requirements

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
