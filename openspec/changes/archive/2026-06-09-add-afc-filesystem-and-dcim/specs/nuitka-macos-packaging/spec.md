## ADDED Requirements

### Requirement: 冻结环境下 HEIC/HEIF 解码依赖完整可用

打包脚本 SHALL 显式包含 `pillow-heif`（及其自带的 `_pillow_heif` 原生扩展与 `libheif` 动态库）与 `PIL`，使「相册」Tab 在未安装 Python 与依赖的 macOS 上仍能解码 HEIC/HEIF 原图（不依赖 Qt 的 heif 插件）。打包脚本 SHALL 在预检阶段校验构建环境已安装 `pillow-heif`，缺失时以非零状态退出并打印修复提示。

#### Scenario: 打包后 App bundle 内含 pillow-heif 与 libheif

- **WHEN** 打包脚本成功完成
- **THEN** `CablediOS.app/Contents/MacOS/` 下存在 `_pillow_heif` 原生扩展与其依赖的 `libheif` 动态库，`PIL` 包亦随产物分发

#### Scenario: 冻结 App 中查看 HEIC 照片

- **WHEN** 在冻结的 `CablediOS.app` 中进入「相册」Tab 并查看一张 HEIC 照片
- **THEN** 应用经 `pillow-heif` 解码并显示，不因原生扩展或 `libheif` 缺失而失败

#### Scenario: 构建环境缺少 pillow-heif 时给出明确报错

- **WHEN** 执行打包脚本但构建环境未安装 `pillow-heif`
- **THEN** 脚本在预检阶段以非零状态退出并打印缺失项与修复提示，不产出半成品 App
