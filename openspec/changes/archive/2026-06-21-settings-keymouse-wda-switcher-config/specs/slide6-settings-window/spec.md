## ADDED Requirements

### Requirement: Settings 窗口包含 Key/Mouse 标签

桌面应用的 Settings 窗口 SHALL 提供 3 个水平标签页：`General`、`DeveloperDiskImage`、`Key/Mouse`。窗口高度 SHALL 继续按最高标签页自适应，切换到 `Key/Mouse` 时表格与设置行不得被压缩。

#### Scenario: 打开 Settings 可见 Key/Mouse

- **WHEN** 用户打开 Settings
- **THEN** 顶部展示 `General` / `DeveloperDiskImage` / `Key/Mouse` 三个标签

### Requirement: Key/Mouse 标签提供 WDA 配置

`Key/Mouse` 标签 SHALL 提供以下持久化配置，并在变更时即时写回：

- `settings/keymouse_wda_bundle_id`
- `settings/keymouse_wda_port`
- `settings/keymouse_wda_mjpeg_port`

默认值分别为 `com.facebook.WebDriverAgentRunner.xctrunner`、`8100` 与 `9100`。这些配置 SHALL 通过运行时桥接影响后续设备发现与 WDA 启动。

#### Scenario: 修改 WDA 配置

- **WHEN** 用户修改 WDA bundle id / server port / MJPEG port
- **THEN** 对应值写回各自的持久化键

### Requirement: Key/Mouse 标签提供底部手势表格

`Key/Mouse` 标签 SHALL 提供 `Bottom Gestures / 底部手势` 区域，包含一段说明文案和一张三列表格。

表格列为：

- `Device`
- `Swipe Up Hold`
- `Bottom Swipe Up`

#### Scenario: 打开底部手势设置

- **WHEN** 用户打开 `Key/Mouse` 标签中的 `Bottom Gestures / 底部手势`
- **THEN** 界面显示一张三列表格

### Requirement: 底部手势表格包含默认行和设备行

底部手势表格 SHALL 包含一条固定默认行，以及零条或多条按 `device id` 的设备行。其持久化键为 `settings/keymouse_bottom_edge_gestures`。

每行包含：

- `deviceId`
- `swipeUpHold`
- `swipeUp`

默认行的 `deviceId` MUST 为 `default`。

#### Scenario: 查看默认行

- **WHEN** 用户打开表格
- **THEN** 第一行显示 `Default / 默认`

#### Scenario: 新增设备行

- **WHEN** 用户新增一条设备行
- **THEN** 该行写入 `settings/keymouse_bottom_edge_gestures`

#### Scenario: 删除设备行

- **WHEN** 用户删除一条设备行
- **THEN** 对应项从 `settings/keymouse_bottom_edge_gestures` 中移除

### Requirement: 底部手势动作列使用下拉框

底部手势表格的动作列 SHALL 使用下拉框。

`Swipe Up Hold` 列允许值仅为：

- `disabled`
- `app_switcher`

`Bottom Swipe Up` 列允许值仅为：

- `disabled`
- `bottom_swipe_up`
- `control_center`

默认行的默认值 SHALL 为：

- `swipeUpHold = app_switcher`
- `swipeUp = bottom_swipe_up`

#### Scenario: 修改动作列

- **WHEN** 用户修改任一行的 `Swipe Up Hold` 或 `Bottom Swipe Up` 下拉值
- **THEN** 新值写回 `settings/keymouse_bottom_edge_gestures`
