# app-file-transfer-op Specification

## Purpose
TBD - created by archiving change add-app-list-and-file-manager. Update Purpose after archive.
## Requirements
### Requirement: 浏览 App 文件目录

`executor_ios.toolkit_api` SHALL 提供 `afc_list(target, bundle_id, root, sub_path)`，通过 `HouseArrestService` 建立对指定 App 的 AFC 访问并列出 `sub_path` 目录条目。`root` 取值 `documents` 时使用 `VendDocuments`，取值 `container` 时使用 `VendContainer`。两种模式下 AFC 根均位于容器根，因此用户可见的逻辑路径（根为 `/`）在 `documents` 模式下 SHALL 映射到设备侧 `/Documents`、在 `container` 模式下映射到 `/`。每个条目至少包含 `name`、`isDir`、`size`、`mtime`。

#### Scenario: 列出 Documents 目录（fileSharing App）

- **WHEN** 对开启文件共享的 App 调用 `afc_list(target, bundle_id, "documents", sub_path)`
- **THEN** 返回 `ok` 包络，`data.entries` 为该目录条目列表

#### Scenario: 列出沙盒容器目录（沙盒可访问 App）

- **WHEN** 对带 `get-task-allow` 的 App 调用 `afc_list(target, bundle_id, "container", sub_path)`
- **THEN** 返回 `ok` 包络，`data.entries` 为容器内该目录条目列表

#### Scenario: 容器不可访问

- **WHEN** 对不具备沙盒访问权限的 App 请求 `root="container"`
- **THEN** 返回 `error` 包络，`error.message` 说明该 App 沙盒不可访问

#### Scenario: 路径越界被拒绝

- **WHEN** `sub_path` 含 `..` 等试图越过所选 `root` 根目录的片段
- **THEN** 返回 `error` 包络，`error.kind` 为 `BAD_TARGET`，且不执行任何文件访问

### Requirement: 导出（pull）设备文件或目录到本地

`executor_ios.toolkit_api` SHALL 提供 `afc_pull(target, bundle_id, root, remote_path, local_path)`，将设备侧文件或目录读取并写入本地。导出文件时 `local_path` 为目标文件全路径；导出目录时 `local_path` 为目标**父目录**，pull SHALL 在其下递归重建以 `remote_path` 末段命名的目录。

#### Scenario: 导出文件成功

- **WHEN** 调用 `afc_pull(...)` 且 `remote_path` 指向一个存在的文件
- **THEN** 文件内容写入 `local_path`，返回 `ok` 包络

#### Scenario: 导出目录成功

- **WHEN** 调用 `afc_pull(...)` 且 `remote_path` 指向一个目录、`local_path` 为存在的本地父目录
- **THEN** 该目录及其内容被递归写入 `local_path/<目录名>`，返回 `ok` 包络

#### Scenario: 远端路径不存在

- **WHEN** `remote_path` 在设备侧不存在
- **THEN** 返回 `error` 包络，`error.message` 说明路径不存在

### Requirement: 导入（push）本地文件或目录到设备

`executor_ios.toolkit_api` SHALL 提供 `afc_push(target, bundle_id, root, local_path, remote_dir)`，将本地文件或目录写入设备侧 `remote_dir` 目录。文件写入为 `remote_dir/<文件名>`；目录递归复制为 `remote_dir/<目录名>`。

#### Scenario: 导入文件成功

- **WHEN** 调用 `afc_push(...)` 且 `local_path` 为存在文件、`remote_dir` 在所选 root 下合法
- **THEN** 文件被写入设备侧 `remote_dir`，返回 `ok` 包络

#### Scenario: 导入目录成功

- **WHEN** 调用 `afc_push(...)` 且 `local_path` 为存在目录、`remote_dir` 在所选 root 下合法
- **THEN** 该目录及其内容被递归写入设备侧 `remote_dir/<目录名>`，返回 `ok` 包络

#### Scenario: 本地路径无效

- **WHEN** `local_path` 不存在
- **THEN** 返回 `error` 包络，`error.kind` 为 `BAD_TARGET`，且不向设备写入

### Requirement: 删除、新建目录与重命名

`executor_ios.toolkit_api` SHALL 提供 `afc_rm(target, bundle_id, root, remote_path)`、`afc_mkdir(target, bundle_id, root, remote_dir)` 与 `afc_rename(target, bundle_id, root, remote_path, new_path)`，分别用于删除设备侧文件/目录、创建目录与重命名（移动）文件/目录。

#### Scenario: 删除文件

- **WHEN** 调用 `afc_rm(...)` 且 `remote_path` 指向存在的文件或目录
- **THEN** 该路径被删除，返回 `ok` 包络

#### Scenario: 新建目录

- **WHEN** 调用 `afc_mkdir(...)` 且 `remote_dir` 在所选 root 下合法
- **THEN** 目录被创建，返回 `ok` 包络

#### Scenario: 重命名文件或目录

- **WHEN** 调用 `afc_rename(...)` 且 `remote_path` 存在、`new_path` 在所选 root 下合法
- **THEN** 该路径被重命名（或移动）为 `new_path`，返回 `ok` 包络

#### Scenario: 拒绝重命名根目录

- **WHEN** `remote_path` 或 `new_path` 解析后为所选 root 的根 `/`
- **THEN** 返回 `error` 包络，`error.kind` 为 `BAD_TARGET`，且不执行任何操作

