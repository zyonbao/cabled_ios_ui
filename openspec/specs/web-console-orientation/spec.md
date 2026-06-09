## Purpose

Web 控制台屏幕方向能力——暴露方向查询端点，按方向渲染视频流并在横竖屏下正确做坐标映射。

## Requirements

### Requirement: 暴露屏幕方向查询端点

`web_console` SHALL 提供 `GET /api/orientation?target=<udid>` 端点，内部调用 `toolkit_api.orientation(target)` 并把统一信封透传给前端。

#### Scenario: 取得方向

- **WHEN** 前端在设备准备完成后请求 `/api/orientation?target=<udid>`
- **THEN** 返回包含 `orientation` 与 `degrees` 的 JSON
- **AND** 调用失败时返回带错误详情的非 2xx 响应

### Requirement: 按屏幕方向渲染视频流

`web_console` 前端 SHALL 在准备设备后获取方向，并按方向渲染 MJPEG 画面：当帧方向与 `window_size`（当前方向）不一致时旋转 90°/270° 对齐，倒置竖屏额外旋转 180°；容器宽高比与 `window_size`（当前方向）一致，且画面以 `object-fit: contain` 显示避免拉伸/挤压。

#### Scenario: 竖屏渲染

- **WHEN** 设备为竖屏
- **THEN** 画面以竖屏宽高比正常显示，不做旋转

#### Scenario: 横屏渲染

- **WHEN** 设备为横屏
- **THEN** 画面按 `orientation` 指示方向旋转对齐，以横屏宽高比显示且不变形

### Requirement: 横竖屏下的坐标映射正确

`web_console` SHALL 保证点按/滑动的指针坐标映射到 `window_size`（当前方向）坐标空间，使横屏与竖屏下点击位置都与设备实际位置一致。

#### Scenario: 横屏点击映射

- **WHEN** 设备横屏且用户在画面某处点击
- **THEN** 映射出的设备坐标对应该可视位置，点击命中预期目标

### Requirement: 选中设备后提供刷新动作

`web_console` SHALL 在选中设备后提供一个"刷新"按钮，点击后执行与重新选中当前设备**完全一致**的逻辑（重新 `prepare` → 取 `window_size` 与 `orientation` → 重连视频流），用于设备旋转后手动重新同步。该按钮区别于顶部"刷新设备列表"。

#### Scenario: 点击刷新重新同步

- **WHEN** 已连接状态下用户点击该刷新按钮
- **THEN** 触发与重新选中当前设备一致的流程，重新获取方向与尺寸并重连画面

#### Scenario: 未选中设备时不可用

- **WHEN** 尚未选中有效设备
- **THEN** 该刷新按钮不可用或点击无效果
