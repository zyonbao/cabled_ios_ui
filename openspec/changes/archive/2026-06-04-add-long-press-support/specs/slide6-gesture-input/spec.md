## MODIFIED Requirements

### Requirement: 点按与滑动的区分

应用 SHALL 依据按下到抬起的位移阈值（约 8 像素）与按住时长共同区分点按、长按与滑动：位移超过阈值为滑动调用 `toolkit_api.swipe`；位移在阈值内且按住时长达到长按阈值（约 600ms，高于 iOS 系统约 0.5s 的长按阈值）为长按调用 `toolkit_api.long_press`；否则为点按调用 `toolkit_api.tap`。三者互斥。

#### Scenario: 点按

- **WHEN** 用户原地按下后在位移阈值内、且短于长按阈值时抬起
- **THEN** 调用 `tap(target, x, y)`，坐标为按下点映射结果

#### Scenario: 长按

- **WHEN** 用户原地按下（位移在阈值内）并按住达到长按阈值后抬起
- **THEN** 调用 `long_press(target, x, y, durationMs)`，坐标为按下点映射结果
- **AND** `durationMs` 由按住时长映射并钳制到合理上限（≤ 3000ms）

#### Scenario: 滑动

- **WHEN** 用户按下后移动超过阈值再抬起
- **THEN** 调用 `swipe(target, x1, y1, x2, y2, durationMs)`
- **AND** `durationMs` 由按住时长映射并夹在 120~1500ms 之间
