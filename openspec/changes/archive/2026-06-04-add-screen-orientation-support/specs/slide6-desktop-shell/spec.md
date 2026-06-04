## ADDED Requirements

### Requirement: 选中设备后提供刷新按钮

`slide6_console` SHALL 在选中设备后提供一个"刷新"按钮，点击后执行与重新选中当前设备**完全一致**的逻辑（停旧流 → `prepare` → 取 `window_size` 与 `orientation` → `configure_mjpeg` → 重连视频流），并沿用 generation 计数丢弃过期回调。该按钮用于设备旋转后手动重新同步，区别于"刷新设备列表"。

#### Scenario: 点击刷新重新同步当前设备

- **WHEN** 已选中并连接某设备时用户点击刷新按钮
- **THEN** 触发与重新选中该设备一致的流程，重新取得方向与尺寸并重连画面

#### Scenario: 未选中有效设备时不可用

- **WHEN** 未选中设备或选中的是未装 WDA 的设备
- **THEN** 刷新按钮不可用（或点击不进入镜像流程）

#### Scenario: 刷新期间切换设备

- **WHEN** 刷新流程仍在进行时用户切换到另一设备
- **THEN** 丢弃前一次刷新的过期回调，不污染当前设备状态与画面
