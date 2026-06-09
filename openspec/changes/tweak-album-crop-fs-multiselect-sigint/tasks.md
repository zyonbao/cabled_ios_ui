## 1. 相册缩略图居中裁剪（slide6-dcim-album）

- [x] 1.1 在 `dcim_album.py` 抽出 `_crop_square_qimage`：非 HEIC 用 `QImage.scaled(side, side, KeepAspectRatioByExpanding, Smooth)` + 居中 `copy()`；HEIC 用 `PIL.ImageOps.fit((side, side))`
- [x] 1.2 `_write_thumb_jpeg` 输出正方形裁剪 JPEG；iOS 端缓存 JPG 经 `_write_square_jpeg_from_bytes` 同一裁剪流水线落地（不再原样写入）
- [x] 1.3 `_cache_filename` 加入裁剪策略版本标记 `_THUMB_STRATEGY_TAG="c1"`，切换后旧缓存自动失效重建
- [x] 1.4 网格 `iconSize` 已为正方形边长（`_THUMB_PX`）与方形缩略图匹配，满格显示
- [x] 1.5 验证：竖 PNG/横 HEIC/iOS 小 JPG 均裁为 200×200 方形；真机三张缩略图均 200×200（iOS 缓存路径生效）
- [x] 1.6 网格间距收紧为 16px（`_GRID_SPACING_PX`）、`gridSize=(THUMB, THUMB+20)`、单行文件名（`ElideMiddle`、关闭 wordWrap、悬停 tooltip）；每项 `setSizeHint` 固定保证名称带始终可见
- [x] 1.7 相册移除「删除选中」按钮与相关方法（含不再需要的缩略图缓存清理）；导入/删除统一改由「文件系统」Tab 完成（原因：Apple 相册需经 iOS App 系统接口增删，非文件层面）
- [x] 1.8 相册根固定为 `/DCIM`、列表过滤以 `.` 开头的系统目录（隐藏 `.MISC`），完整展示 `NNNAPPLE` 子目录；真机验证 `100/101/102APPLE` 均展示、`.MISC` 隐藏

## 1b. 侧边 Tab 顺序与选中行为（slide6-desktop-shell）

- [x] 1b.1 `main_window` Tab 顺序改为 设备信息 / 相册 / 文件系统 / App 列表 / 键鼠操作
- [x] 1b.2 移除 `on_select_device` 中强制 `setCurrentWidget(device_info_tab)`；设备信息仅为启动默认，切设备保留当前 Tab（验证通过）

## 2. 文件系统多选 + 右键批量操作（slide6-file-system）

- [x] 2.1 `AfcBrowserPanel.__init__` 增加 `multi_select: bool = False`；为真时表格 `ExtendedSelection`
- [x] 2.2 右键菜单在多选 >1 项时显示「批量下载 N 项到…」「批量删除 N 项…」；单项/单选仍走既有单项操作
- [x] 2.3 批量下载：`_batch_export` 选目标目录 → 后台逐项 `afc_pull` → 汇总成功/失败计数
- [x] 2.4 批量删除：`_batch_delete` 一次汇总二次确认（数量+示例名）→ 后台逐项 `afc_rm` → 刷新；取消不删除
- [x] 2.5 `FileSystemTab` 传 `multi_select=True`；`AfcBrowserDialog`（App 沙盒）保持单选默认
- [x] 2.6 验证：多选模式 ExtendedSelection、批量方法就位；沙盒对话框仍 SingleSelection、`multi_select=False`；真机批量下载/删除底层流程通过

## 3. Ctrl+C 干净退出（slide6-app-lifecycle）

- [x] 3.1 `app.py` 安装 `signal.signal(SIGINT, handler)`：handler 调用 `window.close()`（走既有 closeEvent 清理）后 `app.quit()`
- [x] 3.2 启动 200ms 低频 `QTimer`（空回调）唤醒解释器，使 Qt 循环运行时信号处理得以执行；保留 timer 引用避免被回收
- [x] 3.3 验证：子进程启动应用后发 SIGINT，进程干净退出（returncode 0），不崩溃；closeEvent 中 `stop_stream`/`kbd_sender.stop` 收敛后台线程

## 4. 收尾

- [x] 4.1 更新 `slide6_console/README.md`（相册缩略图正方形裁剪、文件系统多选批量下载/删除、Ctrl+C 干净退出）
- [x] 4.2 运行 `openspec validate "tweak-album-crop-fs-multiselect-sigint" --strict` 通过
