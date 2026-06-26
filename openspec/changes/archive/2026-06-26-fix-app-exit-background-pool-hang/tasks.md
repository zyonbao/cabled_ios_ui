# Tasks

## 1. 退出不死等线程池（slide6-app-lifecycle）

- [x] 1.1 `app.py`：`app.exec()` 返回（且 `logsys.shutdown_logging()` 后）改用 `os._exit(exit_code)` 退出，跳过全局 `QThreadPool.waitForDone()`
- [x] 1.2 `main_window.closeEvent`：在 `event.accept()` 前调用 `self.settings.sync()`，确保 os._exit 前设置落盘

## 2. 后台释放不阻塞 UI（slide6-app-lifecycle）

- [x] 2.1 `common/workers.py`：新增 `fire_and_forget(fn)` —— 在 daemon 线程跑 best-effort 调用（daemon 线程不被 Qt 退出等待）
- [x] 2.2 `performance_dialog._stop`：数据流 `close()`（原 UI 线程同步、内部 `wait(3s)`）改为 `fire_and_forget`

## 3. 验证

- [x] 3.1 诊断日志定位：退出时 `pool active threads=5`，多个 `api,prepare` 在途未完成 → 坐实根因
- [x] 3.2 真机：选设备 → 开发者选项 → 键鼠 → 回开发者选项 → 退出 → 秒退（已通过）
- [x] 3.3 真机：更改设置后退出、重启仍生效；性能监控对话框关闭不冻结
- [x] 3.4 移除临时诊断日志；回退探索期的冗余加固（仅保留本变更四处改动）
- [x] 3.5 `openspec validate fix-app-exit-background-pool-hang --strict`
