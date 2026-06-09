## ADDED Requirements

### Requirement: 相册（DCIM）缩略图浏览

`slide6_console` SHALL 在左侧 Tab 栏提供「相册」Tab，基于 `root="media"`、路径 `/DCIM`（及其 `100APPLE` 等子目录）以**缩略图网格**展示媒体文件。条目元数据来自 `afc_list`。app SHALL 维护一个**按设备（UDID）的本地磁盘缩略图缓存**（以 remote 路径为 key、以原图 `(st_size, st_mtime)` 失效，内容为小 JPEG），跨会话持久；缩略图 SHALL 仅对可见项**按需异步建缓存**，其余可后台渐进补齐。缩略图来源 SHALL 优先复用 iOS 端缩略图——按原文件名映射经 `afc_read` 读取 `PhotoData/Thumbnails/V2/DCIM/<相册>/<文件名>/` 下小 JPG 直接落地缓存；缺失时回退读原图生成 JPEG 缩略图。HEIC/HEIF 原图 SHALL 用 `pillow-heif`（必备依赖）解码（不依赖 Qt 的 heif 插件），非 HEIC 用 `QImage` 解码；解码失败、原图超阈值或无法生成、以及视频等非图片项 SHALL 显示占位图标（视频不提取首帧）。该 Tab 无需 WDA 或 tunnel。

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

### Requirement: 双击查看大图

「相册」Tab SHALL 支持双击某图片项弹出大图查看：HEIC/HEIF 用 `pillow-heif` 解码、非 HEIC 用 `QImage` 解码，按窗口尺寸适配显示。视频（如 .MOV/.MP4）SHALL 仅显示占位/提示（不提取首帧），且不影响其导出/删除。

#### Scenario: 查看图片大图

- **WHEN** 用户双击一个图片项（含 HEIC）
- **THEN** 弹出大图查看窗口，HEIC 经 `pillow-heif`、其余经 `QImage` 解码后按窗口尺寸适配显示

#### Scenario: 视频或无法解码的项

- **WHEN** 用户双击视频或无法解码的项
- **THEN** 展示占位/提示，不报错

### Requirement: 带元数据导出

「相册」Tab SHALL 支持将选中媒体导出到本地（`afc_pull`，保留文件字节与修改时间，EXIF/HEIC 等元数据原样保留，不转码）。首版 SHALL NOT 在「相册」Tab 提供"导入到相册"——经 AFC 写入 `/DCIM` 是否登记进 Photos 相册取决于系统索引、无法保证；如需向设备写文件，用户可使用「文件系统」Tab 的 AFC 导入。

#### Scenario: 导出媒体（保留元数据）

- **WHEN** 用户对选中媒体执行导出并选择本地位置
- **THEN** 通过 `afc_pull` 写入本地，文件字节与修改时间、内嵌元数据原样保留（HEIC 导出仍为 HEIC）

#### Scenario: 相册 Tab 不提供导入

- **WHEN** 用户在「相册」Tab 查找导入入口
- **THEN** 相册 Tab 不提供"导入到相册"操作（导入媒体改由「文件系统」Tab 经 AFC 完成）

### Requirement: 多选删除并二次确认

「相册」Tab SHALL 支持多选媒体项，并对删除操作弹出**一次汇总二次确认**（展示选中数量及示例名称）；确认后逐项 `afc_rm` 并刷新网格。

#### Scenario: 多选删除确认后删除

- **WHEN** 用户多选若干媒体项并点击删除，且在确认对话框中确认
- **THEN** 逐项通过 `afc_rm` 删除并刷新网格

#### Scenario: 取消删除

- **WHEN** 用户在确认对话框中取消
- **THEN** 不删除任何项，网格保持不变
