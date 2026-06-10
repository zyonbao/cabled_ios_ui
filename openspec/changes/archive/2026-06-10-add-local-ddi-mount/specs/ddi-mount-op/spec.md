## MODIFIED Requirements

### Requirement: 多方式挂载 DDI

平台层 SHALL 提供 `ddi_mount(target, method, **opts)`，支持两种挂载方式：`auto`（版本感知、按来源优先级的统一流程）与 `manual`（手动本地镜像文件）。已挂载（`AlreadyMountedError`）MUST 视为成功（幂等）；开发者模式未开启 MUST 返回可读错误提示用户在设备设置中开启；挂载 MUST NOT 依赖 XPC tunnel；未知方式 MUST 返回可读错误。

**分层约束**：镜像**获取**（内置索引、本地查找、`hdiutil` 取三件套、GitHub raw/库下载与就近回退）MUST 由独立工具模块 `ios_toolkit/ddi_provider`（不依赖设备/Qt）承担；设备层 `iOSDevice.ddi_mount(family, *, image/signature/build_manifest/trustcache)` MUST 仅接收已解析的镜像文件参数并执行上传+挂载（纯设备交互，不含任何 index/local/download/fallback 逻辑）；`toolkit_api.ddi_mount` 为编排层（`auto` 调 `ddi_provider.resolve_ddi_image` 拿文件后调设备层挂载并在 `finally` 清理临时目录，`manual` 直接透传文件）。族（family，`<17`=developer / `>=17`=personalized）由设备版本在编排层推导。解析与挂载解耦后，"某来源已产出文件但挂载失败"不再自动回退下一来源；"某来源产不出文件"的跨来源回退仍由 `resolve_ddi_image` 内部保留。

`auto` MUST 按如下流程执行：

1. MUST 先读取设备 iOS 主版本，`< 17` 走 `DeveloperDiskImageMounter`（开发者镜像族），`>= 17` 走 `PersonalizedImageMounter`（个性化镜像族）；MUST NOT 直接调用 pymobiledevice3 的 `auto_mount`/`auto_mount_personalized`/`auto_mount_developer`。
2. **iOS<17 目标版本解析（先于遍历来源、离线）**：MUST 把设备 `ProductVersion` 归约为 `{major}.{minor}`（丢弃 patch，与 pmd3 `auto_mount_developer` 一致；例 16.4.1→16.4），并据随包内置的**离线版本索引**（`ios_toolkit/ddi_image_index.json`）解析目标版本 `target`：索引中存在该 `{major}.{minor}` 则取之，否则**就近回退**取同 `major`、`minor' <= 设备 minor` 的最高可用版本；无 ≤ 候选时 `target` 为 None。该解析 MUST 离线、MUST NOT 调用 `api.github.com`。`target` 已定时 MUST 同时用于本地探测与下载，本地 MUST NOT 另行枚举目录做就近回退。`target` 为 None 时 MUST NOT 在此处报错（本地来源跳过，下载来源可经 live tree 兜底重算）。iOS 17+ 无版本概念、不解析 `target`。
3. MUST 按来源优先级配置依次尝试**已启用**的来源（被禁用的来源 MUST 跳过）；任一来源产出可用镜像即挂载并返回成功；所有启用来源均无法产出镜像时 MUST 返回可读错误（提示检查来源设置或网络）。
4. **System Developer Image（本地）来源**：iOS 17+ 在 modern 目录定位 `iOS_DDI.dmg` 并经 `hdiutil` 离线取出通用个性化镜像三件套；iOS<17 `target` 已定时在 legacy 目录命中——MUST 把每个子目录名归约为 `{major}.{minor}`（剥离 build/patch 后缀，如 `16.4 (20E247)`/`16.4.1 (…) arm64e` → `16.4`）再与 `target` 比对，取其中含 `DeveloperDiskImage.dmg`+`.signature` 者；存在即用、否则落到下一来源（MUST NOT 联网、MUST NOT 改写 `target`），`target` 为 None 时本地来源 MUST 跳过。
5. **GitHub Download 来源** MUST 先在配置的保存目录查是否已有满足需求的镜像文件（iOS<17 为 `<target>` 的 image+signature、iOS 17+ 为三件套；缓存命中即用、不联网）；未命中才下载，两族均遵循 **raw 直下为主、库（带 token）作兜底**：
   - iOS<17（`target` 已定）：MUST 先从 `raw.githubusercontent.com`（索引 `raw_base`）直下 `<target>` 版本目录的 `DeveloperDiskImage.dmg`+`.signature`（不调 `api.github.com`、不用 token）。
   - iOS 17+：MUST 从 `raw.githubusercontent.com` 直下固定的个性化镜像三件套路径（不调 `api.github.com`、不用 token）。
   - **库兜底**：当 raw 传输失败、或 iOS<17 `target` 为 None / 内置索引落后于仓库时，MAY 回退 `developer_disk_image` 库——iOS<17 MUST 拉 **live tree 重新就近定版**（同 `major`、`minor' <= 设备 minor` 的最高可用版本，可能比内置索引更新）后 `get_developer_disk_image(target')`；iOS 17+ `get_personalized_disk_image`。此回退路径 MUST 使用配置的 GitHub token 鉴权（无 token 受 60 次/小时匿名限额）；live tree 仍无 ≤ 候选 → 该来源失败。
   - 每次下载 MUST 校验 HTTP 200 与非空内容，所得 MUST 落盘到保存目录后再挂载；token MUST NOT 记录明文（仅可记"是否使用 token"布尔）。
