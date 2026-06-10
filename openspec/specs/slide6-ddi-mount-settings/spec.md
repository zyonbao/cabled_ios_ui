# slide6-ddi-mount-settings Specification

## Purpose
TBD - created by archiving change add-settings-window-revamp. Update Purpose after archive.
## Requirements
### Requirement: DeveloperDiskImage 标签 — System Developer Image section

`DeveloperDiskImage` 标签 SHALL 提供「System Developer Image」section，包含一个启用开关与两个目录输入框：

- 启用开关：持久化键 `settings/ddi_local_enabled`（默认启用）。开关**关闭**时，本 section 内的目录输入框与浏览按钮 MUST 全部 disable。
- legacy developer image 目录（iOS<17 镜像列表）：持久化键 `settings/ddi_legacy_dir`；为空时输入框 MUST 以占位文案展示默认值 `<Xcode>/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport`（`<Xcode>` 经 `xcode-select -p` 解析，失败回退 `/Applications/Xcode.app/Contents/Developer`）。
- modern developer image 目录（iOS17+ 镜像列表）：持久化键 `settings/ddi_modern_dir`；为空时占位文案展示默认值 `/Library/Developer/CoreDevice/CandidateDDIs`。

两个目录均 SHALL 可经文件选择器浏览，亦可直接填写路径。

#### Scenario: 关闭开关禁用 section 内选项

- **WHEN** 用户关闭 System Developer Image 的启用开关
- **THEN** 该 section 内 legacy / modern 目录输入框与浏览按钮变为 disable，且开关状态写入 `settings/ddi_local_enabled`

#### Scenario: 目录为空展示默认占位

- **WHEN** legacy 或 modern 目录留空
- **THEN** 输入框以"默认:…"占位文案展示对应默认路径

### Requirement: DeveloperDiskImage 标签 — GitHub Download Image section

`DeveloperDiskImage` 标签 SHALL 提供「GitHub Download Image」section，包含一个启用开关、GitHub Token 输入与保存目录：

- 启用开关：持久化键 `settings/ddi_github_enabled`（默认启用）。关闭时本 section 内其余控件 MUST disable。
- GitHub Token：持久化键 `settings/ddi_github_token`；输入框 SHALL 以密码方式遮挡回显；旁附说明文案：默认从 doronz88 的 DeveloperDiskImage 仓库下载，无 token 限额 60 次/小时，配置 token 后 5000 次/小时。Token 属敏感凭据，MUST NOT 写入任何日志。
- GitHub 镜像保存目录：持久化键 `settings/ddi_github_save_dir`；为空时占位文案展示默认值 `~/Library/CablediOS/DDI`；可经文件选择器浏览或直接填写。

#### Scenario: Token 遮挡且不入日志

- **WHEN** 用户在 GitHub Token 输入框填写 token
- **THEN** 回显被遮挡，值写入 `settings/ddi_github_token`，且不出现在任何日志输出中

#### Scenario: 关闭开关禁用 section 内选项

- **WHEN** 用户关闭 GitHub Download Image 的启用开关
- **THEN** Token 输入与保存目录控件变为 disable，且开关状态写入 `settings/ddi_github_enabled`

### Requirement: DeveloperDiskImage 标签 — 来源优先级 section

`DeveloperDiskImage` 标签 SHALL 提供「来源优先级」section，用于配置 System Developer Image 与 GitHub Download Image 的优先顺序，持久化键 `settings/ddi_source_priority`（默认 `local,github`，即本地优先）。当某来源 section 的启用开关被关闭时，其在优先级配置中的对应项 MUST disable（不可参与排序/被选中）。当两个来源均被禁用时，优先级 section 整体 MUST disable 并提示需至少启用一个来源。

本变更只负责该配置的呈现与持久化；挂载时对优先级的实际消费由 `add-local-ddi-mount` 承接。

#### Scenario: 禁用来源联动优先级项

- **WHEN** 用户禁用其中一个来源 section
- **THEN** 该来源在优先级配置中的对应项变为 disable

#### Scenario: 两来源均禁用

- **WHEN** System Developer Image 与 GitHub Download Image 均被禁用
- **THEN** 优先级 section 整体 disable 并提示至少启用一个来源

