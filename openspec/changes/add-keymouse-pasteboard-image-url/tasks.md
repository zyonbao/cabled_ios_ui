# Tasks

## 1. 代理层多类型剪贴板能力（pasteboard-op）

- [x] 1.1 `device.py` `set_pasteboard` 增加 `content_type` 参数：`plaintext`/`url` 走 UTF-8→Base64，`image` 走原始字节→Base64，`contentType` 透传 WDA
- [x] 1.2 `device.py` `get_pasteboard` 增加 `content_type` 参数；返回 `data` 增加 `contentType` 字段，image 态返回 `image`(PNG Base64)，保持默认 plaintext 单次读取语义
- [x] 1.3 `toolkit_api.py` 拆分大小上限：保留文本 `_PASTEBOARD_MAX_BYTES`(64 KiB)，新增 `_PASTEBOARD_IMAGE_MAX_BYTES`(默认 16 MiB)，超限返回 `BAD_TARGET`
- [x] 1.4 `toolkit_api.set_pasteboard` / `get_pasteboard` 透传 `content_type` 并按类型校验

## 2. web 端点与前端（console-pasteboard-ui / pasteboard-op）

- [x] 2.1 `web_server.py` `/api/set_pasteboard` 接受可选 `contentType` 与 `image`(base64)，兼容仅 `{target, text}`；`/api/get_pasteboard` 接受可选 `contentType`，返回含 `contentType`
- [x] 2.3 `app.js` 发送时识别单个 URL 走 `url`，否则 `plaintext`
- [ ] 2.2 / 2.4 / 2.5 （可选，未实现）web 设置弹窗图片输入、>10 MiB 确认、镜像画布拖入——端点已支持，前端图片 UI 留作后续

## 3. slide6 桌面端键鼠 Tab（console-pasteboard-ui）

- [x] 3.1 `keymouse_tab.py` 设置剪贴板弹窗：文本输入 + 添加图片预览，互斥与二次确认
- [x] 3.2 发送时 URL 识别 → `url`，否则 `plaintext`；图片 → `image`
- [x] 3.3 画面显示区域 `dragEnterEvent`/`dropEvent` 接受文件拖入，与手势链路分离；非图片提示「仅支持图片」
- [x] 3.4 图片 >10 MiB 二次确认（设置弹窗与拖拽共用）
- [x] 3.5 「读取剪贴板」按设置开关：开启则文本直接复制到本机、不弹窗
- [x] 3.6 「UI XML」按设置开关：开启则 XML 直接复制到本机、不弹窗

## 4. Key/Mouse 设置开关（console-pasteboard-ui）

- [x] 4.1 `keymouse_settings.py` 新增两个布尔键 `pasteboard_auto_copy_host`、`ui_xml_auto_copy_host`，默认关闭，读写封装
- [x] 4.2 `keymouse_settings_widget.py` 渲染两个开关并即时写回
- [x] 4.3 `zh-CN.json` / `en-US.json` 新增设置项文案与图片/URL/拖拽/过大确认相关提示文案

## 5. 验证

- [x] 5.0 py_compile / JSON / i18n.validate / 离屏导入 / 尺寸校验逻辑通过
- [ ] 5.1 真机验证：设置文本/URL/图片三类剪贴板均生效
- [ ] 5.2 真机验证：拖拽图片到画面写入设备剪贴板
- [ ] 5.3 真机验证：>10 MiB 确认与 16 MiB 硬上限拒绝
- [ ] 5.4 真机验证：两个设置开关开/关行为
- [x] 5.5 `openspec validate add-keymouse-pasteboard-image-url --strict` 通过
