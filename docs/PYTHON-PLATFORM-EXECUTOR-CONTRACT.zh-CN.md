# Studio 平台 Python 执行器统一协议

这份文档是发给各平台实现同学的。

目标不是让大家各写一套随意的 Python 脚本，而是让：

1. 各平台都用 Python 实现底层“手和眼”
2. Studio 后续能统一整合
3. chat / explorer / executor 最终都复用同一套平台能力

这份文档是 **Python 实现协议**。  
上层语义和验收要求，请同时阅读：

- `CONTRACT.md`
- `PLATFORM-ACCEPTANCE.md`
- `PLATFORM-SUBMISSION-TEMPLATE.zh-CN.md`

---

## 1. 设计目标

每个平台都要提供同一组基础能力：

- `list_targets`
- `screenshot`
- `dump_ui`
- `tap`
- `swipe`
- `input_text`
- `key_event`
- `launch_app`
- `kill_app`
- `switch_app_env`
- `type_credential`

这些能力会被两类上层复用：

1. **探索 / 对话 / Explorer**
   - 模型探索设备
   - 截图、读 UI、点击、输入

2. **Executor**
   - 真正执行 case primitive
   - 最终也应尽量复用同一套平台实现

所以规范不是“只给 Rust broker 调一次”的零散 helper，而是：

- 一套共享 Python 平台库
- 一套一次性 JSON CLI
- 一个可选的 NDJSON executor 入口

---

## 2. 推荐目录结构

每个平台统一放在：

```text
studio/src-tauri/vendor/runtime/executor_<platform>/
```

例如：

```text
executor_android/
executor_ios/
executor_macos/
executor_windows/
executor_web/
```

每个平台目录建议至少包含：

```text
executor_<platform>/
  __init__.py
  toolkit_api.py
  toolkit_cli.py
  main.py
  secrets.py                # 如果需要凭据能力
  README.md
```

说明：

- `toolkit_api.py`
  - 放真正的平台能力实现
  - explorer / broker / executor 都应尽量复用这里
- `toolkit_cli.py`
  - 一次性 JSON stdin/stdout 协议
  - 给 Studio broker 调用
- `main.py`
  - 可选，但推荐
  - 如果平台要支持本地 executor，就按现有 NDJSON contract 实现
- `secrets.py`
  - 可选
  - 只在实现 `type_credential` 时使用

---

## 3. 强制约束

### 3.1 不允许每个平台自定义协议

所有平台必须：

- 使用相同操作名
- 使用相同 JSON 基本结构
- 使用相同错误分类
- 使用相同 selector 字段
- 使用相同截图 / 坐标语义

### 3.2 不要把平台差异暴露给上层

例如这些差异，必须在平台实现内部消化：

- Retina / 高 DPI
- 浏览器 zoom
- 多显示器偏移
- viewport 坐标和 screen-space 坐标转换
- 原生 UI 树差异

上层只认统一 contract，不学平台特例。

### 3.3 明文凭据不能离开 Python helper

`type_credential` 必须只接收：

- `env`
- `role`
- `field`

不能接收明文 `username` / `password`。

明文只允许出现在：

- Python helper 进程内存
- 必要的平台输入通道

不能出现在：

- Rust 日志
- HTTP body
- MCP transcript
- stdout
- stderr
- 命令行参数

---

## 4. 实现分层

建议统一成三层：

### 第 1 层：共享 Python API

这是必做的。

`toolkit_api.py` 里暴露统一函数，例如：

```python
def list_targets() -> dict: ...
def screenshot(target: str) -> dict: ...
def dump_ui(target: str) -> dict: ...
def tap(target: str, x: int, y: int) -> dict: ...
def swipe(target: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 250) -> dict: ...
def input_text(target: str, text: str) -> dict: ...
def key_event(target: str, key: str) -> dict: ...
def launch_app(target: str, package: str, activity: str | None = None) -> dict: ...
def kill_app(target: str, package: str) -> dict: ...
def switch_app_env(target: str, env: str) -> dict: ...
def type_credential(target: str, env: str, role: str, field: str, skip_clear: bool = False) -> dict: ...
```

这些函数的返回值，必须是“结构化 dict”，不要直接 print。

### 第 2 层：一次性 JSON CLI

这是必做的。

`toolkit_cli.py` 作为 Studio broker 的统一入口。

调用方式建议固定为：

```bash
python3 -B -m executor_<platform>.toolkit_cli
```