6. iOS 17+ 个性化签名 MUST 由挂载器在设备上用设备 ticket 完成（平台层不做加密操作）；`hdiutil` 挂载 MUST 在 `finally` 中 detach，detach 失败仅记日志不得覆盖主错误。

`manual` 在 iOS 17+ MUST 接受 `image`/`build_manifest`/`trustcache` 三个文件，在 iOS<17 MUST 接受 `image`/`signature` 两个文件。

#### Scenario: 自动挂载（iOS 17+，本地优先命中）

- **WHEN** 用户选择 `auto`，来源优先级中本地来源在前且本机存在 `iOS_DDI.dmg`
- **THEN** 平台层离线取出通用个性化镜像三件套并经 `PersonalizedImageMounter` 挂载，返回 `{ok, data:{mounted:true, source:"local", ...}}`，全程不访问网络

#### Scenario: 自动挂载（本地缺失回退下载，raw 直下 + 缓存）

- **WHEN** 用户选择 `auto`，本地来源无可用镜像且 GitHub 来源已启用（iOS 17+）
- **THEN** 平台层先查保存目录缓存，未命中则从 `raw.githubusercontent.com` 直下三件套（不调 api.github.com、不用 token）并存盘，再挂载并返回成功；后续再次挂载 MUST 命中缓存而不重复下载

#### Scenario: iOS<17 据内置索引解析 target 后本地/下载共用

- **WHEN** iOS<17（如 16.5），内置索引无 16.5 但有同 major 的 16.4
- **THEN** 平台层先据索引离线解析 `target=16.4`；按优先级先查本地（子目录名归约为 `{major}.{minor}` 后匹配 `16.4`，兼容 `16.4 (20E247)` 命名，命中即用），否则从 raw 直下 `16.4` 并存盘后挂载（本地与下载用同一 `target`）

#### Scenario: raw 失败或索引落后时回退库 live tree 重算（带 token）

- **WHEN** iOS<17 据内置索引 `<target>` 的 raw 直下失败（传输失败或仓库已无该版本），或内置索引无 ≤ 候选（`target` 为 None）
- **THEN** 平台层回退 `developer_disk_image` 库（用配置的 token）拉 live tree 重新就近定版 `target'`（可能比内置索引更新）后 `get_developer_disk_image(target')` 下载并存盘，再挂载；iOS 17+ 则 `get_personalized_disk_image`

#### Scenario: 自动挂载（iOS<17 按 major.minor 匹配，丢弃 patch）

- **WHEN** 用户选择 `auto`，设备 iOS<17（如 16.4.1），内置索引含 `16.4`
- **THEN** 平台层把版本归约为 `{major}.{minor}`（16.4），解析 `target=16.4`，在 legacy 目录或下载来源取 `16.4` 的 `DeveloperDiskImage.dmg`+`.signature` 并经 `DeveloperDiskImageMounter` 挂载；不查找 patch 级目录

#### Scenario: 内置索引无 target 时下载源经 live tree 兜底

- **WHEN** iOS<17 内置索引无 ≤ 候选（`target` 为 None），但 GitHub 下载来源已启用
- **THEN** 本地来源跳过；下载来源经 live tree（带 token）重新就近定版并下载，成功则挂载；若 live tree 亦无 ≤ 候选且无其他可用来源，`auto` MUST 返回可读错误

#### Scenario: 无可用来源

- **WHEN** 用户选择 `auto`，所有启用来源都无法产出镜像（本地缺失且无网络/限额）
- **THEN** 返回可读错误，提示检查来源设置或网络

#### Scenario: 手动挂载（iOS 17+）

- **WHEN** 用户选择 `manual` 并提供 image/build_manifest/trustcache
- **THEN** 经 `PersonalizedImageMounter.mount` 挂载，返回成功

#### Scenario: 已挂载幂等

- **WHEN** 设备已挂载 DDI 时再次挂载
- **THEN** 视为成功返回，不报错

