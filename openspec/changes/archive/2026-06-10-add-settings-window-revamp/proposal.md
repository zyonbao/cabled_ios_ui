## Why

当前 Settings 是一个平铺的单页 Preferences 对话框，随着配置项增多（日志、即将到来的 DDI 镜像来源/优先级/GitHub token 等）已不够清晰。需要把 Settings 重构为分组的标签页窗口，并提前把 DDI 镜像来源相关的配置项落地，为后续 `add-local-ddi-mount`（本地/GitHub 多来源挂载）提供配置载体。

## What Changes

- **Settings 窗口改为 3 个水平切换的标签页**：`General` / `Logging` / `DeveloperDiskImage`。
- **General 标签**：暂仅保留「Ask to clean XPC tunnel on exit」开关（沿用现有键与行为）。
- **Logging 标签**：保留启用开关 + 目录输入框；目录为空时输入框占位文案改为直接展示默认路径「默认:~/Library/CablediOS/Logs」，替换现有的"留空使用默认…"提示。
- **DeveloperDiskImage 标签**：新增镜像来源配置，分三个 section：
  - **System Developer Image**：一个启用开关（关闭时本 section 内选项全部 disable）；legacy developer image 目录（iOS<17，默认 Xcode `DeviceSupport` 目录）；modern developer image 目录（iOS17+，默认 `/Library/Developer/CoreDevice/CandidateDDIs`）。
  - **GitHub Download Image**：一个启用开关；GitHub Token 输入（含说明：默认从 doronz88 仓库下载，无 token 60 次/小时，配置 token 后 5000 次/小时）；GitHub 镜像保存目录。
  - **来源优先级**：配置 System Developer Image 与 GitHub Download Image 的优先顺序；当任一 section 被禁用时，其在优先级配置中的对应项 disable。
- 所有新配置项经 `QSettings` 持久化；本变更只负责**配置面与持久化**，实际挂载消费这些配置由 `add-local-ddi-mount` 承接。

## Capabilities

### New Capabilities
- `slide6-settings-window`: 分组标签页式 Settings 窗口的整体结构与 General 标签内容。
- `slide6-ddi-mount-settings`: DeveloperDiskImage 标签的镜像来源配置（三个 section + 优先级 + 持久化键）。

### Modified Capabilities
- `slide6-logging-settings`: 日志配置移入 Logging 标签；目录为空时占位文案改为直接展示默认路径。

## Impact

- 代码：`slide6_ui/main_window.py`（`_open_preferences` 重构为 `QTabWidget` 三标签；新增 DDI 相关 `QSettings` 键常量与读写辅助）；可能抽出 `slide6_ui/common/file_dialogs.open_directory` 复用（已存在）。
- 持久化：新增 `QSettings` 键（DDI 来源开关 / legacy 目录 / modern 目录 / GitHub 开关 / GitHub token / GitHub 保存目录 / 来源优先级）。沿用既有键 `settings/ask_clean_tunnel_on_exit`、`settings/logging_enabled`、`settings/logging_dir`。
- 安全：GitHub token 属敏感凭据，MUST 仅存于本地 `QSettings`，MUST NOT 写入日志（安全基线第 4 条）。
- 范围边界：本变更不改变挂载逻辑；DDI 配置项的实际消费在 `add-local-ddi-mount` 中实现。
