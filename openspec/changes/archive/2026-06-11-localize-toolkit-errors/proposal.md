## Why

`ios_toolkit` 是纯逻辑层，但其错误信封里的 `message` 字段被 UI 直接显示给用户，且部分 `message` 是硬编码中文。在 `en-US` 模式下，这些 toolkit 错误会以中文露出，破坏国际化一致性。逻辑层不应承担本地化职责——它只需回稳定的机器可读错误标识，由 UI 负责按标识渲染本地化文案。

## What Changes

- 在错误信封中引入稳定、细粒度的错误码 `error.code`（如 `DDI_NO_SOURCE`、`DDI_MOUNT_TIMEOUT`、`DVT_TUNNEL_REQUIRED`、`GPX_FILE_NOT_FOUND`…），与现有粗粒度 `error.kind` 并存；`kind` 保留为大类（`BAD_TARGET`/`TIMEOUT`/`SUBPROCESS`/…），`code` 唯一标识具体错误。
- 错误中的可变量（路径、`exc`、`family` 等）从拼进 `message` 改为放入结构化 `error.details`（如 `{"path": ...}`），供 UI 做具名占位符插值。
- `error.message` 退化为**英文调试详情**，仅用于日志 / tooltip / 兜底展示，不再作为面向用户的本地化文案来源。逻辑层 SHALL NOT 依赖任何 UI / i18n 模块（保持可 headless / CLI 运行）。
- UI 层新增「toolkit 错误本地化」机制：按 `error.code` 在 i18n catalog 的 `errors.*` 命名空间查模板，用 `details` 插值；缺映射时回退到 `kind` 级通用文案，再回退到 `message`。
- 迁移现有面向用户的 toolkit 错误（含全部硬编码中文 `_err` 与会上浮到 UI 的异常消息）到「稳定 code + details」形态，并在两份 catalog 补齐对应 `errors.*` 文案。

## Capabilities

### New Capabilities
- `slide6-error-localization`: UI 按 toolkit 返回的 `error.code` 渲染本地化错误文案的机制（映射、details 插值、多级回退）。

### Modified Capabilities
- `json-cli`: 失败响应格式新增稳定细粒度 `error.code` 字段，并约定 `message` 为英文调试详情、可变量入 `error.details`。

## Impact

- `ios_toolkit/toolkit_api.py`、`ios_toolkit/device.py`、`ios_toolkit/ddi_provider.py`：`_err(...)` / 上浮异常的标识从「`kind` + 中文 message」改为「`kind` + 稳定 `code` + 结构化 `details`，message 转英文」。
- `slide6_ui`：错误展示处（`status.setText(error.message)` 等）改为经本地化映射函数渲染；新增 `errors.*` catalog 命名空间（`zh-CN.json` / `en-US.json`）。
- 错误信封契约（`json-cli`）：消费方（含 executor 子进程协议）向后兼容——`kind` / `message` / `details` 保留，仅新增 `code`。
- 无新增第三方依赖。