#### Scenario: 开发者模式未开启

- **WHEN** 设备未开启开发者模式
- **THEN** 返回可读错误，提示在设备「设置 → 隐私与安全性 → 开发者模式」开启

### Requirement: 查询 DDI 挂载状态

平台层 SHALL 提供 `ddi_status(target)`，经 usbmux lockdown 查询设备的 DeveloperDiskImage 挂载状态，返回是否已挂载、镜像类型、开发者模式状态与 iOS 主版本。该查询 MUST NOT 依赖 XPC tunnel（iOS 17+ 亦然）。镜像类型 SHALL 按 iOS 版本选择（iOS<17 为 `Developer`、iOS 17+ 为 `Personalized`）。该查询 MUST 对"个性化挂载成功后 `CopyDevices` 卡死（设备侧不回包）"免疫：MUST 以轻量的 `is_image_mounted`（`LookupImage`）作为挂载布尔值的主来源；`CopyDevices` MUST 限时执行且仅用于补充镜像类型 / 挂载路径明细，超时或失败 MUST 跳过而不阻塞状态返回；`CopyDevices` MUST 作为该会话最后一个命令执行，超时后不得在同一会话继续发送命令（避免迟到回包导致协议错位）。

#### Scenario: 已挂载

- **WHEN** 设备已挂载对应版本的 DDI
- **THEN** 返回 `{ok, data:{mounted:true, imageType, developerMode, iosMajor}}`

#### Scenario: 未挂载

- **WHEN** 设备未挂载 DDI
- **THEN** 返回 `{ok, data:{mounted:false, ...}}`

#### Scenario: CopyDevices 卡死时仍返回状态

- **WHEN** 个性化挂载刚成功，`CopyDevices` 在设备侧卡死不回包
- **THEN** 状态查询在限时内回退，仍基于 `is_image_mounted` 返回 `{ok, data:{mounted:true}}`（可不含镜像路径明细），不超时失败

## ADDED Requirements

### Requirement: 探测开发者服务（DVT）就绪

平台层 SHALL 提供 `ddi_wait_ready(target, timeout=500)`，用**最轻量的 DVT 握手**作为「开发者服务是否可用」的就绪信号：仅打开并立即关闭一个 `DvtProvider`（即只完成 DTX capability 握手、不发任何 instrument 请求），带退避重试直至成功或超时。该探测 MUST 走开发者服务通道（iOS 17+ 经 RSD/tunnel、iOS<17 经 usbmux），MUST NOT 查询 mounter（个性化挂载刚成功后 mounter 会持续无响应数分钟，正是该探测要规避的服务）。每次尝试 MUST 限时（避免握手卡死钉住循环）；成功返回 `{ok, data:{ready:true}}`，超时返回可读的 `TIMEOUT` 错误。该能力 SHALL 用于挂载成功后解锁依赖 DVT 的功能（进程 / 定位），而非轮询 `ddi_status`。

UI SHALL 对挂载/卸载采用**乐观更新**：`ddi_mount`/`ddi_unmount` 的 RPC 返回成功即视为权威结果立即反映到界面，MUST NOT 在操作完成后立刻查询 `ddi_status`（mounter 此刻忙碌，查询会超时并被误判为操作失败）。挂载成功后状态 SHALL 显示「已挂载（准备中…）」并禁用 DVT 功能位，后台 `ddi_wait_ready` 成功后才置为「已挂载」并解锁功能位、超时则置为「已挂载（准备超时…）」。挂载/卸载进行中或就绪探测进行中时，并发的 `ddi_status` 刷新 MUST 被抑制，以免撞上忙碌的 mounter 而超时。

#### Scenario: 挂载成功后探测 DVT 就绪并解锁功能

- **WHEN** `ddi_mount` 返回成功，UI 启动后台 `ddi_wait_ready`
- **THEN** 状态先显示「已挂载（准备中…）」且功能位禁用；当 DVT 握手成功时状态变为「已挂载」并解锁进程 / 定位功能

#### Scenario: DVT 就绪探测超时

- **WHEN** 挂载成功但设备在超时（默认 500s）内开发者服务仍未起来（如 iOS 17+ 未启动 XPC tunnel）
- **THEN** `ddi_wait_ready` 返回 `TIMEOUT`，UI 状态显示「已挂载（准备超时…）」，功能位保持禁用，可刷新重试或重新挂载

#### Scenario: 挂载/卸载期间抑制并发状态查询

- **WHEN** 挂载或卸载 RPC 正在执行（mounter 忙碌），同时触发了 `ddi_status` 刷新
- **THEN** 刷新被抑制不发起查询；操作自身的回调负责更新界面状态，不出现「查询 DDI 状态超时」误报
