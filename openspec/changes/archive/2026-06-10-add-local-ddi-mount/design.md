## Context

DDI 挂载现状（`ddi-mount-op`）：`ddi_mount(method, **paths)` 的 `auto` 直接调 pmd3 `auto_mount`，`personalized`/`developer` 调 `auto_mount_personalized`/`auto_mount_developer`，`manual` 用本地文件经 `PersonalizedImageMounter`/`DeveloperDiskImageMounter` 挂载。

关键事实（已查证）：

- **iOS 17+ 是通用个性化镜像**：一份 `Image.dmg + BuildManifest.plist + trustcache` 对所有 17+ 机型/版本通用，挂载时由 pmd3 用设备 AP ticket（TSS）个性化签名（`get_personalized_disk_image()` 无版本参数即佐证）。
- **iOS < 17 需按版本精确匹配** `DeveloperDiskImage.dmg` + `.signature`。
- 本机 `/Library/Developer/CoreDevice/CandidateDDIs/iOS_DDI.dmg` 是 Apple 签名的通用 iOS DDI（root 拥有、全局可读）；其内部 `Restore/` 含镜像三件套，需 `hdiutil` 取出。
- `developer_disk_image` 库下载入口仅 `DeveloperDiskImageRepository.create(github_token=...)`（拉 `api.github.com` 仓库 tree，再按 blob URL 下 `get_personalized_disk_image()` / `get_developer_disk_image(version)`，返回原始 bytes）。带 token 时 GitHub 限额从 60/小时升到 5000/小时。
- 个性化挂载成功后立刻调 `CopyDevices` 会在设备侧卡死（不回包），导致 `ddi_status` 超时。

`add-settings-window-revamp`（已归档）提供并持久化以下键：`ddi_local_enabled` / `ddi_legacy_dir` / `ddi_modern_dir` / `ddi_github_enabled` / `ddi_github_token` / `ddi_github_save_dir` / `ddi_source_priority`。本变更让 `auto` 流程消费它们。

约束：仅 macOS 有 `CandidateDDIs`；`hdiutil` 系统自带；不引入新 Python 依赖；保留 `manual`。

## Goals / Non-Goals

**Goals:**

- 把「自动（按系统版本）」做成**版本感知 + 按设置优先级 + 本地优先 + 可缓存 + 可配 token** 的统一可控流程。
- iOS 17+ 优先复用本机通用镜像；iOS<17 优先复用 Xcode 版本匹配镜像；本地缺失再按优先级走 GitHub 下载（带 token、存盘缓存）。
- 移除冗余的 `personalized`/`developer` 显式方式。
- 固化 `ddi_status` 对 `CopyDevices` 卡死免疫。

**Non-Goals:**

- 保留 iOS<17 的 `{major}.{minor}` 归约语义（丢弃 patch，与 pmd3 一致）；在缺精确版本时**新增**基于 `ddi_image_index.json` 的 nearest-lower 就近回退（同 major、`minor' <= 设备 minor` 的最高可用版本），不引入其它匹配策略。
- 不自动升级 Xcode / 不主动从 Apple 拉新 DDI（仅消费本机已有候选）。
- 不改 `manual` 行为。

## Decisions

### 决策 1：`auto` 重写为"主版本分流 → 优先级编排 → 来源各自解析 → 按族挂载"

先按设备主版本分流到 **legacy（<17）/ modern（17+）** 两条流程。**legacy 先据内置索引把设备版本解析为唯一的规范目标版本 `target`**（见下），该 `target` 同时用于本地探测与下载；随后按设置优先级遍历来源，命中即挂载：

```
major, minor = parse(device.ProductVersion)
family = personalized if major >= 17 else developer
# <17 先据内置索引离线定版（决策 2）。target 可能为 None（设备版本低于索引、
# 或索引偶尔落后）——此时本地跳过、下载源仍可经 live tree 兜底重算，故此处不硬报错。
target = resolve_target_from_index(major, minor) if family == developer else None
for source in settings.ddi_source_priority:          # 跳过被禁用的来源
    files = resolve_source(source, family, target)   # 拿不到 → None，试下一个
    if files: mount(family, files); return ok
return err("没有可用的 DDI 来源…")  # 可读，提示检查设置/网络
```

