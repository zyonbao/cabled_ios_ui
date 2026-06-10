# Tasks

## 0. 内置版本索引（已完成）

- [x] 0.1 `ios_toolkit/tools/gen_ddi_index.py`：索引生成器（GitHub tree API 优先，限额回退 `git clone --filter=blob:none` + `git ls-tree`）
- [x] 0.2 生成 `ios_toolkit/ddi_image_index.json`（<17 版本 `11.4`–`16.7` 共 40 个 + personalized）
- [x] 0.3 `packaging/build_macos_app.sh`：用 `--include-data-files=…/ddi_image_index.json=ios_toolkit/ddi_image_index.json` 精确纳入单个 JSON（主构建 + fallback GUI 构建）

## 1. 平台层：来源解析 helpers

- [x] 1.1 `ios_toolkit/device.py`：`_load_ddi_index()` 读取并缓存 `ddi_image_index.json`（`Path(__file__).parent`，缺失/损坏降级 + 记日志）
- [x] 1.2 `ios_toolkit/device.py`：`_resolve_target_from_index(major, minor)`——<17 据内置索引离线解析目标版本 `target`：精确 `{major}.{minor}` 命中即取，否则就近回退（同 major、`minor' <= 设备 minor` 的最高可用版本）；无 ≤ 候选返回 None（不报错，交由下载源 live tree 兜底）。**该 `target` 同时用于本地与下载，本地不再单独枚举。**
- [x] 1.3 `ios_toolkit/device.py`：`_resolve_local_image(family, target, legacy_dir, modern_dir)`（实现为 `_find_local_developer_image` + `_find_ios_ddi_dmg`）——17+ 在 modern 目录定位 `iOS_DDI.dmg`（存在性校验）；<17 `target` 已定时枚举 legacy 目录，**把每个子目录名归约为 `{major}.{minor}`**（剥离 build/patch 后缀，如 `16.4 (20E247)`/`16.4.1 (…) arm64e`→`16.4`）与 `target` 比对，取含 `DeveloperDiskImage.dmg(.signature)` 者（不做就近回退）；`target` 为 None 或无匹配返回 None
- [x] 1.4 `ios_toolkit/device.py`：`_extract_personalized_from_dmg(dmg_path)`——`hdiutil attach -nobrowse -readonly -plist` 解析挂载点，按模式定位 `Image.dmg`/`BuildManifest.plist`/`*.trustcache`，返回三路径；`finally` `hdiutil detach`（失败仅记日志）；attach/缺文件返回可读错误
- [x] 1.5 `ios_toolkit/device.py`：`_resolve_github_image(family, target, save_dir, token)`（实现为 `_resolve_github_developer_image` + `_resolve_github_personalized_image`）——先查 save_dir 缓存（齐全即用）；未命中按 **raw 主 / 库兜底**：(a) raw 直下——17+ 三个固定 URL；<17 `target` 已定时从 `raw_base` 取 `<target>` 目录；GET 校验 200/非空、不调 api.github.com、不用 token；(b) 当 raw 传输失败 / <17 `target` 为 None / 索引落后时回退 `developer_disk_image.DeveloperDiskImageRepository.create(github_token=token or None)`——17+ `get_personalized_disk_image`；<17 拉 **live tree 重新就近定版** `target'` 后 `get_developer_disk_image(target')`（live tree 仍无 ≤ 候选则失败）；落盘并返回文件路径；下载处禁止记录 token 明文（仅记是否带 token 布尔）。

## 2. 平台层：重写 auto + 移除冗余方式

- [x] 2.1 `ios_toolkit/device.py` `ddi_mount`：重写 `method == "auto"`——读设备主版本定族；<17 先 `_resolve_target_from_index` 定 `target`（可能 None，不在此报错）；按来源优先级（入参 `sources`）跳过禁用项依次 `_resolve_local_image`/`_resolve_github_image`（共用 `target`，`target` 为 None 时本地跳过、下载源 live tree 兜底）；命中即经 `PersonalizedImageMounter`/`DeveloperDiskImageMounter` 挂载；全失败返回可读错误；`AlreadyMountedError` 幂等；不依赖 tunnel；关键路径补日志（`target`、命中来源、镜像路径、build、失败 `exc_info`）
- [x] 2.2 `ios_toolkit/device.py` `ddi_mount`：删除 `personalized`/`developer` 分支；保留 `manual`
- [x] 2.3 `ios_toolkit/toolkit_api.py` `ddi_mount` 包装：方式白名单收敛为 `{auto, manual}`；透传来源配置入参（sources/legacy_dir/modern_dir/github_token/github_save_dir）；入口日志记录 method 与是否带 token（布尔，不记 token 值）

## 3. 平台层：ddi_status 加固（对照固化）

- [x] 3.1 `ios_toolkit/device.py` `ddi_status`：确认顺序 `is_image_mounted`（限时）→ `query_developer_mode_status`（限时）→ `CopyDevices`（限时、最后、仅补明细、超时跳过且不再发命令）

## 3b. 重构：镜像获取与设备挂载解耦（`ddi_provider` 独立工具）

> `ios_toolkit` 聚焦设备管理与交互；§1 的来源解析 helpers 与 §2.1 的 `auto` 编排全部迁出到独立模块。

