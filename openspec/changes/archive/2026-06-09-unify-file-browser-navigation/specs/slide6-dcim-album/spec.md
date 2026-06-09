## MODIFIED Requirements

### Requirement: 相册（DCIM）缩略图浏览

`slide6_ui` SHALL 在左侧 Tab 栏提供「相册」Tab，基于 `root="media"`、路径 `/DCIM`（及其 `100APPLE` 等子目录）以**缩略图网格**展示媒体文件。条目元数据来自 `afc_list`。app SHALL 维护一个**按设备（UDID）的本地磁盘缩略图缓存**（以 remote 路径为 key、以原图 `(st_size, st_mtime)` 失效，内容为小 JPEG），跨会话持久；缩略图 SHALL 仅对可见项**按需异步建缓存**，其余可后台渐进补齐。缩略图来源 SHALL 优先复用 iOS 端缩略图——按原文件名映射经 `afc_read` 读取 `PhotoData/Thumbnails/V2/DCIM/<相册>/<文件名>/` 下小 JPG 直接落地缓存；缺失时回退读原图生成 JPEG 缩略图。HEIC/HEIF 原图 SHALL 用 `pillow-heif`（必备依赖）解码（不依赖 Qt 的 heif 插件），非 HEIC 用 `QImage` 解码；解码失败、原图超阈值或无法生成、以及视频等非图片项 SHALL 显示占位图标（视频不提取首帧）。

导航交互 SHALL 与其它文件浏览器一致：顶部导航栏 SHALL 按统一顺序 **「上一级」按钮 - 可编辑路径输入框 - 「刷新」按钮** 排列（其后接「导出选中」）；「上一级」按钮 SHALL 在非 `/DCIM` 根目录启用、在 `/DCIM` 根禁用。可编辑路径输入框展示当前路径，用户编辑后回车 SHALL 跳转到目标路径；跳转目标 SHALL 经规范化并夹在 `/DCIM` 根内（越出则收敛到 `/DCIM`），使相册 Tab 不浏览到 DCIM 之外。该 Tab 无需 WDA。

#### Scenario: 网格展示 DCIM

- **WHEN** 用户选中设备并进入「相册」Tab
- **THEN** 列出 `/DCIM` 下相册子目录与媒体文件，媒体文件以缩略图网格展示

#### Scenario: 进入相册子目录

- **WHEN** 用户双击某相册子目录（如 `100APPLE`）
- **THEN** 进入该目录并展示其媒体缩略图，并可经「上一级」按钮返回

#### Scenario: 根目录禁用上一级

- **WHEN** 当前处于 `/DCIM` 根目录
- **THEN**「上一级」按钮为禁用态，进入子目录后恢复启用

#### Scenario: 编辑路径回车跳转

- **WHEN** 用户在路径输入框输入某 `/DCIM` 下的路径并回车
- **THEN** 相册跳转列举该目录

#### Scenario: 路径越界收敛到根

- **WHEN** 用户输入越出 `/DCIM` 根的路径（含 `..` 越界）并回车
- **THEN** 路径经规范化收敛到 `/DCIM`，不浏览到 DCIM 之外
