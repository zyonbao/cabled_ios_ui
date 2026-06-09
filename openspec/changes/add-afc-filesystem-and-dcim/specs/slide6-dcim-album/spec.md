## ADDED Requirements

### Requirement: 相册（DCIM）缩略图浏览

`slide6_console` SHALL 在左侧 Tab 栏提供「相册」Tab，基于 `root="media"`、路径 `/DCIM`（及其 `100APPLE` 等子目录）以**缩略图网格**展示媒体文件。条目元数据来自 `afc_list`；缩略图 SHALL 仅对可见项**按需异步加载**（经 `afc_read` 取字节后用 `QImage` 缩放），并按 remote 路径在内存缓存，避免滚动重复拉取。不可解码或非图片项 SHALL 回退为占位图标。该 Tab 无需 WDA 或 tunnel。

#### Scenario: 网格展示 DCIM

- **WHEN** 用户选中设备并进入「相册」Tab
- **THEN** 列出 `/DCIM` 下相册子目录与媒体文件，媒体文件以缩略图网格展示

#### Scenario: 缩略图按需加载与回退

- **WHEN** 网格滚动使某媒体项可见
- **THEN** 异步经 `afc_read` 取字节生成缩略图；解码失败或非图片项展示占位图标

#### Scenario: 进入相册子目录

- **WHEN** 用户双击某相册子目录（如 `100APPLE`）
- **THEN** 进入该目录并展示其媒体缩略图，并可返回上一级

### Requirement: 双击查看大图

「相册」Tab SHALL 支持双击某图片项弹出大图查看（`QImage` 适配窗口缩放）。对暂不支持预览的类型（如视频 .MOV）SHALL 给出占位或提示，且不影响其导出/删除。

#### Scenario: 查看图片大图

- **WHEN** 用户双击一个可解码的图片项
- **THEN** 弹出大图查看窗口，按窗口尺寸适配显示

#### Scenario: 不支持预览的类型

- **WHEN** 用户双击视频或无法解码的项
- **THEN** 展示占位/提示，不报错

### Requirement: 带元数据导入/导出

「相册」Tab SHALL 支持将选中媒体导出到本地（`afc_pull`，保留文件字节与修改时间，EXIF 等元数据原样保留），以及从本地导入媒体到当前相册目录（`afc_push`，按字节写入，不转码）。

#### Scenario: 导出媒体（保留元数据）

- **WHEN** 用户对选中媒体执行导出并选择本地位置
- **THEN** 通过 `afc_pull` 写入本地，文件内嵌元数据与修改时间保留

#### Scenario: 导入媒体

- **WHEN** 用户选择或拖入本地图片/视频导入
- **THEN** 通过 `afc_push` 按字节写入当前 DCIM 目录并刷新网格
- **AND** UI 提示"已写入文件，相册可见性取决于系统索引"（不声称写入 Photos 库）

### Requirement: 多选删除并二次确认

「相册」Tab SHALL 支持多选媒体项，并对删除操作弹出**一次汇总二次确认**（展示选中数量及示例名称）；确认后逐项 `afc_rm` 并刷新网格。

#### Scenario: 多选删除确认后删除

- **WHEN** 用户多选若干媒体项并点击删除，且在确认对话框中确认
- **THEN** 逐项通过 `afc_rm` 删除并刷新网格

#### Scenario: 取消删除

- **WHEN** 用户在确认对话框中取消
- **THEN** 不删除任何项，网格保持不变