协议：

- 从 `stdin` 读取一个 JSON 请求
- 往 `stdout` 输出一个 JSON 响应
- 进程执行完后退出

为什么这样定：

- 避免命令行参数泄密
- 避免 shell escaping 麻烦
- 所有平台调用方式一致

### 第 3 层：NDJSON executor

这是推荐做法，不是平台接入第一阶段的强制项。

如果平台要支持本地 run / cloud run executor，
则 `main.py` 应遵守：

- ~~`executor-north-bound-contract.md`~~ <!-- WillNotDo: 当前不实现 executor，此 contract 暂不适用。链接指向仓库内部路径，无法外部访问。-->
  > **名称推断**："north-bound contract" 在系统架构中指下层组件向上层（broker / Studio）暴露的接口协议。该文件大概率定义了以下内容：
  > - executor 启动后如何向 broker 声明就绪（handshake / `ready` 消息）
  > - NDJSON 消息的类型枚举（`request`、`result`、`error`、`heartbeat` 等）
  > - 请求超时与优雅退出的生命周期约定
  > - 错误码与错误格式规范
  >
  > 如果后续需要实现 executor，应以该文件为准，而非本文档的推断。

并且：

- `main.py` 不要重复实现平台操作
- 应优先调用 `toolkit_api.py`

这样 explorer 和 executor 才不会各写一套。

---

## 5. 一次性 JSON CLI 协议

这部分是最关键的。

## 5.1 启动方式

统一要求：

```bash
python3 -B -m executor_<platform>.toolkit_cli
```

要求：

- 不依赖交互式输入
- 不写多行 stdout
- `stdout` 只输出一个完整 JSON 对象
- `stderr` 可写调试日志，但不能泄密

## 5.2 stdin 请求格式

请求统一是一个 JSON 对象：

```json
{
  "op": "dump_ui",
  "requestId": "optional-request-id",
  "deadlineMs": 15000,
  "args": {
    "target": "emulator-5554"
  }
}
```

字段说明：

- `op`
  - 必填
  - 操作名
- `requestId`
  - 可选
  - 原样回传，方便上层排障
- `deadlineMs`
  - 可选
  - 超时上限，默认 15000
- `args`
  - 必填
  - 操作参数对象

## 5.3 stdout 响应格式

成功：

```json
{
  "ok": true,
  "requestId": "optional-request-id",
  "data": {}
}
```

失败：

```json
{
  "ok": false,
  "requestId": "optional-request-id",
  "error": {
    "kind": "BAD_TARGET",
    "message": "target not found",
    "details": {}
  }
}
```

要求：

- 成功时返回 `ok: true`
- 失败时返回 `ok: false`
- `data` 和 `error` 二选一
- 不要在 `stdout` 混入额外日志

## 5.4 退出码约定

建议统一：

- `0`：请求已处理，具体成功失败看 JSON 的 `ok`
- `2`：输入 JSON 非法或参数缺失
- `3`：平台运行时未安装 / 环境不满足
- `4`：内部子进程失败
- `5`：执行器内部异常

说明：

- 上层仍然以 `stdout` JSON 为主
- 退出码主要用于调试和兜底

---

## 6. 操作名与参数协议

下面这些操作名必须严格一致。

## 6.1 `list_targets`

请求：

```json
{
  "op": "list_targets",
  "args": {}
}
```

成功响应：

```json
{
  "ok": true,
  "data": {
    "targets": [
      {
        "id": "emulator-5554",
        "platform": "android",
        "name": "Pixel 7 API 34",
        "state": "online",
        "metadata": {
          "model": "Pixel 7",
          "os_version": "Android 14"
        }
      }
    ]
  }
}
```

要求：

- 未安装平台运行时工具时，返回空列表，不报错
- 必须快，目标小于 1 秒

桌面平台补充约定：

- 对 `macOS` / `Windows`，`list_targets` 的目标不是“列出很多 app 或 window”
- 第一版统一把“当前宿主机本身”视为一个 target
- 推荐固定返回单个 target：
  - `id = "self"`
- 后续所有操作都针对这个 host target：
  - `screenshot("self")`
  - `dump_ui("self")`
  - `tap("self", x, y)`

原因：

- 这样和移动端“一台设备就是一个 target”的抽象最一致
- 上层不需要先学桌面平台的窗口 / 应用模型
- app、window、前后台切换等复杂度收敛在平台实现内部

建议：

