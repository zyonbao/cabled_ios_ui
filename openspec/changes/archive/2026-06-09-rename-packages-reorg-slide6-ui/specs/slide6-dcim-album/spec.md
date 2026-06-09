## MODIFIED Requirements

### Requirement: 相册（DCIM）缩略图浏览

`slide6_ui` SHALL 在左侧 Tab 栏提供「相册」Tab，基于 `root="media"`、路径 `/DCIM`（及其 `100APPLE` 等子目录）以**缩略图网格**展示媒体文件。条目元数据来自 `afc_list`。app SHALL 维护一个**按设备（UDID）的本地磁盘缩略图缓存**（以 remote 路径为 key、以原图 `(st_size, st_mtime)` 失效，内容为小 JPEG），跨会话持久；缩略图 SHALL 仅对可见项**按需异步建缓存**，其余可后台渐进补齐。缩略图来源 SHALL 优先复用 iOS 端缩略图——按原文件名映射经 `afc_read` 读取 `PhotoData/Thumbnails/V2/DCIM/<相册>/<文件名>/` 下小 JPG 直接落地缓存；缺失时回退读原图生成 JPEG 缩略图。HEIC/HEIF 原图 SHALL 用 `pillow-heif`（必备依赖）解码（不依赖 Qt 的 heif 插件），非 HEIC 用 `QImage` 解码；解码失败、原图超阈值或无法生成、以及视频等非图片项 SHALL 显示占位图标（视频不提取首帧）。该 Tab 无需 WDA 或 tunnel。

#### Scenario: 网格展示 DCIM

- **WHEN** 用户选中设备并进入「相册」Tab
- **THEN** 列出 `/DCIM` 下相册子目录与媒体文件，媒体文件以缩略图网格展示

#### Scenario: 优先复用 iOS 端缩略图建本地缓存

- **WHEN** 某图片项可见且其 `PhotoData/Thumbnails/V2/DCIM/<相册>/<文件名>/` 缩略图存在且本地缓存未命中
- **THEN** 经 `afc_read` 读取该小 JPG 落地为本地缓存并展示，不读取原图

#### Scenario: 缩略图缺失时回退生成

- **WHEN** 该项无 iOS 端缩略图
- **THEN** 经 `afc_read` 读原图生成 JPEG 缩略图（HEIC/HEIF 用 `pillow-heif`，非 HEIC 用 `QImage`）落地缓存；原图超阈值或无法生成、或为视频/非图片项时展示占位图标

#### Scenario: 命中本地缓存

- **WHEN** 该项本地缓存存在且原图 `(st_size, st_mtime)` 未变
- **THEN** 直接用本地缓存展示，不再访问设备

#### Scenario: 进入相册子目录

- **WHEN** 用户双击某相册子目录（如 `100APPLE`）
- **THEN** 进入该目录并展示其媒体缩略图，并可返回上一级
