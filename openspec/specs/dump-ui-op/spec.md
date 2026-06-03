## ADDED Requirements

### Requirement: 导出 UI 树并转换为统一 selector 格式
系统 SHALL 通过 WDA `GET /source?format=xml` 获取 UI 层级树，将 XML 原文存入 `raw` 字段，并将每个元素解析为含以下 8 个字段的 selector：`resourceId`（←`name`）、`text`（←`label`）、`contentDesc`（←`value`）、`class`（←`type`）、`bounds`（←坐标计算）、`clickable`（推断）、`enabled`（←`enabled`）、`visible`（←`visible`）。

#### Scenario: dump_ui 成功返回 raw 和 selectors
- **WHEN** 以有效 UDID 调用 `dump_ui(target)`，WDA 正在运行
- **THEN** 返回 `{"ok": true, "data": {"rawMime": "application/xml", "raw": "<xml string>", "selectors": [...]}}` 其中 selectors 中每条均包含全部 8 个字段

#### Scenario: 所有缺失字段使用默认值
- **WHEN** WDA 返回的 XML 中某元素缺少 `name`、`label` 等属性
- **THEN** 对应 selector 中该字段使用默认值（字符串字段为空字符串，布尔字段为 `false`）

### Requirement: selector 去重和数量上限
系统 SHALL 对相同 `resourceId + bounds` 组合只保留一条，且 selectors 总数不超过 200 条，超出时截断。

#### Scenario: 重复元素被去重
- **WHEN** WDA 返回的 XML 中存在多个 `name` 和 `bounds` 完全相同的元素
- **THEN** 结果 selectors 中该组合只出现一次

#### Scenario: 超过 200 条时截断
- **WHEN** WDA 返回的 XML 中元素数量超过 200 条（去重后）
- **THEN** selectors 长度 ≤ 200，超出部分被截断

### Requirement: bounds 格式转换
系统 SHALL 将 XML 中元素的 `x`、`y`、`width`、`height` 属性转换为 `"[x1,y1][x2,y2]"` 格式，其中 `x2 = x + width`，`y2 = y + height`。

#### Scenario: bounds 正确转换
- **WHEN** XML 元素有 `x="10" y="20" width="100" height="50"`
- **THEN** 对应 selector 的 `bounds` 为 `"[10,20][110,70]"`