- `macOS`
  - 在 macOS host 上返回一个 `self`
  - 不在 macOS host 上返回空列表
- `Windows`
  - 在 Windows host 上返回一个 `self`
  - 不在 Windows host 上返回空列表

注意：

- 如果桌面平台尚未真正实现 screenshot / dump_ui / tap 等核心能力，不要提前返回假的 `self`
- 这会误导上层认为“这个 target 已经可操作”
- 未实现阶段，允许返回空列表

## 6.2 `screenshot`

请求：

```json
{
  "op": "screenshot",
  "args": {
    "target": "emulator-5554"
  }
}
```

成功响应：

```json
{
  "ok": true,
  "data": {
    "mimeType": "image/png",
    "base64": "iVBORw0K..."
  }
}
```

要求：

- 必须是 PNG
- 返回的像素坐标必须和 `tap` / `swipe` 一致

## 6.3 `dump_ui`

请求：

```json
{
  "op": "dump_ui",
  "args": {
    "target": "emulator-5554"
  }
}
```

成功响应：

```json
{
  "ok": true,
  "data": {
    "raw": "<hierarchy>...</hierarchy>",
    "rawMime": "application/xml",
    "selectors": [
      {
        "resourceId": "us.zoom.videomeetings:id/btnLogin",
        "text": "Login",
        "contentDesc": "",
        "class": "android.widget.Button",
        "bounds": "[432,1186][720,1290]",
        "clickable": true,
        "enabled": true,
        "visible": true
      }
    ]
  }
}
```

要求：

- `selectors` 字段名必须和上面一致
- 上限建议约 200 条
- 要去重
- 同一页面重复输出时顺序尽量稳定

## 6.4 `tap`

请求：

```json
{
  "op": "tap",
  "args": {
    "target": "emulator-5554",
    "x": 576,
    "y": 1238
  }
}
```

成功响应：

```json
{
  "ok": true,
  "data": {
    "ok": true,
    "exitCode": 0,
    "stdout": "",
    "stderr": "",
    "extra": {
      "tapX": 576,
      "tapY": 1238
    }
  }
}
```

说明：

- 所有“变更型操作”都建议复用这个 `OpResult` 风格

## 6.5 `swipe`

请求：

```json
{
  "op": "swipe",
  "args": {
    "target": "emulator-5554",
    "x1": 500,
    "y1": 1500,
    "x2": 500,
    "y2": 400,
    "durationMs": 300
  }
}
```

成功响应：

```json
{
  "ok": true,
  "data": {
    "ok": true,
    "exitCode": 0,
    "stdout": "",
    "stderr": "",
    "extra": {
      "fromX": 500,
      "fromY": 1500,
      "toX": 500,
      "toY": 400,
      "durationMs": 300
    }
  }
}
```

## 6.6 `input_text`

请求：

```json
{
  "op": "input_text",
  "args": {
    "target": "emulator-5554",
    "text": "hello world"
  }
}
```

要求：

- 必须拒绝：
  - 换行
  - 单引号
  - 反引号
- 必须拒绝超过 1KB 的文本

成功响应：

```json
{
  "ok": true,
  "data": {
    "ok": true,
    "exitCode": 0,
    "stdout": "",
    "stderr": "",
    "extra": {
      "length": 11
    }
  }
}
```

## 6.7 `key_event`

请求：

```json
{
  "op": "key_event",
  "args": {
    "target": "emulator-5554",
    "key": "ENTER"
  }
}
```

共享 key vocabulary：

- `BACK`
- `HOME`
- `ENTER`
- `MENU`
- `RECENTS`
- `POWER`
- `DEL`
- `TAB`
- `SPACE`
- `ESCAPE`

## 6.8 `launch_app`

请求：

```json
{
  "op": "launch_app",
  "args": {
    "target": "emulator-5554",
    "package": "us.zoom.videomeetings",
    "activity": "us.zoom.videomeetings.LauncherActivity"
  }
}
```

要求：

- 非 Android 平台可以忽略 `activity`

## 6.9 `kill_app`

请求：

```json
{
  "op": "kill_app",
  "args": {
    "target": "emulator-5554",
    "package": "us.zoom.videomeetings"
  }
}
```

## 6.10 `switch_app_env`

请求：

```json
{
  "op": "switch_app_env",
  "args": {
    "target": "emulator-5554",
    "env": "dev"
  }
}
```

要求：

