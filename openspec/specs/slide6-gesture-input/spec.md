## Purpose

定义桌面端手势输入行为：将本地鼠标轨迹映射为设备逻辑坐标并区分点击/滑动/长按等动作，同时确保与键盘捕获、镜像刷新与焦点管理协同，不引入交互抢占。

## Requirements

### Requirement: 鼠标坐标到设备逻辑坐标的映射

应用 SHALL 把画面控件上的鼠标位置归一化到 `[0,1]`，再乘以 `window_size` 的逻辑宽高，得到设备坐标，且映射不受 Retina/高 DPI 像素影响。

#### Scenario: 归一化映射

- **WHEN** 用户在画面区域按下/抬起鼠标
- **THEN** 鼠标坐标按显示区域归一化后乘以设备逻辑尺寸得到设备坐标
- **AND** 坐标被钳制在画面范围内

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

### Requirement: 手势不打断键盘捕获

当键盘镜像开启时，应用 SHALL 在手势操作后将输入焦点保持在键盘捕获控件上。

#### Scenario: 点按后保持键盘焦点

- **WHEN** 键盘镜像处于开启状态且用户在画面上完成一次手势
- **THEN** 手势完成后输入焦点仍回到键盘捕获控件
