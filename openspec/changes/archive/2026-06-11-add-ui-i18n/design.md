## Context

- `slide6_ui` 是 PySide6 桌面端，文案全部硬编码简体中文：约 616 条含中文的字符串字面量，分布在 20 个 `.py` 文件。文案密集 Top：`keymouse/keymouse_tab.py`(94)、`developer_tools/developer_tools_tab.py`(93)、`common/afc_browser.py`(69)、`profiles/profiles_tab.py`(50)、`main_window.py`(47)。
- 约一半文案是 f-string，含 `{var}` 插值（如 `f"已成功挂载 DDI 到设备 {target}"`）。
- 设置由 `QSettings("ios_ui_ta_proxy", "slide6_console")` 单例承载，即时写回；Settings 已收敛为 `General` / `DeveloperDiskImage` 两标签（`main_window._open_preferences` / `_build_general_tab`）。
- 项目所有交互均「重启生效」，语言切换无需运行时 retranslate。
- 打包：`packaging/build_macos_app.sh` 两处 Nuitka 调用，已有 `--include-data-files` 先例（`ios_toolkit/ddi_image_index.json`）。`--include-package=slide6_ui` 只收 `.py`，不收包内数据文件。

## Goals / Non-Goals

**Goals:**
- 一套轻量 i18n：启动选定语言、按语义 key 取值、支持占位符插值、缺失回退。
- `slide6_ui` 全部展示文案改为按 key 取值，提供 `zh-CN` / `en-US` 两份 catalog。
- Settings/General 提供语言下拉，切换后持久化 + 重启生效。
- 语言文件随 Nuitka 打包进 app。

**Non-Goals:**
- 不引入 Qt `QTranslator` / `.ts` / `.qm`；不做运行时动态 retranslate。
- 不翻译 `ios_toolkit/toolkit_api` 层中文用户可见文案（本次范围外，已知限制）。
- 不做 web console 国际化；不新增除 en-US 外的语言。

## Decisions

### 1. key 方案：语义嵌套 key
- catalog 为嵌套 JSON，访问时用点路径 key，例如 `t("dev_tools.ddi.mounted")`、`t("keymouse.overlay.need_ddi")`。
- 顶层命名空间按模块/功能划分：`common` / `main_window` / `dev_tools` / `keymouse` / `profiles` / `crash` / `app_manager` / `device_info` / `file_system` / `album` / `syslog` 等，便于定位与避免冲突。
- `zh-CN.json` 是 catalog 全集（充当 key 清单的事实来源）；`en-US.json` 必须与之同构（key 集合一致）。

### 2. i18n 工具（`slide6_ui/i18n.py`）
- 模块级单例，**启动期初始化一次**：`init(lang: str | None)` 读取并展平 catalog 到 `{dotted_key: template}`。
- `lang` 解析顺序：显式入参 > `QSettings` 的 `settings/language` > 默认 `zh-CN`（**不跟随系统**，由用户手动切换）。仅接受 `{"zh-CN", "en-US"}`，非法值回退 `zh-CN`。
- 取值 API：
  - `t(key: str, /, **kwargs) -> str`：取当前语言模板；缺失则回退 `zh-CN`；仍缺失返回 `key` 本身（开发期暴露漏配）。有 `kwargs` 时执行 `template.format(**kwargs)`；`format` 失败（占位符不匹配）时记 warning 并返回未格式化模板，不崩溃。
- catalog 加载用标准库 `json`，路径用 `importlib.resources` / `Path(__file__).parent / "languages"`，保证开发态与 Nuitka 打包态都能定位。
- 无第三方依赖；`i18n.py` 不 import 任何 `slide6_ui` 子模块，避免循环依赖。

### 3. 占位符插值（f-string 改写）
- 凡 f-string 文案改写为：catalog 中存模板 `"已成功挂载 DDI 到设备 {target}"`，调用处 `t("dev_tools.ddi.mount_ok", target=target)`。`t()` 内部对模板执行 `template.format(**kwargs)`。
- 占位符一律用**具名**（`{target}`、`{count}`），禁止位置占位符 `{}`，保证两种语言可调换语序。数字/格式规格（`{pct:.1f}`、`{n:,}`）原样保留在模板里，由 `format` 处理。
- **翻译以完整句子为单位**：禁止把半句塞进 catalog 再用代码拼接。条件/状态拼接的文案重构为「整句模板按 key 分支」。示例：
  ```json
  { "dev_tools": { "ddi": {
    "mounted_ready":     "已挂载",
    "mounted_preparing": "已挂载（准备中...）",
    "mounted_timeout":   "已挂载（准备超时...）"
  } } }
  ```
  ```python
  key = "mounted_ready" if ready else ("mounted_timeout" if timed_out else "mounted_preparing")
  self._set_status(t(f"dev_tools.ddi.{key}"))
  ```
- 复数：本项目不引入完整复数规则引擎（ICU MessageFormat），用整句分支 key（`count_zero` / `count_one` / `count_many`）覆盖即可。
- **两份 catalog 同一 key 的占位符名集合 SHALL 完全一致**（如 zh-CN 用 `{target}`、en-US 也必须用 `{target}`，不得写成 `{device}`），由校验工具兜底（见决策 7）。

### 4. 语言选择 UI（Settings/General）
- 在 General 顶部（或配置文件 section 旁）加「语言 / Language」`QComboBox`：`简体中文` → `zh-CN`，`English` → `en-US`。
- 当前值读 `settings/language`（默认 `zh-CN`）。`currentIndexChanged` 时写回并 `QMessageBox` 提示「重启后生效 / Restart to apply」。不做运行时切换。

### 5. 启动初始化时机
- 在 `slide6_ui/app.py`（或 `main_window` 构造前的入口）`QApplication` 创建后、构建任何窗口前调用 `i18n.init()`，确保所有 UI 构造时 `t()` 已就绪。

### 6. 打包
- `packaging/build_macos_app.sh` 两处 Nuitka 调用各加：
  `--include-data-dir="$REPO_ROOT/slide6_ui/languages=slide6_ui/languages"`。

### 7. key 完整性 + 占位符一致性校验（开发期护栏）
- 增加一个轻量校验（脚本或 `i18n.py` 内 `validate()`）：
  - **key 集合对齐**：对比 `zh-CN` / `en-US` 的展平 key 集合，报告缺失/多余 key。
  - **占位符名一致性**：对每个共有 key，用 `string.Formatter().parse()` 提取两份模板的具名占位符集合并比对，提前暴露 `{target}` vs `{device}`、漏写占位符这类不一致。
- 迁移过程与 CI/手验时使用，降低漏翻与运行期 `format` 失败风险。

## Risks / Trade-offs

- **f-string 改写正确性**（最大风险）：参数遗漏或占位符拼写不一致会导致运行期文案错乱。缓解：`t()` 对 `format` 失败做降级（返回模板 + warning，不崩溃）；逐文件迁移并冒烟；key 完整性校验。
- **catalog 与代码漂移**：新增/改文案时漏更两份 JSON。缓解：`validate()` key 对齐校验；zh-CN 作为唯一 key 来源。
- **打包遗漏语言文件**：Nuitka 不自动收包内数据。缓解：显式 `--include-data-dir` + 打包后冒烟验证英文可加载。
- **范围边界**：toolkit 层中文文案仍会出现在状态栏等处，英文模式下混入中文。已明确为本次 Non-Goal，后续单独处理。
- **工作量大**：616 条 × 20 文件。缓解：tasks 按文件拆分，基础设施先行 + 逐文件迁移，每文件可独立验证。