- 不支持就明确返回 `NOT_IMPLEMENTED`
- 支持的话，内部要负责：
  - 切环境
  - 重启 app
  - 等待回到稳定状态

## 6.11 `type_credential`

请求：

```json
{
  "op": "type_credential",
  "args": {
    "target": "emulator-5554",
    "env": "dev",
    "role": "host",
    "field": "password",
    "skipClear": false
  }
}
```

成功响应：

```json
{
  "ok": true,
  "data": {
    "ok": true,
    "exitCode": 0,
    "stdout": "",
    "stderr": "",
    "extra": {
      "length": 16,
      "field": "password"
    }
  }
}
```

要求：

- 明文不能出现在请求里
- 明文不能出现在响应里
- 明文不能出现在 stderr 里

---

## 7. 错误分类

所有平台都统一使用这 4 类：

- `NOT_IMPLEMENTED`
- `BAD_TARGET`
- `SUBPROCESS`
- `INTERNAL`

失败响应示例：

```json
{
  "ok": false,
  "error": {
    "kind": "BAD_TARGET",
    "message": "target emulator-5554 is offline",
    "details": {}
  }
}
```

约束：

- target 不存在 / 坐标越界 / 参数不合法：
  - 用 `BAD_TARGET`
- 平台天然不支持：
  - 用 `NOT_IMPLEMENTED`
- 原生工具失败 / 超时：
  - 用 `SUBPROCESS`
- 真正未分类异常：
  - 用 `INTERNAL`

不要所有错误都塞到 `INTERNAL`。

---

## 8. `dump_ui` 的统一要求

这是最重要的部分之一。

### 8.1 统一 selector 字段

必须输出：

- `resourceId`
- `text`
- `contentDesc`
- `class`
- `bounds`
- `clickable`
- `enabled`
- `visible`

没有值时也要给默认值，不要缺字段。

### 8.2 排序建议

建议优先级：

1. 可见且可点击
2. 可见且可输入
3. 当前交互相关容器
4. 有助于定位的静态文本

### 8.3 去重建议

如果多个节点实质上是同一控件，不要重复暴露很多次。

优先保留：

- id 更稳定的
- bounds 更准确的
- text / contentDesc 信息更全的

### 8.4 稳定性要求

同一页面反复 `dump_ui`：

- selector 顺序应基本稳定
- 不要一会儿 40 条，一会儿 180 条

---

## 9. 超时与日志

建议默认超时：

- `list_targets`：1 秒
- 常规截图 / dump / tap / input：15 秒
- helper 凭据输入：15 秒
- 环境切换：90 秒

日志规则：

- `stdout`：协议 JSON only
- `stderr`：调试日志
- `stderr` 绝不能包含明文凭据

---

## 10. 与 executor 的关系

如果平台后续要接入 executor，建议：

1. `toolkit_api.py` 作为唯一真实实现层
2. `toolkit_cli.py` 给探索 / broker 调用
3. `main.py` 按 NDJSON executor contract 实现
4. `main.py` 内部调用 `toolkit_api.py`

不要这样做：

- explorer 一套平台逻辑
- executor 再抄一套平台逻辑

这样后面一定会漂。

---

## 11. 最低交付要求

每个平台交付时，至少要给：

1. `executor_<platform>/` 代码目录
2. `README.md`
3. 按 `PLATFORM-SUBMISSION-TEMPLATE.zh-CN.md` 填好的文档 <!-- TODO: 缺少外部文档链接，待补充 -->
4. 至少 3 条自测记录

如果暂时不支持某些能力，也可以交，但必须：

- 明确写清楚
- 统一返回 `NOT_IMPLEMENTED`
- 不要假支持

---

## 12. 推荐 README 内容

每个平台自己的 `README.md` 至少写清楚：

1. 依赖什么原生工具
2. 本地怎么安装依赖
3. 如何单独运行 `toolkit_cli.py`
4. 哪些操作已实现
5. 哪些操作未实现
6. 坐标体系是什么
7. `dump_ui` 来源是什么
8. 有没有已知限制

---

## 13. 一句话总结

每个平台实现方最终要交的，不是“几个能跑的脚本”，而是：

- 一套可复用的 Python 平台能力库
- 一套统一的一次性 JSON CLI 协议
- ~~一个可选的 executor 入口~~ <!-- WillNotDo: 当前未提供 executor 具体实现逻辑 -->

这样你后面整合进 Studio 时，才能真正做到统一，而不是每个平台都特殊处理。
