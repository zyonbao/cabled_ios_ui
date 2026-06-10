## Why

现状 DDI 挂载有三处不顺手：

1. **iOS 17+ 的 `auto`/`personalized` 走 pmd3 内部 `auto_mount_personalized`**：固定调用 `DeveloperDiskImageRepository.create()`（**空参、无 token**）联网从 doronz88 GitHub 仓库下载镜像，匿名限额 60 次/小时容易打满（已复现 `GithubRateLimitExceededError`），且**不看本机已有的 Xcode/CoreDevice 镜像**。
2. **来源与缓存不可控**：pmd3 路径既不接受我们刚在 Settings 落地的 GitHub token，也不复用本机已下载/Xcode 自带的镜像，导致每次都可能重新联网。
3. **挂载方式选项冗余**：`个性化镜像(iOS17+)` 与 `开发者镜像(iOS<17)` 两个手动联网选项与 `auto` 语义重叠，徒增困惑。

`add-settings-window-revamp` 已落地 DDI 来源配置（System Developer Image 本地目录、GitHub token 与保存目录、来源优先级）。本变更让挂载逻辑**消费这些配置**，把"自动"做成一条可控、本地优先、可缓存、可配 token 的统一流程。

## What Changes

- **重写「自动（按系统版本）」挂载流程**，不再直接调用 pmd3 的 `auto_mount`/`auto_mount_personalized`/`auto_mount_developer`，改为自行编排：
  1. **先取设备版本号**，按 `< 17` / `>= 17` 决定挂载族（`DeveloperDiskImageMounter` / `PersonalizedImageMounter`）。
  2. **iOS<17 目标版本解析（先于来源、优先离线）**：把设备版本归约为 `{major}.{minor}`（丢弃 patch，与 pmd3 一致；例 16.4.1→16.4），据随包**内置离线版本索引** `ios_toolkit/ddi_image_index.json` 解析出 `target`（精确命中或**就近回退**：同 major、`minor' <= 设备 minor` 的最高可用版本，零 API）；该 `target` **同时用于本地探测与下载**，本地不再单独就近回退；无 ≤ 候选时 `target=None`（不在此报错，交由下载源 live tree 兜底）。iOS 17+ 无版本概念。
  3. **按 Settings 的来源优先级**（`ddi_source_priority`）依次尝试启用的来源（被禁用的来源跳过）。
  4. **System Developer Image（本地）来源**：17+ 在 modern 目录定位 `iOS_DDI.dmg`；<17 `target` 已定时在 legacy 目录命中——**把每个子目录名也归约为 `{major}.{minor}`** 再与 `target` 比对（兼容 `16.4 (20E247)`、`16.4.1 (…) arm64e` 等带 build/patch 后缀的命名），取含 `DeveloperDiskImage.dmg`+`.signature` 者；命中即用、否则落到下一来源；`target=None` 时跳过本地。
  5. **GitHub Download 来源**：先在保存目录查缓存（命中即用），没有才下载，两族均 **raw 主 / 库兜底**——
     - **raw 直下**（不经 `api.github.com`、不受 60/小时限额、无需 token）：iOS 17+ 为 3 个固定 URL；iOS<17 为已定 `target` 的版本目录。
     - **库兜底**：当 raw 传输失败、或 iOS<17 `target` 为 None / 内置索引落后于仓库（偶发更新）时，回退 `developer_disk_image` 库——iOS<17 拉 **live tree 重新就近定版** `target'` 后下载（覆盖索引落后），iOS 17+ `get_personalized_disk_image`，此时才用 Settings 的 token 提升限额。
     - 下载所得 MUST 存入保存目录缓存，再挂载。
  6. 任一来源产出镜像即挂载；所有启用来源都拿不到镜像时返回可读错误。
- **移除挂载方式中的 `个性化镜像（iOS17+，联网下载）` 与 `开发者镜像（iOS<17）`**（UI 选项 + 平台层 `personalized`/`developer` 分支 + API 白名单）。挂载方式精简为 `auto`（上述统一流程）与 `manual`（手动选本地文件）。
- **保留并固化 `ddi_status` 对 `CopyDevices` 卡死的免疫**（先轻量 `is_image_mounted`，`CopyDevices` 限时、最后、超时跳过）。

## Capabilities

### New Capabilities
<!-- 无新增独立 capability：本变更是对既有 DDI 挂载能力的重写与加固 -->

### Modified Capabilities
- `ddi-mount-op`: `auto` 重写为版本感知 + 按 Settings 优先级的多来源（本地/下载）流程，下载优先 raw CDN（免限额/免 token）、<17 不确定时回退 `developer_disk_image`（带 token），本地优先 + 缓存；移除 `personalized`/`developer` 方式；`ddi_status` 对 `CopyDevices` 卡死免疫。
- `slide6-developer-tools`: DDI 挂载方式选项精简为「自动（按系统版本）」与「手动选本地镜像文件」。
- `slide6-ddi-mount-settings`: GitHub Token 说明文案改为"仅在回退到 GitHub API 下载时生效（raw 直下不受限额、无需 token）"。

## Impact

- 代码：
  - `ios_toolkit/ddi_image_index.json`（新增，随包内置）+ `ios_toolkit/tools/gen_ddi_index.py`（索引生成器）。
  - `packaging/build_macos_app.sh`：用 `--include-data-files=…/ddi_image_index.json=ios_toolkit/ddi_image_index.json` 精确把该 JSON 打入 bundle（不全量纳入 `ios_toolkit` 数据文件）。
  - `ios_toolkit/ddi_provider.py`（新增，独立"镜像获取工具"，不依赖设备/Qt）：内置索引加载、<17 离线定版、本地查找、`hdiutil` 取 `iOS_DDI.dmg` 三件套、GitHub raw 直下 + 库（带 token）就近回退；公共 API `resolve_ddi_image(...) -> ResolvedDDI` / `ddi_family` / `parse_major_minor`。
  - `ios_toolkit/device.py`：`ddi_mount` 退化为纯设备挂载 `ddi_mount(family, *, image/signature/build_manifest/trustcache)`（仅上传+挂载+幂等+开发者模式错误处理），删除全部 index/local/download/fallback 逻辑与 `personalized`/`developer` 分支；`ddi_status` 加固对照固化。
  - `ios_toolkit/toolkit_api.py`：`ddi_mount` 升为编排层——`auto` 调 `ddi_provider.resolve_ddi_image` 拿文件再调设备层挂载（`finally` 清理临时目录、回填 `source/target`），`manual` 透传文件；方式白名单 `auto`/`manual`；入口日志记录 method/family 与是否带 token（布尔）。
  - 读取 Settings（`QSettings`）：来源开关 / 优先级 / legacy & modern 目录 / GitHub token / 保存目录。平台层经入参或读取键消费（详见 design）。
  - `slide6_ui/developer_tools/developer_tools_tab.py`：`_MOUNT_METHODS` 收敛为 `auto`/`manual`。
- 依赖：使用 macOS 自带 `hdiutil`、`requests`（raw 下载，已随 `developer_disk_image` 间接引入）与既有 `developer_disk_image` 库（仅 <17 回退用）；无新增 Python 依赖。
- 安全：GitHub token 仅在 API 回退下载时本地读取用于鉴权，MUST NOT 写入日志（安全基线第 4 条）。raw 下载经 HTTPS，MUST 校验 HTTP 200 与非空内容。
- 平台：本地来源依赖 macOS 专有路径（Xcode `DeviceSupport` / CoreDevice `CandidateDDIs`），缺失时该来源自动跳过。
