## ADDED Requirements

### Requirement: 鼠标坐标到设备逻辑坐标的映射

应用 SHALL 把画面控件上的鼠标位置归一化到 `[0,1]`，再乘以 `window_size` 的逻辑宽高，得到设备坐标，且映射不受 Retina/高 DPI 像素影响。

#### Scenario: 归一化映射

- **WHEN** 用户在画面区域按下/抬起鼠标
- **THEN** 鼠标坐标按显示区域归一化后乘以设备逻辑尺寸得到设备坐标
- **AND** 坐标被钳制在画面范围内

### Requirement: 点按与滑动的区分

应用 SHALL 依据按下到抬起的位移阈值（约 8 像素）区分点按与滑动：低于阈值为点按调用 `toolkit_api.tap`，否则为滑动调用 `toolkit_api.swipe`。

#### Scenario: 点按

- **WHEN** 用户按下后在阈值内抬起
- **THEN** 调用 `tap(target, x, y)`，坐标为按下点映射结果

#### Scenario: 滑动

- **WHEN** 用户按下后移动超过阈值再抬起
- **THEN** 调用 `swipe(target, x1, y1, x2, y2, durationMs)`
- **AND** `durationMs` 由按住时长映射并夹在 120~1500ms 之间

### Requirement: 手势不打断键盘捕获

当键盘镜像开启时，应用 SHALL 在手势操作后将输入焦点保持在键盘捕获控件上。

#### Scenario: 点按后保持键盘焦点

- **WHEN** 键盘镜像处于开启状态且用户在画面上完成一次手势
- **THEN** 手势完成后输入焦点仍回到键盘捕获控件
