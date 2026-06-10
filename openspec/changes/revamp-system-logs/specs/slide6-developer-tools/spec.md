## ADDED Requirements

### Requirement: 系统日志区块入口

「开发者工具」Tab SHALL 容纳一个独立的系统日志区块（作为可扩展 Grid 的一部分），按当前设备主版本暴露对应入口：iOS 17+ 暴露 `oslog`，iOS 17 以下暴露 `syslog`。该区块 MUST 随主窗口的设备切换刷新；未选中设备时 MUST NOT 启动任何日志流。系统日志 MUST NOT 再以独立 sidebar tab 形式存在。日志流的具体采集与渲染行为遵循 `slide6-syslog-stream` 能力。

#### Scenario: 从开发者工具进入日志区块

- **WHEN** 选中设备并进入「开发者工具」Tab 的系统日志区块
- **THEN** 依设备版本显示 oslog（17+）或 syslog（17-）入口，可开始 / 停止实时日志

#### Scenario: 设备切换刷新日志区块

- **WHEN** 用户切换所选设备
- **THEN** 日志区块停止旧设备的流并按新设备版本切换入口
