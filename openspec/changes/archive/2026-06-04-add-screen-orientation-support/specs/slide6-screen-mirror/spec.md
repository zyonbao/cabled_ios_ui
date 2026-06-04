## ADDED Requirements

### Requirement: 按屏幕方向渲染画面与坐标映射

`slide6_console` 的画面控件 SHALL 在准备设备后取得 `toolkit_api.orientation(target)`，并据此渲染 MJPEG 画面：当帧方向与 `window_size`（当前方向）不一致时按 `degrees` 把帧旋转 90°/270° 使其与当前方向对齐；当帧方向已一致但朝向为 `PORTRAIT_UPSIDE_DOWN` 时额外旋转 180°（仅凭宽高比无法识别 180° 翻转）。旋转后再 letterbox 居中绘制，使画面朝向与设备一致、宽高比正确，且手势坐标映射到 `window_size`（当前方向）空间在四方向下都正确。

#### Scenario: 竖屏渲染

- **WHEN** 设备为竖屏
- **THEN** 画面不旋转，按竖屏宽高比 letterbox 显示
- **AND** 点按/滑动映射到设备坐标正确

#### Scenario: 横屏渲染与点击

- **WHEN** 设备为横屏（左或右）
- **THEN** 画面以横屏宽高比正立显示且不变形
- **AND** 用户点击画面某处时映射出的设备坐标对应该可视位置

#### Scenario: 倒置竖屏渲染

- **WHEN** 设备为倒置竖屏（`PORTRAIT_UPSIDE_DOWN`）
- **THEN** 画面额外旋转 180° 正立显示，而非保持倒置

#### Scenario: 方向获取失败回退

- **WHEN** `orientation` 查询失败或返回未知方向
- **THEN** 按竖屏（不旋转）渲染，且不崩溃
