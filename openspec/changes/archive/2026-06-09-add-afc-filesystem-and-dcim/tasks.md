## 1. executor 层：媒体分区 AFC（afc-filesystem-op）

- [x] 1.1 在 `executor_ios/device.py` 的 Nuitka 静态导入提示块确认 `AfcService` 已纳入（house-arrest 之外的直连 AFC）
- [x] 1.2 `iOSDevice._with_afc` 按 `root` 分流：`media` → `AfcService(lockdown)`（`com.apple.afc`，`async with` 关闭 reader），`documents`/`container` 维持 house-arrest
- [x] 1.3 `_AFC_BASE` 增加 `"media": "/"`；`_afc_device_path` 对 media 直接透传逻辑路径
- [x] 1.4 `_validate_root` 接受 `media`；`toolkit_api.afc_*` 在 `root="media"` 时允许 `bundle_id` 为空
- [x] 1.5 新增 `iOSDevice.afc_read` 与 `toolkit_api.afc_read(target, bundle_id, root, remote_path, max_bytes=None)`，经 AFC 读取字节，受 `max_bytes` 上限保护
- [x] 1.6 校验：真机以 `root="media"` 验证 list/mkdir/rm 与 afc_read（iOS 缩略图命中 57511B、原图 max_bytes 拒绝、坏 root BAD_TARGET）通过，无 orphan task

## 2. UI：文件系统 Tab（slide6-file-system）

- [x] 2.1 将 `afc_browser.py` 浏览逻辑抽成可嵌入 `AfcBrowserPanel`；以 `root="media"`、`bundle_id=""`、起始路径 `/` 提供媒体分区浏览
- [x] 2.2 新建 `FileSystemTab` 容器并注册到 `main_window` 左侧 Tab；`set_target` 选中设备后加载
- [x] 2.3 复用 panel 既有导入/导出（文件与文件夹）/删除（二次确认）/新建/重命名能力，media 根下生效

## 3. UI：相册 Tab（slide6-dcim-album）

- [x] 3.1 新建 `slide6_console/dcim_album.py`：缩略图网格（`QListWidget` IconMode），基于 `afc_list(root="media", "/DCIM")` 渲染条目
- [x] 3.2 本地磁盘缩略图缓存（按 UDID，key=remote 路径，失效依据 `(size,mtime)`，内容小 JPEG，跨会话持久）；按列表自上而下渐进建缓存、限并发（最多 3）、命中本地缓存即用
- [x] 3.2a 建缓存流水线：优先经 `afc_read` 读 `PhotoData/Thumbnails/V2/DCIM/<相册>/<文件名>/` 下小 JPG 直接落地；缺失时读原图生成 JPEG（HEIC/HEIF 用 `pillow-heif`，非 HEIC 用 `QImage` 缩放）；超阈值/失败/视频/非图片回退占位（真机：iOS 缩略图命中 57511/53668/4175B）
- [x] 3.3 进入相册子目录与返回上一级（如 `100APPLE`，不越过 `/DCIM`）
- [x] 3.4 双击查看大图对话框：HEIC/HEIF 用 `pillow-heif`、非 HEIC 用 `QImage` 解码显示（真机 PNG 1179×2556、合成 HEIC 800×600 通过）；视频/不支持类型给占位/提示
- [x] 3.5 导出（`afc_pull`，保字节+按 mtime 回写本地时间戳，HEIC 原样）；相册 Tab **不提供**导入到相册与删除（相册增删需设备上 iOS App 调用系统照片库接口；文件级写入/删除走「文件系统」Tab）
- [x] 3.7 注册「相册」Tab 到 `main_window` 左侧 Tab；`set_target` 联动

## 4. 校验与收尾

- [x] 4.1 真机回归：iOS ≤16 与 iOS 17+ 各验证 文件系统浏览/传输/删除、相册缩略图（含 iOS 缓存命中与回退）/查看（含 HEIC）/导出
- [x] 4.2 验证 `PhotoData/Thumbnails/V2/DCIM/<相册>/<文件名>/` 缩略图映射在目标 iOS 版本上的可用性；缺失/布局不同的回退路径生效
- [x] 4.3 媒体分区受限目录（如 `PhotoData/CPL/...`）失败路径友好提示，不崩溃
- [x] 4.4 HEIC 解码：`pillow-heif>=1.0` 已加入 `slide6_console/requirements.txt`（必备），模块导入时 `register_heif_opener()`；打包已确认 `pillow-heif`（`_pillow_heif.so` 原生扩展 + `libheif.1.21.2.dylib`）与 `PIL` 随 `.app` 存在，离屏启动冻结产物可正常启动
- [x] 4.5 更新 `slide6_console/README.md` 说明两个新 Tab 与限制（相册不提供导入到相册、Photos 同步可见性、HEIC 用 pillow-heif 解码、本地缩略图缓存位置、受限目录友好提示）
- [x] 4.6 运行 `openspec validate "add-afc-filesystem-and-dcim" --strict` 通过
