## ADDED Requirements

### Requirement: 访问设备媒体分区根（root="media"）

`executor_ios.toolkit_api` 的 AFC 系列函数 SHALL 支持 `root="media"`，经 `AfcService`（`com.apple.afc`，lockdown 直连）访问设备**媒体分区根**（含 `DCIM`、`Downloads`、`Books` 等，**不含** App 沙盒）。`media` 模式下逻辑根 `/` 直接对应媒体分区根（无路径偏移），`bundle_id` SHALL 被忽略（可为空）。访问无需 WDA 或 XPC tunnel。`sub_path`/`remote_path` SHALL 沿用既有规范化与越界校验。

#### Scenario: 列出媒体分区目录

- **WHEN** 调用 `afc_list(target, "", "media", sub_path)`
- **THEN** 返回 `ok` 包络，`data.entries` 为该目录条目（`name`/`isDir`/`size`/`mtime`）

#### Scenario: media 模式忽略 bundle_id

- **WHEN** 以 `root="media"` 调用任一 AFC 函数且 `bundle_id` 为空
- **THEN** 正常经 `com.apple.afc` 访问，不因 `bundle_id` 为空而报错

#### Scenario: 路径越界被拒绝

- **WHEN** `sub_path`/`remote_path` 含试图越过媒体分区根的 `..` 片段
- **THEN** 返回 `error` 包络，`error.kind` 为 `BAD_TARGET`，且不执行任何文件访问

#### Scenario: 受限目录访问失败

- **WHEN** 列举或写入媒体分区中系统受限/只读目录失败
- **THEN** 返回 `error` 包络，`error.message` 说明失败原因（不崩溃）

### Requirement: 媒体分区文件导入/导出/删除/新建/重命名

`afc_pull` / `afc_push` / `afc_rm` / `afc_mkdir` / `afc_rename` SHALL 在 `root="media"` 下提供与沙盒模式一致的语义：导出/导入支持文件与文件夹（递归），删除可作用于文件或目录，新建目录与重命名作用于媒体分区路径。导出 SHALL 保留文件字节与设备侧修改时间（`st_mtime`），导入 SHALL 按字节写入（不转码）。

#### Scenario: 导出媒体文件（保留元数据）

- **WHEN** 以 `root="media"` 调用 `afc_pull(...)` 且 `remote_path` 指向存在文件
- **THEN** 文件字节写入本地、修改时间同步设备侧 `st_mtime`，文件内嵌元数据（如 EXIF）原样保留，返回 `ok`

#### Scenario: 导入文件或文件夹到媒体分区

- **WHEN** 以 `root="media"` 调用 `afc_push(...)` 且 `local_path` 存在、`remote_dir` 合法
- **THEN** 文件写入 `remote_dir/<名>`、目录递归写入 `remote_dir/<目录名>`，返回 `ok`

#### Scenario: 删除媒体分区条目

- **WHEN** 以 `root="media"` 调用 `afc_rm(...)` 且 `remote_path` 指向存在的文件或目录
- **THEN** 该路径被删除，返回 `ok`

#### Scenario: 媒体分区新建目录与重命名

- **WHEN** 以 `root="media"` 调用 `afc_mkdir(...)` 或 `afc_rename(...)` 且路径合法
- **THEN** 目录被创建 / 路径被重命名，返回 `ok`

### Requirement: 按需读取文件字节（缩略图）

`executor_ios.toolkit_api` SHALL 提供 `afc_read(target, bundle_id, root, remote_path, max_bytes=None)`，经 AFC 读取并返回指定文件的字节内容，供 UI 生成缩略图等用途。`max_bytes` 非空时 SHALL 限制读取上限（超出则截断或拒绝），避免大文件造成内存峰值。

#### Scenario: 读取文件字节成功

- **WHEN** 调用 `afc_read(...)` 且 `remote_path` 指向存在的文件
- **THEN** 返回 `ok` 包络，`data` 含该文件字节（或受 `max_bytes` 限制的前缀）

#### Scenario: 读取目录或不存在路径

- **WHEN** `remote_path` 指向目录或不存在
- **THEN** 返回 `error` 包络，`error.message` 说明原因

#### Scenario: 超过字节上限

- **WHEN** 文件大小超过 `max_bytes`
- **THEN** 仅返回前 `max_bytes` 字节或返回明确的超限 `error`（实现需保证不一次性载入整文件）
