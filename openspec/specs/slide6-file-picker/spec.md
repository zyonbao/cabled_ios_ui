# slide6-file-picker Specification

## Purpose
定义文件/目录选择体验的一致性规范：系统选择器与应用内置选择器的切换开关、路径跳转栏样式统一、长路径显示策略及相关设置文案约束。
## Requirements
### Requirement: 统一的本地文件/文件夹选取入口

桌面应用所有本地文件/文件夹选取 SHALL 统一收口到单一模块（`slide6_ui/common/file_dialogs.py`），并对外仅暴露四个 helper：选取单个已存在文件、选取多个已存在文件、保存文件、选取目录。各功能页（安装 IPA、安装描述文件、挂载 DDI 选镜像、AFC 导入/导出、截图与日志保存、oslog 导出、相册导出、崩溃导出、GPX 选择等）SHALL 通过这些 helper 进行选取，SHALL NOT 直接调用 `QFileDialog` 静态方法。

#### Scenario: 各入口走统一 helper

- **WHEN** 任一功能页需要选取本地文件或文件夹
- **THEN** 通过统一模块的 helper 完成选取，模块外不存在对 `QFileDialog` 的直接调用

#### Scenario: 取消选取

- **WHEN** 用户在选取对话框中点击取消
- **THEN** helper 返回空结果（单选/保存返回空字符串，多选返回空列表），调用方按"未选择"处理

### Requirement: 系统/内置选择器的全局切换

选择使用系统原生选择器还是应用内置选择器 SHALL 由持久化偏好 `settings/use_builtin_file_dialog` 决定（默认 `False`，即系统原生）。该偏好 SHALL 在每次弹窗时即时读取，使变更立即生效且无需重启。

#### Scenario: 默认使用系统原生选择器

- **WHEN** 用户从未修改该偏好
- **THEN** 所有选取走系统原生面板

#### Scenario: 开启内置后即时生效

- **WHEN** 用户开启「使用应用内置的文件/文件夹选择器」
- **THEN** 后续任一次选取改用应用内置选择器，无需重启应用

### Requirement: 应用内置带路径栏选择器

应用内置选择器 SHALL 为同一个带可编辑"路径跳转栏"的对话框，并覆盖打开单文件、打开多文件、保存文件、选取目录四种用途。路径栏 SHALL 在用户浏览目录时同步当前路径，并允许粘贴/输入绝对的文件或目录路径后回车跳转；对长路径 SHALL 显示路径头部而非尾部。

#### Scenario: 路径栏跳转目录

- **WHEN** 用户在路径栏输入一个存在的目录路径并回车
- **THEN** 选择器导航进入该目录

#### Scenario: 长路径显示头部

- **WHEN** 路径长度超过路径栏可见宽度
- **THEN** 路径栏显示路径的起始部分（如 `/Applications/Xcode.app/Contents/...`），而非结尾部分

#### Scenario: 保存时预填文件名

- **WHEN** 用户在保存用途下于路径栏输入一个尚不存在的目标路径并回车
- **THEN** 选择器跳到其父目录并在文件名字段预填该文件名，由用户确认保存

