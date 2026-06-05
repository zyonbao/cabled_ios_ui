## Context

控制台分两端：

- slide6 桌面端（PySide6）：`slide6_console/main_window.py` 负责 UI 与设备生命周期，`slide6_console/keyboard.py` 提供 `KeyboardCapture`（QLineEdit 捕获宿主键盘）与 `KeyboardSender`（FIFO 串行发送）。
- web 端（FastAPI + 原生 JS）：`web_console/web_server.py` 暴露 `/api/*`，`web_console/web/{index.html,app.js}` 是单页 UI。

两端最终都复用 `executor_ios.toolkit_api`，再下沉到 `executor_ios.device.iOSDevice` 的 WDA HTTP 调用。现有相关能力：

- `send_keys(target, text)` → WDA `POST /session/{sid}/wda/keys`，向聚焦控件输入任意文本（含 IME 结果），已被键盘镜像使用。
- `key_event` / `key_chord` 处理编辑键、导航键、修饰组合键。
- `device._post_with_session_retry` / `_get_with_session_retry` 提供带 session 重建的 WDA 调用封装，是新增剪贴板能力的现成基座。

当前缺口正是用户提出的三点：slide6 键盘开启缺少就地输入框/退出入口、缺少独立「文本框 + 发送」、缺少剪贴板读写。

## Goals / Non-Goals

**Goals:**

- slide6 键盘镜像开启时就地替换为「捕获输入框 + 退出叉」，退出入口明确。
- 两端各提供独立「文本输入框 + 发送」，一次性向设备聚焦控件发送文本。
- 两端各提供 set/get 剪贴板：set 走确认/取消弹窗，get 走文本展示弹窗（非文本则提示且不可复制）。
- 底层新增 `get_pasteboard` / `set_pasteboard` 及 web 端点，复用现有 envelope 与 session 重试封装。

**Non-Goals:**

- 不改动 web 端键盘镜像（键盘捕获）交互。
- 不实现剪贴板的图片/富文本读写与预览（仅纯文本读写，非文本仅作提示）。
- 不实现 web 端读取展示窗口「禁止选中」（用户已说明可不做）。
- 不引入新的第三方依赖。

## Decisions

### 决策 1：剪贴板底层走 WDA `/wda/getPasteboard` 与 `/wda/setPasteboard`

WDA 提供 session 级 `POST /session/{sid}/wda/setPasteboard`（body `{"content": "<base64>", "contentType": "plaintext"}`）与 `POST /session/{sid}/wda/getPasteboard`（body `{"contentType": "plaintext"}`，`value` 返回 base64）。直接在 `iOSDevice` 上新增 `set_pasteboard` / `get_pasteboard`，复用 `_post_with_session_retry`，与现有 `send_keys` / `key_chord` 完全同构。

- 备选：通过 `idevicepasteboard` 等外部工具——需额外依赖、与现有 WDA 通道割裂，否决。
- `get_pasteboard` 返回 `{"text", "isText"}`：`plaintext` 读取若 base64 解码后为空或解码失败，置 `isText=false`，把「是否文本」的判定下沉到底层，UI 仅消费布尔值。

### 决策 2：文本发送复用 `send_keys`，不新增底层能力

「文本框 + 发送」与键盘镜像的文本输入语义一致（都是向聚焦控件输入文本），直接复用 `toolkit_api.send_keys`：

- web 端复用现有 `POST /api/type`（已是 `send_keys` 的封装），无需新端点；前端新增独立输入框与发送按钮，点击时入队/直接 POST。
- slide6 端复用 `KeyboardSender.enqueue_text`（串行 worker），或在已连接时直接 `runner.submit(api.send_keys, ...)`。优先经 `KeyboardSender` 以与镜像输入共用顺序保证。
- 选 `send_keys` 而非 `input_text`：`input_text` 禁止换行/单引号/反引号且限 1024 字节，约束更强；`send_keys` 上限 4096 字节且接受任意字符，更贴合「灌入一段文本」诉求。

### 决策 3：slide6 键盘开启「就地替换」用同位 widget 切换

在 `kbd_btn` 所在的 sidebar 行位置放一个容器，内部用两种形态切换：

