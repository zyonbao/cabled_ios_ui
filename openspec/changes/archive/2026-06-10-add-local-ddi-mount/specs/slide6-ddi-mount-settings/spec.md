## MODIFIED Requirements

### Requirement: DeveloperDiskImage 标签 — GitHub Download Image section

`DeveloperDiskImage` 标签 SHALL 提供「GitHub Download Image」section，包含一个启用开关、GitHub Token 输入与保存目录：

- 启用开关：持久化键 `settings/ddi_github_enabled`（默认启用）。关闭时本 section 内其余控件 MUST disable。
- GitHub Token：持久化键 `settings/ddi_github_token`；输入框 SHALL 以密码方式遮挡回显；旁附说明文案 SHALL 说明 token **仅在回退到 GitHub API 下载时生效**——默认优先从 `raw.githubusercontent.com` 直下镜像（不受 API 限额、无需 token），仅当 iOS<17 无法经 raw 定位版本目录而回退到 GitHub API 时才用 token（无 token 60 次/小时，配置后 5000 次/小时）。Token 属敏感凭据，MUST NOT 写入任何日志。
- GitHub 镜像保存目录：持久化键 `settings/ddi_github_save_dir`；为空时占位文案展示默认值 `~/Library/CablediOS/DDI`；可经文件选择器浏览或直接填写。

#### Scenario: Token 遮挡且不入日志

- **WHEN** 用户在 GitHub Token 输入框填写 token
- **THEN** 回显被遮挡，值写入 `settings/ddi_github_token`，且不出现在任何日志输出中

#### Scenario: 关闭开关禁用 section 内选项

- **WHEN** 用户关闭 GitHub Download Image 的启用开关
- **THEN** Token 输入与保存目录控件变为 disable，且开关状态写入 `settings/ddi_github_enabled`
