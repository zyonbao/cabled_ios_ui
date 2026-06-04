## ADDED Requirements

### Requirement: 消费 WDA MJPEG broadcaster 渲染实时画面

应用 SHALL 在后台线程连接设备的 MJPEG broadcaster（`device.mjpeg_local_port`），完成握手后按 multipart 边界解析出每帧 JPEG，并在主线程渲染到画面控件。

#### Scenario: 建立流并渲染

- **WHEN** 设备准备完成进入连接状态
- **THEN** 后台线程连接 `127.0.0.1:<mjpeg_local_port>`，发送触发字节并消费 WDA 的 HTTP 头
- **AND** 持续解析 JPEG 帧并在主线程刷新画面

#### Scenario: 端口不可用

- **WHEN** 设备的 `mjpeg_local_port` 不可用
- **THEN** 显示画面流不可用的错误提示，且不崩溃

### Requirement: 解码与线程边界

应用 SHALL 在后台线程完成 JPEG 解码，仅通过信号把解码后的图像传回主线程绘制，主线程不得执行阻塞的网络或解码操作。

#### Scenario: 后台解码主线程绘制

- **WHEN** 后台线程收到一帧完整 JPEG
- **THEN** 在后台线程解码为图像并通过信号发回主线程
- **AND** 主线程仅负责把图像绘制到画面控件

### Requirement: 断流处理

当画面流中断时，应用 SHALL 停止渲染并提示用户，而不是冻结或崩溃。

#### Scenario: 流中断

- **WHEN** 已连接状态下 MJPEG 连接被关闭或读取失败
- **THEN** 显示"画面流已中断"提示，并允许用户重新选择设备重试

### Requirement: 设备切换时清理流资源

切换设备或停止镜像时，应用 SHALL 使旧的流线程失效并关闭其连接，避免过期帧污染新设备画面。

#### Scenario: 切换设备停止旧流

- **WHEN** 用户从设备 A 切换到设备 B
- **THEN** 设备 A 的流线程被标记失效并关闭连接
- **AND** 画面只显示设备 B 的帧