**关键原则（已修订）**：iOS 17 以前的 DDI **基本冻结但偶有更新**，内置索引为 <17 的**主版本地图**：`target` 的"精确 / 就近回退"**优先由内置索引离线计算一次**（决策 2），本地来源**不再单独枚举目录做就近回退**（只判断是否存在该 `target`）；当内置索引下载失败/无 `target` 时，下载源 MAY 经 `developer_disk_image` 库拉 **live tree 重新就近定版并下载**（覆盖索引落后/缺失）。

- `resolve_source("local", target)`：
  - **modern（17+）**：在 `ddi_modern_dir`（默认 CandidateDDIs）找 `iOS_DDI.dmg` → `hdiutil` 取三件套（无版本概念）。
  - **legacy（<17）**：`target` 已定时在 `ddi_legacy_dir`（默认 Xcode `iPhoneOS.platform/DeviceSupport`）命中——**把每个子目录名归约为 `{major}.{minor}`**（剥离 build/patch 后缀，如 `16.4 (20E247)`、`16.4.1 (…) arm64e` → `16.4`）再与 `target` 比对，取含 `DeveloperDiskImage.dmg(.signature)` 者；存在即用、否则 None；`target` 为 None 时跳过本地（无法离线定版）。
- `resolve_source("github", target)`：
  - 先在 `ddi_github_save_dir` 查缓存（modern：三件套齐全；legacy：`<target>` 的 image+signature 齐全）→ 命中即用。
  - 未命中 → **下载**（见决策 2）落盘到保存目录（modern 存三件套；legacy 存 `<ver>/DeveloperDiskImage.dmg`+`.signature`）→ 用落盘文件。

**理由**：<17 内置索引覆盖绝大多数场景、运行时定版离线零 API、本地/下载共用同一 `target`；偶发的索引落后/raw 失败由 live tree 兜底自愈，不需要手动刷索引。

### 决策 2：下载 = raw CDN 直下为主，库（带 token）作兜底（两族对称）

**legacy 定版 `resolve_target_from_index(major, minor)`（离线、决策 1 在遍历来源前调用一次）**：把设备版本归约为 `{major}.{minor}`，在内置索引（决策 7）`developer_image_versions` 中查精确匹配；不存在则**就近回退**（同 major、`minor' <= 设备 minor` 的最高可用版本）。无任何 ≤ 候选 → 返回 None（本地跳过，下载源经 live tree 兜底）。**全程离线、零 API。**

`github` 来源未命中缓存时下载，**两族都遵循 raw 主、库兜底**：

**legacy（<17）**：
1. **raw 直下**（`target` 已定时；base 取索引 `raw_base`）：GET `DeveloperDiskImages/<target>/DeveloperDiskImage.dmg(.signature)`，校验 HTTP 200 且非空；不调 `api.github.com`、不用 token。
2. **库兜底**（raw 失败，或 `target` 为 None / 内置索引落后于仓库）：`DeveloperDiskImageRepository.create(github_token=ddi_github_token or None)` 拉 **live tree → 重新就近定版** `target'`（同 major、`minor' <= 设备 minor` 的最高可用版本，可能比内置索引更新）→ `get_developer_disk_image(target')` 下载。**此处才用 token。** live tree 仍无 ≤ 候选 → 该来源失败。

**modern（17+）**：通用镜像、无版本概念。
1. **raw 直下**：3 个固定路径 `PersonalizedImages/Xcode_iOS_DDI_Personalized/{Image.dmg,BuildManifest.plist,Image.dmg.trustcache}`，校验 200/非空；不用 token。
2. **库兜底**（raw 失败）：`DeveloperDiskImageRepository.create(github_token=…).get_personalized_disk_image()`（库已确认提供此 API）。**此处才用 token。** 失败 → 该来源失败。

每次下载所得 MUST 落盘到 `ddi_github_save_dir` 后再挂载；token MUST NOT 记录明文（仅记"是否带 token"布尔）。

**理由**：把 <17 的"哪个版本 + 就近选择"前移到**构建期**固化进 bundle，运行时选版离线、零 API，本地与下载共用同一 `target`；raw 直下绕开限额；偶发的索引落后/raw 失败由 live tree 重算定版兜底（带 token）自愈。

