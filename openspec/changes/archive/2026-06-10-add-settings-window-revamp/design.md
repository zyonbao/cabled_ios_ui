## Context

现状：`MainWindow._open_preferences` 打开一个平铺单页对话框，含「Ask to clean XPC tunnel on exit」开关与一个「日志」区（启用开关 + 目录输入 + 浏览）。配置项即将增多（DDI 多来源、GitHub token、优先级），单页布局不可持续。

既有持久化键（沿用）：`settings/ask_clean_tunnel_on_exit`、`settings/logging_enabled`、`settings/logging_dir`，存储于 `QSettings(ios_ui_ta_proxy, slide6_console)`。

本变更是 UI + 持久化的"配置面"工作；DDI 配置项的**消费**（挂载时按来源/优先级取镜像、用 token 下载）由 `add-local-ddi-mount` 承接，不在本变更内实现。

## Goals / Non-Goals

**Goals:**

- Settings 重构为 3 个水平标签：General / Logging / DeveloperDiskImage。
- 提供并持久化 DDI 镜像来源配置（System Developer Image / GitHub Download Image / 优先级）。
- Logging 目录占位文案直接展示默认路径。
- 合理的默认值，开箱即与现有行为一致。

**Non-Goals:**

- 不实现挂载逻辑对这些配置的消费（属 `add-local-ddi-mount`）。
- 不改变 General / Logging 既有键名与既有行为（除占位文案）。
- 不引入加密存储（token 存 `QSettings`，与平台一致；仅保证不入日志）。

## Decisions

### 决策 1：用 `QTabWidget` 承载三标签

`_open_preferences` 改为构建 `QTabWidget`，三个页签分别构建 General / Logging / DDI 内容控件。沿用现有 `QSettings` 实例与"变更即写回"的交互（无独立"保存"按钮，关闭即生效），与现有日志区行为一致。

**备选**：用 `QListWidget`+`QStackedWidget` 的侧边导航式；水平标签更轻、更贴合需求描述。

### 决策 2：DDI 配置的 QSettings 键与默认值

| 配置 | 键 | 默认值 |
|---|---|---|
| System Developer Image 启用 | `settings/ddi_local_enabled` | `true` |
| legacy(iOS<17) 镜像目录 | `settings/ddi_legacy_dir` | `<Xcode>/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport` |
| modern(iOS17+) 镜像目录 | `settings/ddi_modern_dir` | `/Library/Developer/CoreDevice/CandidateDDIs` |
| GitHub Download 启用 | `settings/ddi_github_enabled` | `true` |
| GitHub Token | `settings/ddi_github_token` | 空 |
| GitHub 镜像保存目录 | `settings/ddi_github_save_dir` | `~/Library/CablediOS/DDI` |
| 来源优先级 | `settings/ddi_source_priority` | `local,github`（本地优先） |

- `<Xcode>` 通过 `xcode-select -p` 解析（失败回退 `/Applications/Xcode.app/Contents/Developer`）。
- 目录输入框为空时，UI 以占位文案展示对应默认值（与 Logging 一致的"默认:xxx"风格）。

**理由**：legacy 标准目录即 pmd3 `auto_mount_developer` 使用的 Xcode `DeviceSupport`、modern 即 CoreDevice 候选目录——二者均为**只读来源**，保持系统路径不可改到应用目录（否则读不到镜像）。日志与 GitHub 下载镜像属应用自有可写数据，统一归入 `~/Library/CablediOS/`（`Logs/` 与 `DDI/`）。

### 决策 3：section 启用联动

- System Developer Image / GitHub Download Image 各有一个启用开关；关闭时该 section 内的其余控件 disable。
- 「来源优先级」section 展示两个来源的顺序配置；当某来源 section 被禁用时，其在优先级中的对应项 disable（不可参与排序/被选中）。
- 两个来源都禁用时，优先级 section 整体 disable，并提示"至少启用一个来源"。

### 决策 4：GitHub Token 的安全处理

token 存 `QSettings`（本地、明文，与现有平台设置一致），输入框可用 `QLineEdit.Password` 回显遮挡；**MUST NOT** 写入任何日志（呼应安全基线第 4 条与日志系统的脱敏要求）。说明文案静态展示 doronz88 仓库地址与限额对比。

## Risks / Trade-offs

- **token 明文存储** → 受限于 QSettings 现状；缓解：回显遮挡 + 严禁入日志 + 文案提示仅本机使用。
- **默认 Xcode 路径在无 Xcode 机器上不存在** → 仅作为占位默认；真正消费时（`add-local-ddi-mount`）再做存在性校验与降级提示。
- **配置面先行、暂无消费方** → 本变更只落地配置与持久化；需在 `add-local-ddi-mount` 中显式消费，避免"配了不生效"的割裂感（已在该变更中交叉引用）。
- **优先级 UI 复杂度** → 采用「可上移/下移的有序列表」，为将来 >2 来源预留扩展；不做可拖拽复杂交互。

## Open Questions

- （已定）优先级 UI 形态：采用「可上移/下移的有序列表」（为将来扩展更多来源预留），而非两项下拉。
