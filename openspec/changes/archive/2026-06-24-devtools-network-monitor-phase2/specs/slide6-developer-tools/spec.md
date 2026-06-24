## MODIFIED Requirements

### Requirement: 网络监控界面

「开发者工具」Tab 中的网络监控 SHALL 以子面板方式呈现（非独立 sidebar Tab），并提供顶部状态条、三栏布局与高频控制栏。过滤器 MUST 支持按协议（TCP/UDP/unknown）、host/port（`IP:port` 子串）、关键词与「仅活跃连接」筛选；方向（in/out）过滤 MAY 提供，基于推导值。进程归属不可用（`pid=-2`），左栏改为按「远端 IP/接口」聚合，不提供进程列表/进程过滤。网络采集为事件推送式（无设备侧采样间隔），UI 渲染采用限速批量刷新。

#### Scenario: 在开发者工具内进入网络监控子面板

- **WHEN** 用户点击网络监控功能卡片
- **THEN** 进入同一 Tab 下的 Network Monitor 子面板
- **AND** 子面板展示状态条、控制栏和三栏主布局
