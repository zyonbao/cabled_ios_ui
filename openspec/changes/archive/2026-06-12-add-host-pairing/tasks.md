## 1. toolkit 配对能力（device.py）

- [x] 1.1 新增 `_open_lockdown_no_autopair()`：手搓 usbmux lockdown 客户端（`ServiceConnection.create_using_usbmux` + 选 `PlistUsbmuxLockdownClient` + `_initialize()`），**跳过** `_handle_autopair`，规避陈旧记录导致的 `validate_pairing` 崩溃（坑 1）
- [x] 1.2 新增 `_probe_paired_async()`：自管 `validate_pairing()`，捕获 `ConnectionTerminatedError` / `ssl.SSLError` 并按"未配对"处理（坑 5）
- [x] 1.3 新增常量 `_PAIRING_RECORDS_DIR = ~/Library/CablediOS/PairingRecords` 并用作缓存目录（坑 2/3）
- [x] 1.4 新增 `_clear_unwritable_pair_cache()`：配对前清理不可写的旧缓存文件（坑 2）
- [x] 1.5 实现 `pairing_state()` / `pair()` / `unpair()`：`pair()` 在全新连接上直接 `lockdown.pair()` 并经 `PlistUsbmuxLockdownClient.save_pair_record` 写回 usbmuxd；`unpair()` 手动 `fetch_pair_record()` 后发送 Unpair（坑 4）
- [x] 1.6 全程 `logging`（不打印密钥/证书）

## 2. toolkit 同步包装（toolkit_api.py）

- [x] 2.1 新增 `pairing_state(target)` / `pair_device(target)` / `unpair_device(target)`，沿用 `_ok` / `_err`
- [x] 2.2 `list_targets()` 未配对设备跳过 WDA 探测、置 `offline`（坑 6）

## 3. 顶栏配对按钮与状态广播（main_window.py）

- [x] 3.1 顶栏设备下拉框右侧新增配对按钮，文案随 `_paired`（None/True/False）切换
- [x] 3.2 `_refresh_pairing` 异步探测 + `_on_pairing_result` 忽略过期结果
- [x] 3.3 `_set_pair_state` 广播：更新按钮、应用蒙版、按配对态加载/清空依赖配对 tab、处理键鼠 on_enter/on_leave
- [x] 3.4 `_on_pair_clicked`（取消配对二次确认）/ `_run_pair_action` / `_on_pair_action_done`（完成后重跑选择流程）

## 4. 共享配对蒙版与 tab 门控（main_window.py）

- [x] 4.1 新增共享 `_pair_overlay`，重父到当前依赖配对 tab；`_apply_pair_overlay` 控制显隐与定位
- [x] 4.2 对受门控 tab 安装 `eventFilter`，跟随尺寸变化重定位蒙版
- [x] 4.3 `_apply_gated_targets`：仅在已配对时给依赖配对 tab 下发目标，否则清空（坑 6）
- [x] 4.4 「设备信息」tab 不受门控

## 5. UI 细节修正

- [x] 5.1 设备列表项仅显示 `名称 (UDID)` 或 `UDID`，去除 model / 「未安装WDA」后缀
- [x] 5.2 键鼠 tab 非活动选择时不写共享顶栏状态（坑 7）

## 6. i18n 文案

- [x] 6.1 `zh-CN.json`：新增配对按钮/蒙版/状态/取消确认等文案键
- [x] 6.2 `en-US.json`：与 zh-CN 同步，键集一致

## 7. 验证

- [x] 7.1 lint（ReadLints）确认 device.py / toolkit_api.py / main_window.py / keymouse_tab.py 无报错
- [x] 7.2 模块导入校验通过
- [x] 7.3 手动验证：未配对设备列表只显示 UDID、无 WDA 提示、无 `NotPairedError` traceback
- [x] 7.4 手动验证：点「配对」→ 设备弹信任 → 信任后配对成功（含设备上残留陈旧记录的场景）
- [x] 7.5 手动验证：配对后顶栏不误报「未安装WDA」；各依赖配对 tab 加载正常
- [x] 7.6 手动验证：「取消配对」二次确认后生效，状态回到未配对
- [x] 7.7 `openspec validate add-host-pairing --strict` 通过
