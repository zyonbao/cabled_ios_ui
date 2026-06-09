# slide6-dcim-album Specification

## Purpose
定义桌面应用「相册」Tab 的能力：基于 `root="media"` 的 AFC 浏览设备 DCIM 相册，提供正方形居中裁剪的缩略图网格（优先复用 iOS 端缩略图、本地磁盘缓存）、双击查看大图（HEIC 经 pillow-heif 解码）、带元数据导出；不提供导入到相册与删除（相册增删需经设备上 iOS App 调用系统照片库接口）。
## Requirements
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

### Requirement: 双击查看大图

「相册」Tab SHALL 支持双击某图片项弹出大图查看：HEIC/HEIF 用 `pillow-heif` 解码、非 HEIC 用 `QImage` 解码，按窗口尺寸适配显示。视频（如 .MOV/.MP4）SHALL 仅显示占位/提示（不提取首帧），且不影响其导出。

#### Scenario: 查看图片大图

- **WHEN** 用户双击一个图片项（含 HEIC）
- **THEN** 弹出大图查看窗口，HEIC 经 `pillow-heif`、其余经 `QImage` 解码后按窗口尺寸适配显示

#### Scenario: 视频或无法解码的项

- **WHEN** 用户双击视频或无法解码的项
- **THEN** 展示占位/提示，不报错

### Requirement: 带元数据导出

「相册」Tab SHALL 支持将选中媒体导出到本地（`afc_pull`，保留文件字节与修改时间，EXIF/HEIC 等元数据原样保留，不转码）。

#### Scenario: 导出媒体（保留元数据）

- **WHEN** 用户对选中媒体执行导出并选择本地位置
- **THEN** 通过 `afc_pull` 写入本地，文件字节与修改时间、内嵌元数据原样保留（HEIC 导出仍为 HEIC）

### Requirement: 相册缩略图居中裁剪填充

「相册」Tab 的缩略图 SHALL 以**正方形居中裁剪（Crop）**方式呈现：缩略图在生成/落地阶段统一裁为 `_THUMB_PX × _THUMB_PX` 正方形 JPEG（按比例放大至覆盖后居中裁剪），并使网格 `iconSize`/`gridSize` 基于该正方形边长，使图标满格显示、无变形、无留边。来自 iOS 端缓存的缩略图 JPG 与回退生成的缩略图 SHALL 经同一裁剪流水线落地，保证两种来源观感一致。缩略图本地缓存的失效因子 SHALL 包含裁剪策略版本标记，使切换到居中裁剪后旧的非正方形缓存自然失效并重建。

#### Scenario: 不同宽高比图片裁剪为正方形

- **WHEN** 相册中存在竖图、横图或方图缩略项
- **THEN** 各缩略图均以正方形居中裁剪显示、铺满网格单元，不出现拉伸变形或留边

#### Scenario: iOS 端缓存缩略图同样裁剪

- **WHEN** 某项缩略图来源为 iOS 端缓存 JPG
- **THEN** 该 JPG 经同一居中裁剪流水线落地为正方形缓存后展示，与回退生成的缩略图观感一致

#### Scenario: 切换裁剪策略后旧缓存失效重建

- **WHEN** 切换为居中裁剪策略后再次浏览同一相册
- **THEN** 因缓存失效因子含裁剪版本标记，旧的非正方形缓存被判失效并重建为正方形缩略图

### Requirement: 相册网格间距与文件名展示

「相册」Tab 的缩略图网格 SHALL 使用紧凑的单元间距（横纵约 16px），每个媒体项 SHALL 在缩略图下方以**单行**展示其文件名（过长居中省略、悬停可见完整名）。单元尺寸 SHALL 固定为缩略图边长加一个文件名带高度，使文件名始终可见、不被裁切。

#### Scenario: 展示文件名

- **WHEN** 用户浏览相册媒体网格
- **THEN** 每个媒体项缩略图下方显示其文件名（单行，过长居中省略，悬停显示完整名）

#### Scenario: 紧凑网格间距

- **WHEN** 网格排布多张缩略图
- **THEN** 相邻单元横纵间距约 16px，不出现过宽留白

### Requirement: 相册不提供导入与删除

「相册」Tab SHALL NOT 提供「导入到相册」与「删除选中（媒体）」操作。原因：Apple「照片」相册由系统数据库索引、**不仅依赖文件管理**——可靠地向相册增删媒体需经 iOS App 调用系统相册接口（如 PhotoKit），仅经 AFC 在 `/DCIM` 下增删文件无法保证反映到「照片」相册。需要对设备文件进行导入/删除时，用户 SHALL 改用「文件系统」Tab 的 AFC 操作（其增删仅作用于文件层面，不等同于相册库增删）。

#### Scenario: 相册无导入入口

- **WHEN** 用户在「相册」Tab 查找导入入口
- **THEN** 相册 Tab 不提供「导入到相册」操作

#### Scenario: 相册无删除入口

- **WHEN** 用户在「相册」Tab 查找删除入口
- **THEN** 相册 Tab 不提供「删除选中」操作；如需删除设备文件改由「文件系统」Tab 完成

### Requirement: 相册根隐藏系统点目录

「相册」Tab SHALL 以 `/DCIM` 为根，并在列表中隐藏以 `.` 开头的系统/隐藏条目（如 `.MISC`）。相册 SHALL NOT 将根硬编码为某个具体相册子目录（如 `100APPLE`），以便完整展示设备上所有 DCF 相册子目录（`100APPLE`、`101APPLE`、…），在不同 iOS 版本/多相册场景下均正确。

#### Scenario: 隐藏 .MISC 并保留全部相册子目录

- **WHEN** `/DCIM` 下同时存在 `.MISC` 与多个 `NNNAPPLE` 相册子目录
- **THEN** 列表隐藏 `.MISC`，但展示全部 `NNNAPPLE` 相册子目录

