## Context

现有实现已经把 WDA 关键配置放进了 Settings，但底部手势仍然只覆盖一个 `App Switcher` 能力，模型过窄，无法同时承载：

- `swipe up hold`
- `swipe up`
- 默认规则
- 按 `device id` 的覆盖规则
- 主界面按钮名称

这次把它统一提升为 `Bottom Gestures / 底部手势`。

## Decisions

### 1. Settings 中使用统一表格模型

`Key/Mouse` tab 分两块：

1. `WDA`
   - `WDA bundle id`
   - `WDA server port`
   - `WDA MJPEG port`
2. `Bottom Gestures`
   - 一段说明文案
   - 一张三列表格

表格列：

1. `Device`
2. `Swipe Up Hold`
3. `Bottom Swipe Up`

### 2. 默认行与设备行

表格第一行固定为 `Default / 默认`。后续行为按 `device id` 的覆盖行。

- 默认行不可删除
- 设备行支持 `add / edit / delete`
- 两个动作列都通过下拉框选择

### 3. 持久化模型

新增 QSettings 键：

| Key | Type | Default |
| --- | --- | --- |
| `settings/keymouse_wda_bundle_id` | string | `com.facebook.WebDriverAgentRunner.xctrunner` |
| `settings/keymouse_wda_port` | int | `8100` |
| `settings/keymouse_wda_mjpeg_port` | int | `9100` |
| `settings/keymouse_bottom_edge_gestures` | JSON string | see below |

`settings/keymouse_bottom_edge_gestures` 存储 JSON 数组，每项包含：

- `deviceId`
- `swipeUpHold`
- `swipeUp`

默认数组首项为：

```json
{
  "deviceId": "default",
  "swipeUpHold": "app_switcher",
  "swipeUp": "bottom_swipe_up"
}
```

### 4. 允许值

`swipeUpHold`：

- `disabled`
- `app_switcher`

`swipeUp`：

- `disabled`
- `bottom_swipe_up`
- `control_center`

### 5. 主界面按钮生成规则

主界面不再写死 `App Switcher` 按钮，而是按当前设备解析命中的底部手势行：

1. 先精确匹配 `device id`
2. 未命中则回退默认行
3. `disabled` 的项不显示按钮
4. 启用的项按配置名称显示按钮

按钮位置：

- 在 `HOME` 下方
- 在 `Keyboard input` 上方

### 6. 底层动作映射

`app_switcher`：

- 调用现有 `toolkit_api.app_switcher(target)`
- 底层动作固定为 `swipe_up_hold`

`bottom_swipe_up` / `control_center`：

- 调用新增 `toolkit_api.bottom_edge_swipe(target)`
- 底层动作固定为普通 `swipe_up`

这里 `control_center` 本次只代表另一种按钮名称，不引入独立的底层逻辑分叉。

### 7. WDA 配置桥接

`ios_toolkit` 继续通过环境变量读取桌面 UI 的 WDA 配置：

- `IOS_WDA_BUNDLE_ID`
- `IOS_WDA_PORT`
- `IOS_WDA_MJPEG_PORT`

`iOSDevicesManager` 继续通过配置签名刷新设备条目，使后续发现与连接立即使用新值。

## Non-Goals

- 不新增默认分辨率设置。
- 不恢复 `double_home`。
- 不让 `control_center` 引入独立底层手势逻辑。
