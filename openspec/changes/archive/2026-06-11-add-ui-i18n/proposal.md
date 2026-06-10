# 桌面端 UI 国际化（i18n）：zh-CN / en-US

## Why

`slide6_ui` 桌面端目前所有展示文案都是硬编码的简体中文（约 616 条字符串、散布在 20 个文件中），无法面向英文用户。需要引入一套轻量的国际化机制：启动时按设置选定语言，所有展示字符串改为按 key 从语言文件中取值，先支持 `zh-CN` / `en-US` 两种语言。

考虑到本项目所有交互均为「重启生效」（语言切换不需要运行时 retranslate），不引入 Qt 的 `QTranslator` / `.ts` / `.qm` 工具链，而是用一套基于语义 key 的 JSON catalog + 单例工具，改造成本最低、可读性最好。

## What Changes

- 新增 `slide6_ui/languages/` 目录，存放 `zh-CN.json` / `en-US.json` 两个语言 catalog（嵌套语义 key，例如 `dev_tools.ddi.mounted`）。
- 新增 `slide6_ui/i18n.py` 国际化工具：启动时按 `settings/language` 选定语言并加载对应 catalog，提供 `t(key, **kwargs)` 取值（缺失 key 回退到 `zh-CN`，仍缺失则原样返回 key），支持 `{占位符}` 插值。
- Settings/General 新增「语言」下拉（`简体中文` / `English`），切换后写入 `settings/language` 并弹「重启生效」提示。默认固定 `zh-CN`，由用户手动切换到 `en-US`。
- 将 `slide6_ui` 下所有展示用硬编码中文字符串替换为 `t(...)` 调用；带 f-string 插值的文案改写为「模板 key + `{占位符}` + 格式化参数」形式。
- 打包脚本（`packaging/build_macos_app.sh` 两处 Nuitka 调用）新增 `--include-data-dir=slide6_ui/languages=slide6_ui/languages`，确保语言文件随 app 打包。

## Impact

- Affected specs: 新增 `slide6-i18n`（国际化机制：catalog 结构、语言选定与持久化、取值与回退、占位符插值）；`slide6-settings-window`（General 新增语言下拉）；`nuitka-macos-packaging`（打包纳入 languages 目录）。
- Affected code: 新增 `slide6_ui/i18n.py`、`slide6_ui/languages/{zh-CN,en-US}.json`；改造 `slide6_ui` 下 20 个含展示文案的文件；`slide6_ui/main_window.py`（语言下拉 + 启动初始化）；`packaging/build_macos_app.sh`。
- **范围边界**：本次仅覆盖 `slide6_ui` 展示文案。`ios_toolkit/toolkit_api` 层返回的中文用户可见错误文案（如状态栏「查询 DDI 状态超时」）本次**不翻译**，作为已知限制后续单独处理。
- 无新增第三方依赖（JSON 用标准库）。
- 风险点：f-string 插值改写的正确性（参数遗漏 / 占位符不匹配），以及个别动态拼接文案需要重构为带参模板；通过逐文件迁移 + 启动期校验脚本（key 完整性对齐）降低风险。