**索引生成**：`ios_toolkit/tools/gen_ddi_index.py` 重新生成（优先 GitHub tree API，限额/失败时回退 `git clone --filter=blob:none --no-checkout` + `git ls-tree` 枚举，不下载大 blob）。实测当前索引含 <17 版本 `11.4`–`16.7` 共 40 个 + personalized。

**实测依据**：raw 上个性化三件套均 HTTP 200、真二进制（非 LFS 指针；`Image.dmg` ~15MB）；仓库 `DeveloperDiskImages` 按 `{major}.{minor}` 组织（无 patch 级目录），与 pmd3 `auto_mount_developer` 的版本归约一致。

**token 角色**：raw 直下不使用 token；token 仅在"raw 失败 → 库兜底"路径生效。Settings 中 token 说明文案据此改为"仅在回退到 GitHub API 下载时生效"。

### 决策 3：iOS 17+ 本地镜像从 `iOS_DDI.dmg` 取三件套

`hdiutil attach -nobrowse -readonly -plist <iOS_DDI.dmg>` → 解析 mount point → 按模式定位 `Image.dmg` / `BuildManifest.plist` / `*.trustcache` → 经 `PersonalizedImageMounter.mount(...)`（个性化签名由 pmd3 在设备上完成）→ `finally` 中 `hdiutil detach`（detach 失败仅记日志、不抛出）。

### 决策 4：移除 `personalized` / `developer` 方式

- UI `_MOUNT_METHODS` 收敛为 `auto` + `manual`。
- `device.py:ddi_mount` 删除 `personalized`/`developer` 分支（且不再含 `auto` 解析逻辑，见决策 8）。
- `toolkit_api.py` 方式白名单收敛为 `{auto, manual}`，未知方式返回可读错误。

**理由**：两者能力已被重写后的 `auto` 覆盖（本地/下载、版本分流都在内），保留只会语义重叠、误导用户。

### 决策 8：镜像获取与设备挂载解耦——`ios_toolkit/ddi_provider.py` 独立工具

`ios_toolkit` 聚焦"设备管理与交互"，因此把"镜像从哪来"的全部逻辑（内置索引加载、<17 离线定版、本地查找、`hdiutil` 取三件套、GitHub raw/库下载与就近回退）抽到独立模块 `ios_toolkit/ddi_provider.py`，与设备通信彻底分离：

- **`ddi_provider`（纯获取工具，不依赖设备/Qt）**：对外暴露 `ddi_family(major)`、`parse_major_minor(version)`、`resolve_ddi_image(major, minor, *, sources, legacy_dir, modern_dir, github_token, github_save_dir) -> Optional[ResolvedDDI]`。`ResolvedDDI` 持有 `family/source/target` 与镜像文件路径，并提供 `mount_kwargs()`（转成 `ddi_mount` 的文件入参）与 `cleanup()`（删除 17+ 本地解包产生的临时目录）。
- **`device.py:ddi_mount(family, *, image, signature/build_manifest/trustcache)`**：退化为纯设备挂载——只接收已解析的 developer/personalized 文件参数，做上传 + 挂载 + 幂等（`AlreadyMountedError`）+ 开发者模式错误处理，不再含任何 index/local/download/fallback 逻辑。
- **`toolkit_api.py:ddi_mount(target, method, ...)`（编排层）**：`auto` → 调 `ddi_provider.resolve_ddi_image(...)` 拿 `ResolvedDDI` → `device.ddi_mount(...)` → `finally cleanup()`，并把 `source/target` 回填进成功结果；`manual` → 直接用调用方提供的文件参数调 `device.ddi_mount`。族（family）由设备版本在此层推导。

**取舍**：解析与挂载解耦后，"某来源已产出文件但挂载失败"**不再**自动回退下一个来源（挂载失败多为设备侧原因：开发者模式未开、已挂载等）；"某来源产不出文件"的跨来源回退仍保留在 `resolve_ddi_image` 内。该模块仍置于 `ios_toolkit` 包内（与 `ddi_image_index.json` 同级、复用现有 Nuitka `--include-package=ios_toolkit` 打包，无需新增打包配置）。