- [x] 3b.1 新增 `ios_toolkit/ddi_provider.py`：迁入 §1.1–1.5 全部 helpers（`_load_ddi_index`/`resolve_target_from_index`/`parse_major_minor`/`_nearest_lower_version`/`_find_local_developer_image`/`_find_ios_ddi_dmg`/`_hdiutil_attach|detach`/`_extract_personalized_from_dmg`/`_http_get_bytes`/`_resolve_github_developer_image`/`_resolve_github_personalized_image`/`ddi_legacy_default_dir`）+ Nuitka `developer_disk_image` 静态 hint
- [x] 3b.2 `ddi_provider`：新增 `ddi_family(major)`、`ResolvedDDI`（`family/source/target` + 文件路径 + `mount_kwargs()` + `cleanup()`）与公共编排 `resolve_ddi_image(major, minor, *, sources, legacy_dir, modern_dir, github_token, github_save_dir)`（族分流 + 定 `target` + 按优先级返回首个产出文件的来源；无则 None；token 仅记布尔）
- [x] 3b.3 `ios_toolkit/device.py`：`ddi_mount` 退化为纯设备挂载 `ddi_mount(family, *, image, signature, build_manifest, trustcache)`（仅上传+挂载+幂等+开发者模式错误处理）；删除全部 index/local/download/fallback 逻辑与相关 import（`plistlib`/`re`/`shutil`/`subprocess`/`tempfile`）
- [x] 3b.4 `ios_toolkit/toolkit_api.py`：`ddi_mount` 升为编排层——`auto` 调 `ddi_provider.resolve_ddi_image` 拿 `ResolvedDDI` → `device.ddi_mount(...)` → `finally cleanup()` → 回填 `source/target`；`manual` 直接透传文件参数；族由设备版本推导

## 4. UI：挂载方式精简 + 配置透传 + token 文案

- [x] 4.1 `slide6_ui/developer_tools/developer_tools_tab.py`：`_MOUNT_METHODS` 收敛为 `auto`/`manual`；移除 personalized/developer 选项与相关提示文案
- [x] 4.2 调用 `ddi_mount(method="auto", ...)` 时从 `QSettings` 读取来源配置（开关/优先级/legacy&modern 目录/token/保存目录）并作为入参传入
- [x] 4.3 `auto` 返回"无可用来源"错误时，状态栏给出可读提示（复用现有失败展示路径）
- [x] 4.4 `slide6_ui/main_window.py`：GitHub Token 说明文案改为"仅在回退到 GitHub API 下载时生效（raw 直下不受限额、无需 token）"

## 4b. DVT 就绪探测 + 乐观挂载/卸载（已完成）

- [x] 4b.1 `ios_toolkit/device.py`：新增 `ddi_wait_ready(timeout=500)`——最轻量 DVT 握手（open+close `DvtProvider`，不发 instrument 请求），退避重试至成功或超时；每次尝试限时（`asyncio.wait_for` + future timeout）避免卡死钉住循环；成功 `{ok,{ready:true}}`、超时 `TIMEOUT`
- [x] 4b.2 `ios_toolkit/toolkit_api.py`：新增 `ddi_wait_ready(target, timeout)` 包装
- [x] 4b.3 `developer_tools_tab.py`：挂载成功乐观更新——立即「已挂载（准备中…）」+ 禁用功能位 + 后台 `ddi_wait_ready`；就绪成功置「已挂载」并解锁、超时置「已挂载（准备超时…）」；不在挂载成功后立刻查 `ddi_status`
- [x] 4b.4 `developer_tools_tab.py`：卸载乐观更新——成功即「未挂载」，不自动刷新 `ddi_status`；保留 iOS 17+ 自动重挂提示
- [x] 4b.5 `developer_tools_tab.py`：`_ready_token` 让旧探测回调失效（切设备 / 卸载 bump）；`_op_in_flight` + `_ready_probing` 抑制挂载/卸载或探测期间的并发 `ddi_status` 刷新；iOS 17+ tunnel 启动后若已挂载未就绪自动重探

## 5. 验证

- [x] 5.1 lint 无误 + 导入冒烟（已过：helpers 单测 16.4.1→16.4、16.99→16.7、11.0→None、12.9→12.4、目录名归约；UI/平台导入正常）
- [x] 5.2 真机手验（iOS 17+，本地优先）：本机有 `iOS_DDI.dmg` → 选「自动」→ 离线挂载成功（无 GitHub 请求）→ 挂载成功乐观显示「已挂载（准备中…）」→ DVT 就绪后解锁功能位 → 卸载乐观显示「未挂载」
- [x] 5.3 下载/缓存手验（iOS 17+）：禁用本地来源或移走 `iOS_DDI.dmg` → 「自动」走 raw CDN 直下三件套成功并落盘（抓包确认无 api.github.com 请求、未用 token）→ 再次挂载命中缓存不再下载
- [x] 5.4 iOS<17 手验：按 `{major}.{minor}`（如 16.4.1→16.4）解析 `target` 后本地命中挂载成功；据索引就近解析（如索引无 16.5 时 `target=16.4`）本地/raw 命中成功；构造 raw 失败 / 索引无 `target` 场景验证回退库 live tree 重新就近定版下载（带 token）成功
- [x] 5.6 索引手验（源码侧）：`gen_ddi_index.py` 可重生 JSON；`_load_ddi_index()` 在源码环境定位成功
- [x] 5.5 回归：`manual` 不受影响；移除的 personalized/developer 选项不再出现；无可用来源时 UI 提示可读
