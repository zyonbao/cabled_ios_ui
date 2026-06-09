## ADDED Requirements

### Requirement: Ctrl+C（SIGINT）干净退出

桌面应用 SHALL 处理 SIGINT（Ctrl+C），使其触发**干净退出**而非进程崩溃。应用 SHALL 安装 SIGINT 处理函数并通过周期性定时器让 Python 解释器在 Qt 事件循环运行期间得以执行该处理函数；收到 SIGINT 时 SHALL 走与窗口关闭一致的清理路径（停止屏幕镜像、停止键盘发送线程等既有 `closeEvent` 清理）后退出事件循环。

#### Scenario: 终端运行时按 Ctrl+C

- **WHEN** 应用在终端前台运行且用户按下 Ctrl+C
- **THEN** 应用执行与正常关闭一致的清理后退出，进程不崩溃

#### Scenario: 镜像进行中按 Ctrl+C

- **WHEN** 屏幕镜像或后台任务进行中收到 SIGINT
- **THEN** 先停止镜像/后台线程再退出，不在 C++ 事件循环中崩溃