### 决策 5：`ddi_status` 对 `CopyDevices` 卡死免疫（固化）

顺序：`is_image_mounted`（限时 10s，取挂载布尔）→ `query_developer_mode_status`（限时 5s）→ **最后** `CopyDevices`（限时 5s，仅补镜像类型/路径明细，超时跳过且不再在该会话发命令）。

### 决策 6：Settings 消费位置

为保持 `ios_toolkit` 与 UI 解耦，由 **UI 在调用 `toolkit_api.ddi_mount` 时把来源配置作为入参传入**（`sources=[...]`、`legacy_dir`、`modern_dir`、`github_token`、`github_save_dir`），`ddi_provider`/`device.py` 均不直接依赖 Qt；缺省时由 `ddi_provider` 回落到内置默认路径。UI 侧从 `QSettings(ios_ui_ta_proxy, slide6_console)` 读取对应键。

### 决策 7：内置 DDI 版本索引文件 `ios_toolkit/ddi_image_index.json`

- **内容**：`raw_base`、`developer_image_versions`（<17 可用版本清单）、`developer_images`（各版本 dmg/signature 相对路径）、`personalized_image`（17+ 三件套相对路径）、`source`/`ref`/`generated_at`。
- **生成**：`ios_toolkit/tools/gen_ddi_index.py`（构建/维护期运行；GitHub tree API 优先，限额时回退 `git clone --filter=blob:none` + `git ls-tree`，不下载大 blob）。
- **打包**：`packaging/build_macos_app.sh` 用 `--include-data-files=…/ddi_image_index.json=ios_toolkit/ddi_image_index.json` 精确纳入该单个 JSON（避免 `--include-package-data` 全量打入其他数据文件），目标路径与模块同级，运行时 `Path(__file__).parent` 可定位。
- **运行时定位**：`Path(__file__).parent / "ddi_image_index.json"`（源码与 Nuitka 冻结环境一致）；缺失/损坏时降级——17+ 直接尝试 raw 固定路径；<17 `target` 解析失败时回退 `developer_disk_image` 库拉 live tree 计算 `target`（带 token），并记日志。
- **<17 基本冻结、偶有更新**：iOS 17 起改用通用个性化镜像，`DeveloperDiskImages/` 极少新增版本，故内置索引对 <17 视为主版本地图、`target` 优先离线解析；偶发更新/落后由下载源的 live tree 兜底（决策 2）自愈，可选地定期重跑 `gen_ddi_index.py` 刷新内置索引。

**理由**：<17 版本判定与就近回退在运行时优先离线，避免 `api.github.com` 限额；本地与下载共用同一 `target`；索引可用 `gen_ddi_index.py` 一键重生。

## Risks / Trade-offs

- **无 Xcode / `CandidateDDIs` 缺失** → local 来源跳过；若同时禁用/无网导致 github 也不可用 → 返回可读错误，提示检查设置或网络。
- **`iOS_DDI.dmg` 内部布局变化** → 按模式（`*.dmg`/`BuildManifest.plist`/`*.trustcache`）容错；找不到即报错并 detach。
- **内置索引落后/无 `target`**（仓库偶发更新或设备版本低于索引）→ 本地跳过；下载源经 live tree（带 token）重新就近定版并下载兜底；live tree 仍无 ≤ 候选才报"无可用来源"。多数 <17 设备走本地 Xcode 即可，下载为兜底。
- **token 误入日志** → 下载鉴权处禁止打印 token；仅记"是否使用 token"布尔。
- **`hdiutil` detach 泄漏** → 统一 `finally` detach。

## Open Questions

- **TBD（暂不做盲目延时）**：挂载成功后"等 1s 再刷新以提升首刷拿到镜像明细"暂不采用；待调研更可靠的 `CopyDevices` 触发时机。
- （已定）<17 定版优先由内置索引离线完成，本地与下载共用同一 `target`；下载 raw 为主，raw 失败/索引落后/无 `target` 时由 live tree 重新就近定版并下载兜底（带 token）。token 保留于 Settings，说明改为"仅在回退到 API 下载时生效"。
