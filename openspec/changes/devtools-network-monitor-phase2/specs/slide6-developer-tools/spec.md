## MODIFIED Requirements

### Requirement: 网络监控界面

「开发者工具」Tab 中的网络监控 SHALL 以子面板方式呈现（非独立 sidebar Tab），并提供顶部状态条、三栏布局与高频控制栏。过滤器 MUST 支持按进程、协议、方向、host/port、关键词与活跃连接状态筛选。

#### Scenario: 在开发者工具内进入网络监控子面板

- **WHEN** 用户点击网络监控功能卡片
- **THEN** 进入同一 Tab 下的 Network Monitor 子面板
- **AND** 子面板展示状态条、控制栏和三栏主布局
