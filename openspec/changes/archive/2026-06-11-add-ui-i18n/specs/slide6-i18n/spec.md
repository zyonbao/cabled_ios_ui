# slide6-i18n Specification

## ADDED Requirements

### Requirement: 语言 catalog 与目录结构

桌面端 SHALL 在 `slide6_ui/languages/` 目录下为每种受支持语言提供一份 JSON catalog 文件，文件名以语言标签命名（`zh-CN.json`、`en-US.json`）。catalog SHALL 采用嵌套结构，叶子值为展示文案模板；`zh-CN.json` SHALL 为全集（事实上的 key 清单来源），`en-US.json` SHALL 与之 key 集合一致（同构）。

#### Scenario: 提供两种语言 catalog

- **WHEN** 应用构建/运行
- **THEN** `slide6_ui/languages/` 下存在 `zh-CN.json` 与 `en-US.json`
- **AND** 两文件展平后的 key 集合一致

#### Scenario: 嵌套语义 key

- **WHEN** 访问某条文案
- **THEN** 通过点路径语义 key（如 `dev_tools.ddi.mounted`）取值，顶层命名空间按模块/功能划分

### Requirement: 国际化工具与启动期语言选定

桌面端 SHALL 提供国际化工具 `slide6_ui/i18n.py`，在应用启动期（`QApplication` 创建后、构建任何窗口前）初始化一次。语言解析顺序 SHALL 为：显式入参 > `QSettings` 键 `settings/language` > 默认 `zh-CN`；工具 SHALL 仅接受 `zh-CN` / `en-US`，非法或缺失值回退 `zh-CN`。语言选定 SHALL 为重启生效，不在运行时动态 retranslate。

#### Scenario: 默认语言为 zh-CN

- **WHEN** `settings/language` 未设置
- **THEN** 工具加载 `zh-CN` catalog

#### Scenario: 按设置选定语言

- **WHEN** `settings/language` 为 `en-US`
- **THEN** 工具加载 `en-US` catalog，UI 文案以英文展示

#### Scenario: 非法语言值回退

- **WHEN** `settings/language` 为不受支持的值
- **THEN** 工具回退加载 `zh-CN`，不抛异常

### Requirement: 取值 API、回退与占位符插值

国际化工具 SHALL 提供取值函数 `t(key, **kwargs)`：返回当前语言对应模板；当前语言缺失该 key 时回退 `zh-CN`；仍缺失时返回 key 本身。当传入 `kwargs` 时 SHALL 以具名占位符 `{name}` 执行 `format(**kwargs)`；当格式化失败（占位符不匹配/缺参）时 SHALL 记录 warning 并返回未格式化模板，不得使应用崩溃。

#### Scenario: 取当前语言文案

- **WHEN** 调用 `t("dev_tools.ddi.mounted")` 且当前语言存在该 key
- **THEN** 返回当前语言对应文案

#### Scenario: 缺失 key 回退

- **WHEN** 当前语言（如 en-US）缺失某 key 而 zh-CN 存在
- **THEN** 返回 zh-CN 对应文案；若两者都缺失则原样返回 key

#### Scenario: 具名占位符插值

- **WHEN** 调用 `t("dev_tools.ddi.mount_ok", target="00008…")`
- **THEN** 模板中的 `{target}` 被替换为实参值

#### Scenario: 占位符不匹配时降级

- **WHEN** 格式化因占位符/参数不匹配失败
- **THEN** 记录 warning 并返回未格式化模板，应用不崩溃

### Requirement: 展示文案统一经由工具取值

`slide6_ui` 下所有面向用户的展示文案 SHALL 经由 `t(...)` 取值，不得保留硬编码中文展示字符串；原 f-string 插值文案 SHALL 改写为「catalog 模板 + 具名占位符 + `t(key, **kwargs)` 格式化」。

#### Scenario: 无硬编码展示中文

- **WHEN** 审视 `slide6_ui` 展示层代码
- **THEN** 面向用户的文案均通过 `t(...)` 取值（toolkit 层文案为本能力范围外的已知例外）

#### Scenario: key 完整性可校验

- **WHEN** 运行 key 完整性校验
- **THEN** 报告 `zh-CN` 与 `en-US` 之间缺失/多余的 key

#### Scenario: 占位符名一致性可校验

- **WHEN** 运行校验
- **THEN** 对每个共有 key 比对两份模板的具名占位符集合，报告不一致（如一侧 `{target}` 另一侧 `{device}` 或漏写占位符）
