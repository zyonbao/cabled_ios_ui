# slide6-app-lifecycle (delta)

## ADDED Requirements

### Requirement: 退出不被后台设备操作阻塞

桌面应用退出 SHALL 立即完成，不得因仍在运行的后台设备操作而挂起。后台阻塞型设备调用（如 WDA `prepare`、`clear_location` 等）经全局 `QThreadPool` 派发，而 Qt 正常退出会以 `QThreadPool::waitForDone()`（无超时）等待全部在途任务，可使退出挂起数十秒。应用 SHALL 在 `closeEvent` 中先落盘所有持久化状态（如 `QSettings.sync()`），随后在 `app.exec()` 返回后以 `os._exit()` 直接退出，跳过对全局线程池的等待；在途的 best-effort 设备操作随进程结束被丢弃（设备侧在连接断开后自行恢复）。

此外，对话框关闭 / 路径切换时的后台资源释放（如性能采样数据流的 `close()`，其内部可能阻塞数秒）SHALL NOT 在 UI 线程同步执行，应交由后台（线程池或 daemon 线程）执行，以免冻结界面。

#### Scenario: 后台设备操作进行中退出

- **WHEN** 存在仍在运行的后台设备操作（如 WDA prepare）时，用户退出应用
- **THEN** 应用立即退出，不等待这些操作完成，进程不挂起数十秒

#### Scenario: 退出前持久化状态已落盘

- **WHEN** 用户更改设置后退出应用（退出走 `os._exit`，跳过 QSettings 析构同步）
- **THEN** 下次启动时更改后的设置仍然生效

#### Scenario: 关闭性能监控对话框不冻结界面

- **WHEN** 用户关闭正在运行的性能监控对话框（其数据流 `close()` 内部可能阻塞数秒）
- **THEN** 对话框立即关闭，UI 不冻结
