## Context

`ios_toolkit` 通过统一信封返回结果：成功 `{"ok": True, "data": {...}}`，失败 `{"ok": False, "error": {"kind", "message", "details"}}`（见 `toolkit_api._err`）。UI 在展示失败时普遍直接取 `error.message`（如 `status.setText(result["error"]["message"])`），因此逻辑层产生的 `message` 实际承担了展示职责，且其中含硬编码中文（如「没有可用的 DDI 来源…」「请先启动 XPC tunnel…」）。

现有 `kind` 只有少数大类（`BAD_TARGET` / `TIMEOUT` / `SUBPROCESS` / `NOT_IMPLEMENTED` / `INTERNAL` / `LOG_ARCHIVE_FAILED`…），且高度复用——同一个 `TIMEOUT` 覆盖「查 DDI 状态超时 / 等 DVT 就绪超时 / 查 RSD 超时 / 挂载超时 / 卸载超时」等多种语义。仅凭 `kind`，UI 无法区分并给出对应文案。

约束：
- `ios_toolkit` 须可 headless / CLI（`toolkit_cli.py`）与子进程（executor 协议）运行，**不得依赖 `slide6_ui` 或其 i18n / QSettings**。
- 错误信封是跨进程契约（`json-cli`），改动须向后兼容。
- 本地化已有基础设施：`slide6_ui/i18n.py` 的 `t(key, **kwargs)` 与 `languages/*.json`。

## Goals / Non-Goals

**Goals:**
- 让 UI 能按稳定标识渲染本地化的 toolkit 错误文案，`en-US` 下不再露出中文。
- 逻辑层零 i18n：只回稳定细粒度 `code` + 结构化 `details`，`message` 为英文调试详情。
- 错误信封向后兼容（新增字段，不破坏既有 `kind` / `message` / `details` 消费方）。

**Non-Goals:**
- 不为 toolkit 增加运行时语言/locale 概念，不在 toolkit 内做任何翻译。
- 不追求穷尽 toolkit 全部内部异常文案的本地化；只覆盖会上浮到 UI 展示的错误（其余罕见诊断文本保留英文，作为 `message` 调试详情即可）。
- 不改变错误的触发逻辑、退出码语义或成功路径。

## Decisions

### 决策 1：新增稳定细粒度 `error.code`，与 `kind` 并存

错误信封扩展为：

```json
{ "ok": false,
  "error": {
    "kind": "TIMEOUT",                 // 既有大类，保留
    "code": "DDI_MOUNT_TIMEOUT",        // 新增：稳定、唯一、细粒度
    "message": "Mounting DDI timed out (image upload stalled)",  // 英文调试详情
    "details": { "family": "personalized" }  // 结构化可变量
  } }
```

- `code` 为大写蛇形、全局唯一的稳定字符串，是 UI 映射与排障的主键。
- `kind` 不变（向后兼容，且作为 UI 的兜底分组）。
- `_err()` 签名扩展为 `_err(kind, message, details=None, code=None)`；未提供 `code` 时该错误暂归类到 `kind` 级通用文案（渐进迁移友好）。

**备选**：把 `code` 塞进 `details.code`。否决——`code` 是错误的一等标识，放顶层 `error.code` 更清晰、便于契约校验与日志检索。

### 决策 2：可变量入 `details`，`message` 转英文

原 f-string（`f"GPX 文件不存在: {path}"`、`f"未知的 DDI 类型：{family}"`）拆为：英文 `message`（`"GPX file not found"`）+ `details`（`{"path": path}` / `{"family": family}`）。UI 用 `details` 做具名占位符插值，与 `add-ui-i18n` 既定的「具名占位符」约定一致。

### 决策 3：UI 侧本地化映射 + 多级回退

UI 新增一个纯函数（建议 `slide6_ui/common/errors.py: localize_error(error: dict) -> str`）：

1. 若 `error.code` 在 catalog `errors.<code>` 命中 → `t("errors.<code>", **error["details"])`；
2. 否则若 `errors.kind.<kind>` 命中 → 该 `kind` 级通用文案；
3. 否则回退 `error.message`（英文调试详情）；
4. `error` 缺失/非 dict → 通用「未知错误 / Unknown error」。

catalog 新增顶层命名空间 `errors`：`errors.<CODE>`（细粒度）与 `errors.kind.<KIND>`（兜底）。占位符名须与 `details` 字段名一致，并通过既有 `i18n.validate()` 的占位符一致性校验覆盖。

