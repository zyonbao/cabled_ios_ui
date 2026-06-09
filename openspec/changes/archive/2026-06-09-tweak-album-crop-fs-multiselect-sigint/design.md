## Context

`slide6_console` 的相册与文件系统 Tab 已上线（见未归档变更 `add-afc-filesystem-and-dcim`）。本变更针对三处独立的打磨问题：

- 相册缩略图：`dcim_album.py` 生成缩略图时对非 HEIC 用 `QImage.scaled(KeepAspectRatio)`、对 HEIC 用 `PIL.thumbnail`，都按比例缩放；而 `QListWidget` IconMode 在固定 `iconSize` 网格中显示这些非正方形图标，视觉上出现留边/不齐整（用户感知为「拉伸/Stretch」）。iOS 端缓存的缩略图 JPG 同样是原始宽高比。
- 文件系统 Tab：复用 `AfcBrowserPanel`，当前 `selectionMode` 为 `SingleSelection`，右键菜单仅针对单项；批量下载/删除需逐项点击。
- Ctrl+C：Qt 的 C++ 事件循环运行期间，Python 的默认 SIGINT 处理无法被及时执行，按 Ctrl+C 常表现为进程崩溃/异常退出，而非干净关闭。

约束：仅 macOS 桌面；不引入新第三方依赖；`AfcBrowserPanel` 同时被「App 列表」沙盒浏览与「文件系统」Tab 复用，改动需保持对前者无回归。

## Goals / Non-Goals

**Goals:**
- 相册缩略图统一为正方形居中裁剪（Crop）填充，无变形、无留边，网格观感一致。
- 文件系统 Tab 支持多选与右键批量「下载」「删除」，删除有一次汇总二次确认。
- Ctrl+C（SIGINT）触发应用干净退出（复用既有 `closeEvent` 清理路径），不崩溃。

**Non-Goals:**
- 不改相册的导出/删除/查看既有逻辑（仅改缩略图呈现）。
- 不为「App 列表」沙盒浏览强制开启多选（保持其单选默认；多选为「文件系统」Tab 行为）。
- 不实现自定义委托级别的动态裁剪绘制（采用「生成阶段裁成正方形」的简单方案）。
- 不改变 tunnel 退出询问的既有交互（SIGINT 复用同一清理路径即可）。

## Decisions

### 决策 1：缩略图在「生成/落地」阶段裁成正方形（Crop），而非渲染期委托裁剪
- 做法：缩略图统一产出 `_THUMB_PX × _THUMB_PX` 的**正方形**居中裁剪 JPEG：
  - 非 HEIC（`QImage`）：先 `scaled(side, side, KeepAspectRatioByExpanding, Smooth)` 放大到至少覆盖，再 `copy()` 居中裁剪到正方形。
  - HEIC（`pillow-heif`/PIL）：用 `ImageOps.fit((side, side))`（等价于按比例扩展并居中裁剪）。
  - 来自 iOS 端缓存的缩略图 JPG：读到字节后同样经上面的正方形裁剪流水线落地（不直接原样写入），保证两条来源观感一致。
- 同时把 `QListWidget` 的 `iconSize`/`gridSize` 设为基于正方形边长，图标即满格显示。
- **理由**：在生成阶段裁剪一次即可被缓存复用，渲染期零额外成本；相比自定义 `QStyledItemDelegate` 动态裁剪更简单、可缓存、无闪烁。
- **备选**：自定义委托在 `paint` 时按 `KeepAspectRatioByExpanding` 裁剪绘制——更灵活（可随网格尺寸变化重裁）但复杂、每次重绘有成本，本场景不需要。

### 决策 2：缓存失效需纳入「裁剪方式」维度，避免读到旧的非方形缓存
- 在缩略图缓存文件名（`_cache_filename`）的失效因子中加入一个裁剪策略版本标记（如 `c1`），使切到 Crop 后旧缓存自然失效、重建为正方形。
- **理由**：现有缓存按 `(size, mtime)` 失效，不会因「裁剪算法改变」而失效；不加版本标记会读到旧的非方形 JPEG。
- **备选**：升级时清空缓存目录——更暴力且影响其他设备缓存，不如版本标记精准。

