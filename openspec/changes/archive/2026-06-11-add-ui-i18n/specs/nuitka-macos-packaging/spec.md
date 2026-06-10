# nuitka-macos-packaging Specification

## ADDED Requirements

### Requirement: 打包纳入 UI 语言文件

Nuitka 打包 SHALL 将 `slide6_ui/languages/` 目录（语言 catalog JSON）随 `CablediOS.app` 一并打包，使冻结环境下国际化工具可正常加载各语言文案。所有打包入口（GUI 构建与合并构建）SHALL 一致包含该目录。

#### Scenario: 语言目录随 app 打包

- **WHEN** 执行 Nuitka 打包脚本
- **THEN** 每处 Nuitka 调用包含 `--include-data-dir=...slide6_ui/languages=slide6_ui/languages`
- **AND** 产出的 `CablediOS.app` 内存在 `slide6_ui/languages/zh-CN.json` 与 `en-US.json`

#### Scenario: 冻结环境英文文案可加载

- **WHEN** 在打包后的 app 中将语言设为 `en-US` 并重启
- **THEN** 国际化工具成功加载 `en-US` catalog，界面以英文展示
