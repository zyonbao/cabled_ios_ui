# executor_ios

`executor_ios` 是 Studio 平台协议下的 iOS Python 执行器实现，提供可复用的 `toolkit_api.py` 能力层和一次性 JSON CLI 入口 `toolkit_cli.py`。

当前实现仅支持 macOS 上通过 USB 连接的 iOS 物理设备。iOS 模拟器、Wi-Fi 配对设备和 NDJSON executor 入口暂不在当前阶段范围内。

## 目录结构

```text
executor_ios/
  __init__.py
  device.py          # iOSDevice / iOSDevicesManager，多设备管理、端口转发、WDA 生命周期
  toolkit_api.py     # 平台能力 API，供 Explorer / broker / executor 复用
  toolkit_cli.py     # 一次性 JSON stdin/stdout CLI
  tunneld_main.py    # iOS 17+ XPC tunnel daemon 入口，可打包为 ios_tunneld
  ios_tunneld.py     # multidist 打包用的 tunneld 入口包装（basename = ios_tunneld）
  credentials.py     # type_credential 使用的凭据读取模块（原 secrets.py，避免遮蔽 stdlib）
```

## 环境依赖

- macOS
- Python 3.10+
- 已安装并信任的 iOS 物理设备
- 已在设备上手动安装 WebDriverAgent Runner
- Python 依赖：见 `executor_ios/requirements.txt`

安装依赖：

```bash
python3 -m pip install -r executor_ios/requirements.txt
```

## WDA 配置

本项目不负责下载或安装 WDA。设备未安装 WDA 时，`list_targets` 会将该设备标记为 `offline`。

默认 WDA bundle ID：

```text
com.facebook.WebDriverAgentRunner.xctrunner
```

如需覆盖，创建 `~/.executor_ios.json`：

```json
{
  "wda_bundle_id": "com.facebook.WebDriverAgentRunner.xctrunner"
}
```

## iOS 17+ XPC Tunnel

iOS 17+ 启动 WDA xctrunner 需要 XPC tunnel。当前设计中，tunneld 由外部进程负责运行，`device.py` 会在 `do_prepare()` 中自动查询本地 tunneld HTTP API：

```text
http://127.0.0.1:49151
```

开发调试时可直接运行：

```bash
sudo python3 -m executor_ios.tunneld_main
```

发布给客户机器时，建议将 `tunneld_main.py` 打包为独立二进制 `ios_tunneld`，并以 root 权限作为 LaunchDaemon 运行。

## 一次性 CLI 使用

启动方式：

```bash
python3 -B -m executor_ios.toolkit_cli
```

请求从 stdin 读取单个 JSON 对象，响应向 stdout 输出单个 JSON 对象。

示例：列出设备

```bash
echo '{"op":"list_targets","args":{}}' | python3 -B -m executor_ios.toolkit_cli
```

示例：截图

```bash
echo '{"op":"screenshot","args":{"target":"<UDID>"}}' | python3 -B -m executor_ios.toolkit_cli
```

示例：点击

```bash
echo '{"op":"tap","args":{"target":"<UDID>","x":100,"y":200}}' | python3 -B -m executor_ios.toolkit_cli
```

## 已实现能力

- `list_targets`
- `screenshot`
- `dump_ui`
- `tap`
- `swipe`
- `input_text`
- `key_event`
- `launch_app`
- `kill_app`
- `type_credential`

`switch_app_env` 当前返回 `NOT_IMPLEMENTED`。

`key_event` 中：

- `HOME`、`POWER`、`ENTER`、`DEL`、`TAB`、`SPACE`、`ESCAPE` 已实现或映射到 WDA 支持路径
- `BACK`、`MENU`、`RECENTS` 在 iOS 上无对应语义，返回 `NOT_IMPLEMENTED`

## 坐标体系

`screenshot`、`tap`、`swipe` 使用 WDA 暴露的 iOS 逻辑坐标体系。调用方应使用截图/界面树对应的坐标，不需要额外处理 Retina 缩放。

## dump_ui 来源

`dump_ui` 调用 WDA：

```text
GET /source?format=xml
```

返回内容包含：

- `raw`：WDA XML 原始 UI 树
- `rawMime`：`application/xml`
- `selectors`：按统一 contract 映射后的 selector 列表，最多 200 条

每条 selector 包含：

- `resourceId`
- `text`
- `contentDesc`
- `class`
- `bounds`
- `clickable`
- `enabled`
- `visible`

## 凭据输入

`type_credential` 不接收明文凭据，只从环境变量读取：

```text
IOS_CRED_<ROLE>_<FIELD>
```

示例：

```bash
export IOS_CRED_HOST_PASSWORD='secret'
echo '{"op":"type_credential","args":{"target":"<UDID>","env":"dev","role":"host","field":"password"}}' | python3 -B -m executor_ios.toolkit_cli
```

明文凭据不会出现在 stdout、stderr 或返回 JSON 中。

## 已知限制

- 仅支持 USB 物理设备
- 不支持 iOS 模拟器
- 不支持 Wi-Fi 配对设备
- 当前 `toolkit_cli.py` 是一次性子进程模式，进程间不复用 WDA session；同一 Python 进程内直接调用 `toolkit_api.py` 时可复用 session
- `main.py` / NDJSON executor 入口尚未实现
- Phase 3 的多设备、session 复用和 iOS 17+ tunneld 流程仍需实机验收
