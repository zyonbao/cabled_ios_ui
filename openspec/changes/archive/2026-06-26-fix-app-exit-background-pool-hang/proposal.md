# Why

退出应用时会卡住几十秒才真正退出。复现：选设备 → 开发者选项 → 键鼠操作 → 回开发者
选项 → 退出。

日志实证根因：退出时全局 `QThreadPool` 仍有在途任务（`activeThreadCount=5`），其中多个是
**WDA `prepare`(启动 WDA)** 操作——单次耗时长、无法取消，dev↔键鼠 反复切换会堆积一批。
Qt 正常退出会调用 `QThreadPool::waitForDone()`（无超时）**死等**这些在途任务，于是退出被
拖到最慢的那个完成(~30s)。这是通用问题：退出时任何在途阻塞设备操作都会触发，单点改造
（针对某个具体调用）无法根治。

附带发现：性能监控对话框 `_stop()` 在 **UI 线程同步**调用数据流 `close()`（内部
`wait(timeout=3.0)`），关闭对话框时会冻结界面数秒。

# What Changes

落在 `slide6-app-lifecycle`：

1. **退出不再死等线程池**：`app.exec()` 返回后改用 `os._exit(exit_code)` 直接退出，
   跳过 Qt/全局 `QThreadPool` 的 `waitForDone()`；在途 best-effort 设备操作随进程结束被
   丢弃（设备侧连接断开后自行恢复）。
2. **退出前落盘**：`MainWindow.closeEvent` 调用 `QSettings.sync()`，因为 `os._exit` 会
   跳过 QSettings 析构时的自动同步。
3. **后台释放不阻塞 UI**：性能监控数据流的 `close()` 改为经后台执行（新增
   `slide6_ui/common/workers.fire_and_forget` daemon 线程助手），不在 UI 线程同步等待。

# Impact

- Affected specs: `slide6-app-lifecycle`（新增「退出不被后台设备操作阻塞」要求）
- Affected code:
  - `slide6_ui/app.py`（`app.exec()` 返回后 `os._exit`）
  - `slide6_ui/main_window.py`（`closeEvent` 调 `settings.sync()`）
  - `slide6_ui/common/workers.py`（新增 `fire_and_forget` 助手）
  - `slide6_ui/developer_tools/performance_dialog.py`（`_stop` 的流 `close()` 改 `fire_and_forget`）
- 不改设备协议 / WDA。用户可见行为：退出即时；设置仍持久化；性能对话框关闭不冻结。