- 关闭态：显示「键盘输入」按钮。
- 开启态：显示一行「`KeyboardCapture` 输入框 + 退出叉按钮（QPushButton）」。

实现上保留现有 `KeyboardCapture` 与 `KeyboardSender` 逻辑，仅调整布局与可见性切换（`_set_keyboard` 中切换两组 widget 的 `setVisible`）。退出叉点击 = `_set_keyboard(False)`。这样复用既有键盘信号/串行发送链路，改动面集中在 UI 装配。

- 备选：完全重写键盘捕获控件——无必要，否决。

### 决策 4：剪贴板/设置弹窗的两端实现方式

- slide6：set 用 `QInputDialog.getMultiLineText`（自带 OK/Cancel）或自定义 `QDialog`；get 用只读 `QPlainTextEdit` 放进 `QDialog`，文本态允许选中复制，非文本态显示提示标签且不放文本区。
- web：set 用一个模态层（输入 `<textarea>` + 确认/取消）；get 用模态层展示 `<pre>`/`<textarea readonly>` 文本，非文本显示提示文案。

## Risks / Trade-offs

- [WDA 剪贴板需前台] iOS 限制 `UIPasteboard` 仅在 App 前台时可访问，WDA Runner 在后台时 get/setPasteboard 永远返回空字符串（已由 Appium 官方文档与真机复现确认）→ 缓解：`set_pasteboard`/`get_pasteboard` 内部包一层「记录当前前台 app → 通过 `/wda/apps/launch` 把 WDA 切到前台并轮询 `activeAppInfo` 确认 → 执行读写 → 用记录的 bundleId 把原 app 切回前台」。系统剪贴板跨 app 持久，因此 GET 仍能读到用户在其它 app 复制的文本。代价是屏幕会短暂切到 WDA 再切回，属平台固有限制，无法完全消除。
- [iOS 16+「允许粘贴」弹窗] 读取其它 app 剪贴板会弹出系统「允许粘贴」弹窗，未处理前读取返回空 → 处理方式（按用户决定从简）：`get_pasteboard` 只单次读取、不重试、不自动接受弹窗；读到空即提示「剪贴板为空或为非文本内容」。由用户手动点按「允许粘贴」后再次点击读取即可。（曾尝试 `/alert/accept` 与按钮坐标点击自动接受，但该端点识别不到此 SpringBoard 系统弹窗、自动化点按不可靠，已移除。）
- [非文本判定不精确] 仅以 `plaintext` 读取结果是否可解码为非空文本来判断 `isText`，无法区分「真的是图片」与「剪贴板为空」 → 缓解：UI 文案用「非文本或空内容」式中性提示；后续如需精确判定可扩展按 `contentType=image` 二次探测（非本次目标）。
- [send_keys 需聚焦控件] 文本发送要求设备端已有聚焦输入框，否则文本无处落入 → 缓解：与现有键盘镜像同样依赖用户先点设备输入框；UI 提示沿用现有「先点设备输入框」说明。
- [base64 编解码一致性] set 用 UTF-8→base64，get 反向解码，需保证编码一致避免乱码 → 缓解：统一 UTF-8，并在单测中覆盖中文/emoji。
- [两端 UI 重复] set/get 弹窗在两端各实现一份 → 可接受：两端技术栈不同（Qt vs DOM），无共享 UI 层，重复成本低于强行抽象。

## Migration Plan

纯增量，无数据迁移。分层落地：先底层 `device`/`toolkit_api` 的 pasteboard + 单测，再 web 端点与前端，最后 slide6 UI。回滚即移除新增按钮/端点/方法，不影响既有能力。

## Open Questions

已确认的决策：

- 剪贴板读写：经真机验证，WDA 在后台时 get/set 永远失败（返回空）。原「不拉前台、仅提示」的方案会导致功能完全不可用，故**修订为**：读写时自动把 WDA 切到前台执行、完成后自动切回原前台 app（系统剪贴板跨 app 持久，GET 仍能读到其它 app 复制的内容）。
- get/set 两端均提供成功/失败状态提示；读取展示窗口提供「复制到本机」按钮。
- 文本发送：**发送成功后清空输入框**，发送失败则保留输入框内容以便重试。
