# 复制 / 拷贝 文案审计

目的：梳理全工程中所有"复制（copy）"相关文案，区分其**真实意图**，便于在中文语境下统一用词（拷贝 vs 复制）。本文档仅做盘点与建议，**不改代码**；后续按本文档逐项修改。

> 数据来源：`slide6_ui/languages/zh-CN.json`、`en-US.json` 及调用方代码。截至 2026-06-25。

---

## 一、用词约定（待确认）

工程里目前所有 "copy" 文案，本质上**只有一种操作**：把"已有文本"写入**本机系统剪贴板**（`QApplication.clipboard().setText`）。不存在"复制条目 / 生成副本（duplicate）"这类操作。因此区分点不在功能，而在**语境来源**：

- **A 类 · 本地拷贝**：把界面上**已显示**的文本（列表单元格、日志行）放进本机剪贴板，等同 Ctrl+C。
- **B 类 · 设备→本机搬运**：把从**设备剪贴板 / 设备 UI** 读取到的内容放进本机剪贴板。
- **C 类 · 设备端用户动作**：描述用户**在 iOS 设备上**执行的剪贴板复制。

> 关键参考：本工程面向 iOS。Apple 中文本地化统一使用 **「拷贝」/「粘贴」**（而非"复制/粘贴"）。若希望与设备原生 UI 一致，C 类**应为「拷贝」**；A/B 类是否统一为「拷贝」由团队决定。

**建议方案（待团队拍板，确定后据此改下表"建议"列）：**

| 类别 | 操作 | 建议用词 |
|---|---|---|
| A | 本地把已显示文本入剪贴板 | 拷贝 |
| B | 设备/UI 内容搬到本机剪贴板 | 拷贝（动作）/ 复制（描述搬运过程）二选一 |
| C | 设备端用户的剪贴板动作 | **拷贝**（对齐 iOS 原生） |

---

## 二、全量盘点

### A 类 · 本地拷贝（界面已显示文本 → 本机剪贴板）

| key | 当前 zh | 当前 en | 用途 / 调用方 | 建议 |
|---|---|---|---|---|
| `common.copy_value` | 复制值 | Copy value | 列表/表格右键菜单。调用方：crash、app_manager、profiles、device_info、process_dialog、tunnel_manager、syslog | 拷贝值 |
| `common.copy_line` | 复制本行 | Copy line | 纯文本日志右键菜单（syslog、tunnel_manager、diagnostics） | 拷贝本行 |
| `common.copied` | 已复制: {text} | Copied: {text} | 拷贝成功后的状态提示（多页共用） | 已拷贝: {text} |
| `device_info.copied` | 已复制: {text} | Copied: {text} | 设备信息页拷贝提示。**与 `common.copied` 完全重复** | 见"查漏补缺①" |

### B 类 · 设备 → 本机搬运

| key | 当前 zh | 当前 en | 用途 | 建议 |
|---|---|---|---|---|
| `keymouse.pb_copy_to_host` | 复制到本机 | Copy to Host | 设备剪贴板查看弹窗里的按钮 | 待定（拷贝/复制） |
| `keymouse.pb_copied` | 已复制到本机剪贴板 | Copied to host clipboard | 上述按钮 / auto-copy 成功提示 | 待定 |
| `settings.keymouse.auto_copy.group` | 读取后复制到本机 | Copy to Host After Reading | 设置项分组标题 | 待定 |
| `settings.keymouse.auto_copy.pasteboard` | 读取设备剪贴板后不弹窗，直接复制到本机系统剪贴板 | After reading the device clipboard, skip the dialog and copy straight to the host clipboard | 设置项说明 | 待定 |
| `settings.keymouse.auto_copy.ui_xml` | 获取 UI XML 后不弹窗，直接复制到本机系统剪贴板 | After fetching the UI XML, skip the dialog and copy straight to the host clipboard | 设置项说明 | 待定 |

### C 类 · 设备端用户动作（混在其它文案里）

| key | 当前 zh | 片段 | 建议 |
|---|---|---|---|
| `keymouse.pb_empty_detail` | 剪贴板为空或为非文本内容，无法显示/复制\n（请确认设备上已复制文本） | "设备上已**复制**文本" 指用户在 iOS 上的动作 | 对齐 iOS → "已**拷贝**文本" |

---

## 三、查漏补缺

1. **`device_info.copied` 与 `common.copied` 完全重复**（值都是 `已复制: {text}`）。
   - 设备信息页已统一走共享右键菜单，建议删除 `device_info.copied`，改用 `common.copied`，避免两处文案漂移。
   - 涉及代码：[device_info.py:_flash_copied](slide6_ui/device_info/device_info.py)。

2. **`pb_empty_detail` 一句话里混了两种语境**："无法显示/复制"（A/B 类，本机侧）与"设备上已复制文本"（C 类，设备侧）。统一用词时需拆开判断，二者可能用不同词。

3. **拷贝 ↔ 粘贴 应成对**。若 A/C 类定为「拷贝」，则与之对应的「粘贴」文案（如 `keymouse.pb_*` 设置设备剪贴板流程、`gpx_placeholder` 的"粘贴"）措辞已是「粘贴」，方向一致，无需改；仅需确认不要出现"复制…粘贴"的混搭。

4. **设备剪贴板 set/get 文案本身不含"复制"**（`set_pasteboard`=设置剪贴板、`get_pasteboard`=读取剪贴板、`pb_set_ok` 等），属另一概念（设备剪贴板读写），本次不动，仅记录边界。

5. **代码注释**中有两处硬编码中文提示文字 `# flashes "已复制到本机"`（[keymouse_tab.py:1267](slide6_ui/keymouse/keymouse_tab.py#L1267)、[1325](slide6_ui/keymouse/keymouse_tab.py#L1325)），改 B 类文案后注释需同步。

---

## 四、改动清单（确认约定后执行）

- [ ] 团队确定 A/B/C 各类最终用词（填回第二节"建议"列）。
- [ ] 按确定用词批量改 `zh-CN.json`（A 类 3 条 + B 类 5 条 + C 类 1 条）。
- [ ] 删除重复的 `device_info.copied`，调用方改用 `common.copied`（查漏①）。
- [ ] 同步两处代码注释（查漏⑤）。
- [ ] 英文 `en-US.json` 无歧义（copy / Copied），通常无需改；如团队要求术语表统一再议。
- [ ] 自查：改完后全局再次 grep `复制`，确认只剩有意保留的。
