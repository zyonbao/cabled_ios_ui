## Purpose

定义 `slide6_ui` 如何把 `ios_toolkit` 返回的「逻辑层无 i18n」错误信封本地化为面向用户的展示文案：UI 依据稳定的 `error.code`（及 `error.details`）在 i18n catalog 的 `errors.*` 命名空间取模板渲染，逻辑层不参与本地化。
## Requirements
### Requirement: 按错误码渲染本地化错误文案

UI SHALL 提供统一的 toolkit 错误本地化入口（如 `slide6_ui/common/errors.localize_error(error)`），将 toolkit 返回的错误信封 `error`（含 `kind` / `code` / `message` / `details`）渲染为当前语言的展示文案。逻辑层 SHALL NOT 参与该本地化；UI SHALL 依据稳定的 `error.code` 在 i18n catalog 的 `errors.*` 命名空间取模板，并以 `error.details` 作为具名占位符实参插值。

#### Scenario: 按 code 取本地化文案

- **WHEN** `error.code` 在 catalog 中存在对应 `errors.<code>` 模板
- **THEN** 返回当前语言文案，并用 `error.details` 中的字段做具名占位符插值

#### Scenario: 含可变量的错误文案插值

- **WHEN** 渲染携带 `details`（如 `{"path": "/x.gpx"}`）的错误
- **THEN** 模板中的 `{path}` 等具名占位符被 `details` 对应值替换

### Requirement: 错误本地化的多级回退

错误本地化 SHALL 具备多级回退，保证任意错误都能给出可读文案且不致崩溃：当 `errors.<code>` 缺失时回退到 `kind` 级通用文案 `errors.kind.<kind>`；仍缺失时回退到 `error.message`（英文调试详情）；当 `error` 缺失或非对象时返回通用「未知错误」文案。

#### Scenario: 未映射 code 回退到 kind 级文案

- **WHEN** `error.code` 无对应 `errors.<code>` 模板，但其 `kind` 有 `errors.kind.<kind>`
- **THEN** 返回该 `kind` 级通用本地化文案

#### Scenario: 无任何映射时回退到 message

- **WHEN** `code` 与 `kind` 均无对应模板
- **THEN** 返回 `error.message`（英文调试详情），不抛异常

#### Scenario: 错误信封缺失时的兜底

- **WHEN** 传入的 `error` 缺失或非对象
- **THEN** 返回通用「未知错误 / Unknown error」本地化文案

### Requirement: 展示层统一经由本地化入口呈现 toolkit 错误

`slide6_ui` 中所有向用户展示 toolkit 失败信息的位置 SHALL 经由该本地化入口渲染，SHALL NOT 直接展示 `error.message` 原文作为面向用户的主文案。

#### Scenario: 展示点不直接使用原始 message

- **WHEN** 审视 UI 中展示 toolkit 错误的代码
- **THEN** 均经本地化入口渲染（`error.message` 仅作回退或 tooltip / 日志用途）
