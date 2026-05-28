## 1. 项目基础结构

- [ ] 1.1 创建 Python 包目录结构：`ios_ui_ta_proxy/`，含 `__main__.py`、`__init__.py`
- [ ] 1.2 创建 `requirements.txt`：`fastapi`、`uvicorn[standard]`、`requests`、`pydantic`
- [ ] 1.3 创建 `README.md`：说明依赖、启动方式、WDA 前置条件
- [ ] 1.4 添加 `.gitignore`（Python 通用 + `.venv/`）

## 2. WDA 客户端封装

- [ ] 2.1 创建 `wda_client.py`：封装 WDA REST 请求基类，含 base URL 构造和超时设置
- [ ] 2.2 实现 `WDAClient.screenshot()`：调用 `GET /screenshot`，返回 base64 字符串
- [ ] 2.3 实现 `WDAClient.source(format="xml")`：调用 `GET /source`，支持 xml/json 参数
- [ ] 2.4 实现 `WDAClient.accessible_source()`：调用 `GET /wda/accessibleSource`
- [ ] 2.5 实现 `WDAClient.tap(x, y)`：构造 W3C pointer action，调用 `POST /session/:id/actions`
- [ ] 2.6 实现 `WDAClient.swipe(from_x, from_y, to_x, to_y, duration_ms)`：构造 W3C drag action
- [ ] 2.7 实现 `WDAClient.long_press(x, y, duration_ms)`：构造 W3C long press action
- [ ] 2.8 实现 `WDAClient.get_screen_size()`：调用 `GET /wda/screen`，缓存屏幕尺寸

## 3. Session 管理

- [ ] 3.1 创建 `session_manager.py`：维护 session ID 状态（`None` / 活跃 session）
- [ ] 3.2 实现懒建立逻辑：操作前检查 session，不存在则调用 `POST /session` 建立
- [ ] 3.3 实现后台心跳线程：每 30s 调用 `GET /session/:id`，连续 3 次失败则清除 session
- [ ] 3.4 实现 `SessionManager.reset()`：调用 `DELETE /session/:id` 并清除本地缓存
- [ ] 3.5 添加 session 建立的重试逻辑（最多 3 次，间隔 1s）

## 4. FastAPI 路由实现

- [ ] 4.1 创建 `server.py`：初始化 FastAPI app，注册路由和启动参数
- [ ] 4.2 实现 `GET /health`：返回 proxy 状态和 WDA 连通性
- [ ] 4.3 实现 `GET /screenshot`：支持 `format=png`（默认）和 `format=base64` 参数
- [ ] 4.4 实现 `GET /ui_dump`：支持 `format=xml`（默认）/ `json`，`mode=default` / `accessible`
- [ ] 4.5 实现 `POST /click`：Pydantic model 校验 `{x, y}`，坐标越界返回 400
- [ ] 4.6 实现 `POST /swipe`：Pydantic model 校验 `{from_x, from_y, to_x, to_y, duration?}`
- [ ] 4.7 实现 `POST /long_press`：Pydantic model 校验 `{x, y, duration}`，附加 warning 逻辑
- [ ] 4.8 实现 `POST /session/reset`：调用 SessionManager.reset()

## 5. 错误处理与超时

- [ ] 5.1 创建统一异常处理器：所有 WDA 通信错误转为 `{"error": "...", "detail": "..."}` 格式
- [ ] 5.2 为 screenshot/click/swipe 设置 5s 超时；ui_dump 设置 15s 超时
- [ ] 5.3 支持请求体传入自定义 `timeout` 参数（上限 60s）
- [ ] 5.4 WDA 不可达（连接拒绝/超时）返回 503；WDA 返回错误返回 502
- [ ] 5.5 参数校验失败统一返回 422，格式符合 spec

## 6. 启动入口

- [ ] 6.1 实现 `__main__.py`：解析 `--wda-host`、`--wda-port`、`--proxy-port` 参数
- [ ] 6.2 端口占用检测：启动前检查 proxy-port 是否可用，不可用时输出错误退出
- [ ] 6.3 启动时打印服务信息：WDA 地址、proxy 监听地址

## 7. 验证与测试

- [ ] 7.1 用模拟器手动验证 `GET /health`、`GET /screenshot`、`GET /ui_dump`
- [ ] 7.2 验证 `POST /click` 和 `POST /swipe` 在模拟器上实际触发 UI 操作
- [ ] 7.3 验证 session 心跳：等待 60s 后操作不报 session 过期错误
- [ ] 7.4 验证错误格式：WDA 不可达时 /health 和操作接口的响应格式符合 spec
- [ ] 7.5 （可选）真机场景：通过 `iproxy` 端口转发验证全链路