**备选**：UI 直接对 `message` 文本做查表翻译。否决——脆弱（文案一改即失配），且无法处理插值。

### 决策 4：调用点改造范围以「是否上浮 UI」为界

优先迁移当前硬编码中文的 `_err`（DDI 来源/挂载/卸载、DVT/tunnel、虚拟定位、GPX、logarchive 等）与会被 UI 以 `str(exc)` 展示的上浮异常。纯内部、仅日志的英文消息可不分配 `code`（走 `kind` 兜底或保留 message）。

### 错误码初稿（迁移现有中文错误）

| code | kind | details | 场景 |
|---|---|---|---|
| `DDI_NO_SOURCE` | SUBPROCESS | — | 没有可用的 DDI 来源 |
| `DDI_STATUS_TIMEOUT` | TIMEOUT | — | 查询 DDI 状态超时 |
| `DVT_READY_TIMEOUT` | TIMEOUT | — | 等待 DVT 就绪超时 |
| `RSD_QUERY_TIMEOUT` | TIMEOUT | — | 查询 RSD 服务超时 |
| `DDI_MOUNT_TIMEOUT` | TIMEOUT | — | 挂载 DDI 超时 |
| `DDI_UNMOUNT_TIMEOUT` | TIMEOUT | — | 卸载 DDI 超时 |
| `DDI_IMAGE_MISSING` | BAD_TARGET | — | 缺少镜像文件 (image) |
| `DDI_PERSONALIZED_ARGS_MISSING` | BAD_TARGET | — | personalized 挂载缺组件 |
| `DDI_DEVELOPER_ARGS_MISSING` | BAD_TARGET | — | developer 挂载缺 image/signature |
| `DDI_UNKNOWN_FAMILY` | BAD_TARGET | `family` | 未知的 DDI 类型 |
| `DEVELOPER_MODE_OFF` | — | — | 开发者模式未开启 |
| `TUNNEL_REQUIRED` | — | — | 需先启动 XPC tunnel |
| `LOCATION_START_TIMEOUT` | SUBPROCESS | — | 启动虚拟定位超时 |
| `GPX_FILE_NOT_FOUND` | BAD_TARGET | `path` | GPX 文件不存在 |
| `GPX_PARSE_FAILED` | SUBPROCESS | `exc` | 解析 GPX 失败 |
| `GPX_NO_TRACKPOINTS` | BAD_TARGET | — | GPX 无可用轨迹点 |
| `LOG_ARCHIVE_FAILED` | LOG_ARCHIVE_FAILED | `exc` | 收集 logarchive 失败 |

（实施时以代码实际枚举为准，可微调；`kind` 列空白表示沿用调用点既有大类。）

## Risks / Trade-offs

- [一处错误既改 toolkit 又改 UI，易遗漏映射] → UI 多级回退保证「未映射 code」仍显示 `message`（英文）而非崩溃或空白；`i18n.validate()` 覆盖占位符一致性；迁移以表为清单逐条核对。
- [`message` 转英文后，未迁移 UI 的旧展示点会从中文变英文] → 展示点集中改造为 `localize_error(...)`；改造前后用 grep 核对所有 `error""].get("message")` / `["message"]` 读取处。
- [executor 子进程/外部消费方依赖 message 文案] → 仅新增 `code`，`kind`/`message`/`details` 语义不变；`message` 本就标注为 human-readable，不构成契约破坏。
- [details 字段名与占位符不一致导致插值失败] → `t()` 失败降级返回未格式化模板（不崩溃）+ `i18n.validate()` 占位符一致性兜底。

## Migration Plan

1. 扩展 `_err` 支持 `code`，错误信封文档（`json-cli`）补 `code` 字段。
2. 按错误码表逐个改造 toolkit 调用点：分配 `code`、message 转英文、可变量入 `details`。
3. UI 新增 `localize_error()` + `errors.*` catalog（两语言），将展示点改为经其渲染。
4. 跑 `i18n.validate()`、导入冒烟、grep 残留中文 `_err`、核对 UI 读取 `message` 的点已改造。

回滚：UI 展示点可整体回退为直接读 `message`；toolkit 的 `code`/details 为附加字段，保留无副作用。

## Open Questions

- 暂无（错误码表可在实施中按实际代码微调，不阻塞设计）。
