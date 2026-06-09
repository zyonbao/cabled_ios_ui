## ADDED Requirements

### Requirement: 查询 DDI 挂载状态

平台层 SHALL 提供 `ddi_status(target)`，经 usbmux lockdown 查询设备的 DeveloperDiskImage 挂载状态，返回是否已挂载、镜像类型、开发者模式状态与 iOS 主版本。该查询 MUST NOT 依赖 XPC tunnel（iOS 17+ 亦然）。镜像类型 SHALL 按 iOS 版本选择（iOS<17 为 `Developer`、iOS 17+ 为 `Personalized`）。

#### Scenario: 已挂载

- **WHEN** 设备已挂载对应版本的 DDI
- **THEN** 返回 `{ok, data:{mounted:true, imageType, developerMode, iosMajor}}`

#### Scenario: 未挂载

- **WHEN** 设备未挂载 DDI
- **THEN** 返回 `{ok, data:{mounted:false, ...}}`

### Requirement: 多方式挂载 DDI

平台层 SHALL 提供 `ddi_mount(target, method, **paths)`，支持以下挂载方式：`auto`（按版本自动分流）、`personalized`（iOS 17+ 个性化镜像，联网下载）、`developer`（iOS<17 开发者镜像）、`manual`（手动本地镜像文件）。`manual` 在 iOS 17+ MUST 接受 `image`/`build_manifest`/`trustcache` 三个文件，在 iOS<17 MUST 接受 `image`/`signature` 两个文件。已挂载（`AlreadyMountedError`）MUST 视为成功（幂等）；开发者模式未开启 MUST 返回可读错误提示用户在设备设置中开启。挂载 MUST NOT 依赖 XPC tunnel。

#### Scenario: 自动挂载成功

- **WHEN** 用户选择 `auto` 方式且镜像可获取
- **THEN** 设备挂载 DDI，返回 `{ok, data:{mounted:true}}`

#### Scenario: 手动挂载（iOS 17+）

- **WHEN** 用户选择 `manual` 并提供 image/build_manifest/trustcache
- **THEN** 经 `PersonalizedImageMounter.mount` 挂载，返回成功

#### Scenario: 已挂载幂等

- **WHEN** 设备已挂载 DDI 时再次挂载
- **THEN** 视为成功返回，不报错

#### Scenario: 开发者模式未开启

- **WHEN** 设备未开启开发者模式
- **THEN** 返回可读错误，提示在设备「设置 → 隐私与安全性 → 开发者模式」开启

### Requirement: 卸载 DDI

平台层 SHALL 提供 `ddi_unmount(target)`，按 iOS 版本选择对应 mounter（iOS<17 `DeveloperDiskImageMounter`、iOS 17+ `PersonalizedImageMounter`）调用 `umount()` 卸载已挂载的 DDI。未挂载时 MUST 返回可读结果而非崩溃。

#### Scenario: 卸载成功

- **WHEN** 设备已挂载 DDI 且用户请求卸载
- **THEN** 卸载该镜像，返回 `{ok, data:{unmounted:true}}`
