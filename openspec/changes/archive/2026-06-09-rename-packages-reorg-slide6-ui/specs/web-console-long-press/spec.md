## MODIFIED Requirements

### Requirement: 后端 long_press 端点

`web_page` 后端 SHALL 提供 `POST /api/long_press` 端点，请求体为 `{target, x, y, durationMs}`（`durationMs` 可选，默认 800），调用 `toolkit_api.long_press` 并透传成功数据或将错误信封转换为对应 HTTP 状态码（`BAD_TARGET` → 404，其它 → 503）。

#### Scenario: 转发长按

- **WHEN** 浏览器 `POST /api/long_press` 携带有效 `target`/`x`/`y`
- **THEN** 后端调用 `toolkit_api.long_press(target, x, y, durationMs)` 并返回其 `data`

#### Scenario: 设备不存在

- **WHEN** `POST /api/long_press` 的 `target` 不存在
- **THEN** 返回 HTTP 404

### Requirement: 前端原地长按手势识别

`web_page` 前端 SHALL 在画面触控区把"原地按住"识别为长按：在 `pointerup` 时，若按下到抬起的位移小于点按阈值（约 8px）且按住时长达到长按阈值（约 600ms，高于 iOS 系统约 0.5s 的长按阈值），则调用 `POST /api/long_press`，坐标为按下点映射到 `window_size` 的结果，`durationMs` 取实测按住时长并钳制到合理上限（≤ 3000ms）。长按与点按、滑动三者互斥。

#### Scenario: 原地长按触发长按

- **WHEN** 用户在画面某点按下，几乎不移动并按住超过长按阈值后抬起
- **THEN** 调用 `/api/long_press`，坐标为按下点映射结果，`durationMs` 为实测按住时长（钳制后）

#### Scenario: 短按仍为点按

- **WHEN** 用户原地按下并很快（短于长按阈值）抬起
- **THEN** 调用 `/api/tap` 而非 `/api/long_press`

#### Scenario: 有位移时仍为滑动

- **WHEN** 用户按下后移动超过点按阈值再抬起（无论按住多久）
- **THEN** 调用 `/api/swipe` 而非 `/api/long_press`

#### Scenario: 长按不打断键盘捕获

- **WHEN** 键盘镜像处于开启状态且用户完成一次长按
- **THEN** 长按完成后输入焦点仍回到键盘捕获控件
