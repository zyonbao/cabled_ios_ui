## 1. executor 层：媒体分区 AFC（afc-filesystem-op）

- [ ] 1.1 在 `executor_ios/device.py` 的 Nuitka 静态导入提示块确认 `AfcService` 已纳入（house-arrest 之外的直连 AFC）
- [ ] 1.2 `iOSDevice._with_afc` 按 `root` 分流：`media` → `AfcService(lockdown)`（`com.apple.afc`），`documents`/`container` 维持 house-arrest
- [ ] 1.3 `_AFC_BASE` 增加 `"media": "/"`；`_afc_device_path` 对 media 直接透传逻辑路径
- [ ] 1.4 `_validate_root` 接受 `media`；`toolkit_api.afc_*` 在 `root="media"` 时允许 `bundle_id` 为空
- [ ] 1.5 新增 `iOSDevice.afc_read` 与 `toolkit_api.afc_read(target, bundle_id, root, remote_path, max_bytes=None)`，经 AFC 读取字节，受 `max_bytes` 上限保护
- [ ] 1.6 校验：临时脚本在真机以 `root="media"` 验证 list/pull/push/rm/mkdir/rename 与 afc_read 的返回结构与错误路径

## 2. UI：文件系统 Tab（slide6-file-system）

- [ ] 2.1 复用 `slide6_console/afc_browser.py` 的浏览器：以 `root="media"`、`bundle_id=""`、起始路径 `/` 提供媒体分区浏览（评估内嵌面板 vs 复用对话框）
- [ ] 2.2 新建「文件系统」Tab 容器并注册到 `main_window` 左侧 Tab；`set_target` 选中设备后加载
- [ ] 2.3 回归导入/导出（文件与文件夹）/删除（二次确认）/新建/重命名在 media 根下可用

## 3. UI：相册 Tab（slide6-dcim-album）

- [ ] 3.1 新建 `slide6_console/dcim_album.py`：缩略图网格（`QListView`/`QListWidget` IconMode），基于 `afc_list(root="media", "/DCIM")` 渲染条目
- [ ] 3.2 缩略图按需异步加载：可见项经 `afc_read`（带 `max_bytes`）取字节 → `QImage` 缩放；按 remote 路径内存缓存；失败/非图片回退占位
- [ ] 3.3 进入相册子目录与返回上一级（如 `100APPLE`）
- [ ] 3.4 双击查看大图对话框（`QImage` 适配缩放）；不支持类型给占位/提示
- [ ] 3.5 导出（`afc_pull`，保字节+时间戳）与导入（`afc_push`，按字节），导入后提示"相册可见性取决于系统索引"
- [ ] 3.6 多选（ExtendedSelection）删除：一次汇总二次确认 → 逐项 `afc_rm` → 刷新
- [ ] 3.7 注册「相册」Tab 到 `main_window` 左侧 Tab；`set_target` 联动

## 4. 校验与收尾

- [ ] 4.1 真机回归：iOS ≤16 与 iOS 17+ 各验证 文件系统浏览/传输、相册缩略图/查看/导入导出/多选删除
- [ ] 4.2 媒体分区受限目录（如 `PhotoData`）失败路径友好提示，不崩溃
- [ ] 4.3 更新 `slide6_console/README.md` 说明两个新 Tab 与限制（Photos DB 可见性、HEIC 解码回退）
- [ ] 4.4 运行 `openspec validate "add-afc-filesystem-and-dcim" --strict` 通过