### 决策 3：多选与右键批量操作只对「文件系统」Tab 开启
- 在 `AfcBrowserPanel` 增加可选构造参数 `multi_select: bool = False`：为真时表格用 `ExtendedSelection` 并在右键菜单中追加「批量下载到…」「批量删除…」（仅当选中多项或在多选模式下显示）。
- 「文件系统」Tab 传 `multi_select=True`；`AfcBrowserDialog`（App 沙盒）保持默认单选，行为不变。
- 批量下载：弹目录选择 → 逐项 `afc_pull` 到该目录（保持现有单项导出的字节/时间语义）；汇总成功/失败计数。
- 批量删除：一次汇总二次确认（数量 + 示例名）→ 逐项 `afc_rm` → 刷新。
- **理由**：最小侵入、复用既有单项逻辑；不回归「App 列表」沙盒浏览。
- **备选**：再抽一个子类——过度设计，一个布尔开关足够。

### 决策 4：用 QTimer 唤醒解释器 + signal handler 实现 SIGINT 干净退出
- 在 `app.py`：
  - 安装 `signal.signal(signal.SIGINT, handler)`，handler 内调用 `window.close()`（触发既有 `closeEvent` 清理）后 `app.quit()`。
  - 启动一个低频 `QTimer`（如 200ms，回调为空 `lambda: None`），让 Python 解释器有机会在 Qt C++ 循环运行时执行已挂起的信号处理函数。
- **理由**：Qt 运行时 C++ 栈不会主动驱动 Python 信号，周期性回到解释器是社区标准解法；复用 `closeEvent` 保证与正常关闭一致（含 tunnel 询问等）。
- **备选 A**：`signal.signal(SIGINT, SIG_DFL)` 恢复默认——能避免崩溃，但是硬退出，跳过清理（不停镜像线程/不询问 tunnel）。
- **备选 B**：`asyncio` loop 的 `add_signal_handler`——本应用主循环是 Qt 而非 asyncio，不适用。

## Risks / Trade-offs

- [居中裁剪丢失边缘内容] → Crop 是用户明确要求的观感；查看大图仍是完整图，缩略图裁剪可接受。
- [旧缓存读到非方形图] → 决策 2 的裁剪版本标记使旧缓存失效重建。
- [SIGINT 期间正处于设备授权/阻塞调用] → handler 走 `closeEvent`，与用户点关闭一致；后台线程按既有 `stop_stream`/`kbd_sender.stop` 收敛，最坏情况退出稍有延迟但不崩溃。
- [多选改动影响 App 沙盒浏览] → 通过 `multi_select` 开关隔离，默认关闭，沙盒路径不变；实现后回归 App 列表浏览。
- [Ctrl+C 与退出 tunnel 询问叠加] → 在终端无交互环境下询问框可能突兀；可接受（与点击关闭一致），必要时后续再细化。

## Migration Plan

1. 改 `dcim_album.py`：缩略图生成/落地统一裁正方形 + 缓存名加裁剪版本标记 + 网格 iconSize 调整。
2. 改 `afc_browser.py`：`AfcBrowserPanel` 增 `multi_select`，文件系统 Tab 传 True，加右键批量下载/删除。
3. 改 `app.py`：安装 SIGINT handler + 唤醒 QTimer。
4. 真机回归：相册缩略图为方形裁剪、文件系统多选批量下载/删除、Ctrl+C 干净退出；App 列表沙盒浏览无回归。

无需回滚特殊处理（纯客户端行为改动）。

## Open Questions

- 批量下载遇到重名是否覆盖/跳过/重命名？首版按现有单项导出语义（写入同名，存在则覆盖），后续可加策略。
