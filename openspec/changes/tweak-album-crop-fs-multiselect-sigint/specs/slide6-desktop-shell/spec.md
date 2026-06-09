## ADDED Requirements

### Requirement: 侧边 Tab 顺序

应用 SHALL 以固定顺序在左侧 Tab 栏排列功能页：**设备信息 / 相册 / 文件系统 / App 列表 / 键鼠操作**。需要 WDA / 镜像启动成本的「键鼠操作」SHALL 置于末位，信息类「设备信息」SHALL 置于首位。

#### Scenario: Tab 顺序

- **WHEN** 应用启动
- **THEN** 左侧 Tab 依次为 设备信息、相册、文件系统、App 列表、键鼠操作

### Requirement: 设备切换保留当前 Tab

应用启动时 SHALL 默认选中「设备信息」Tab（即首位 Tab）。当用户切换所选设备时，应用 SHALL **保留**用户当前所在的 Tab，而非每次都重置/跳回「设备信息」。

#### Scenario: 启动默认 Tab

- **WHEN** 应用启动
- **THEN** 当前选中的 Tab 为「设备信息」

#### Scenario: 切换设备保留 Tab

- **WHEN** 用户当前停留在「相册/文件系统/App 列表/键鼠操作」中的某个 Tab，并切换所选设备
- **THEN** 仍停留在原 Tab，不被重置回「设备信息」
