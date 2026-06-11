## Context

`DeveloperToolsTab._build_ui`（`slide6_ui/developer_tools/developer_tools_tab.py`）当前：

- DDI 行以 `root.addLayout(ddi_row)` 直接加入 `root`（`QVBoxLayout`）；XPC Tunnel 行先放进一个 `QHBoxLayout`，再包进 `tunnel_widget = QWidget()` 后 `root.addWidget(...)`。该包装器用于整行 `setVisible(False)`（iOS<17 隐藏）。包装器带 Qt 平台默认内边距（约 9–11px），叠加 root 的默认 spacing，使两行间距明显大于普通行间距，显得松散。
- 功能位卡片由 `_make_tile(title, subtitle)` 生成：`QToolButton` + `setText(f"{title}\n{subtitle}")` + `ToolButtonTextOnly`。标题与描述同字体同字号拼接，无视觉层级；syslog 卡片同样仅 `setText(...)`。门控逻辑依赖 `QToolButton` 的 `.clicked` / `.setEnabled` / `.setToolTip` 以及 `_feature_buttons` 列表。

## Goals / Non-Goals

**Goals:**

- 收紧并统一两条状态行之间的纵向间距，使其更小、更自然、与其它行一致。
- 功能位卡片标题与描述分层呈现：标题更突出（更大/加粗），描述更弱（更小/次要色），提升辨识度。

**Non-Goals:**

- 不改变功能位门控逻辑、点击行为、异步调用与就绪检查。
- 不调整 i18n 文案键（标题/描述沿用既有 `dev_tools.tile.*`）。
- 不引入新依赖、不做主题/换肤系统。

## Decisions

### 决策 1：间距——去掉包装器多余内边距 + 统一 root 间距

保留 `tunnel_widget` 包装器（整行显隐切换仍需要它），但将其内部布局 `setContentsMargins(0, 0, 0, 0)`，并对 `root` 设定统一且较小的 `setSpacing(...)`（以及必要时显式 `setContentsMargins`），使 DDI 行与 Tunnel 行间距与普通行一致、收紧自然。

- 备选：把 Tunnel 行也用 `addLayout` 直接加入（去掉 QWidget）。否决——会失去对整行的 `setVisible` 单点控制，需要逐控件显隐，改动更大且更易出错。

### 决策 2：卡片——`QToolButton` 子类内嵌两个 `QLabel`

`QToolButton` 的 `setText` 无法对标题/描述分别设样式。改为一个 `QToolButton` 子类卡片：内部 `QVBoxLayout` 承载两个 `QLabel`（title：加粗/较大；subtitle：较小/次要色，`setWordWrap(True)`），子 `QLabel` 设 `Qt.WA_TransparentForMouseEvents` 让点击穿透到按钮本身。

- 这样保留现有 `.clicked` / `.setEnabled` / `.setToolTip` 接口与 `_feature_buttons` 门控不变，改动局限在 `_make_tile` 与 syslog 卡片构造处。
- 样式用代码内 `QFont`/`setStyleSheet` 表达层级（标题 bold + 略大、描述 disabled/secondary 色），不引入全局样式表。
- 备选 A：`QToolButton` 富文本（`setText` + HTML）。否决——`QToolButton` 对富文本渲染支持差、跨平台不稳定。
- 备选 B：完全替换为自定义 `QFrame` 卡片并自管点击。否决——需重写门控/信号接线，改动面更大。

## Risks / Trade-offs

- [子 `QLabel` 拦截点击导致卡片点不动] → 给两个 `QLabel` 设 `WA_TransparentForMouseEvents`，并验证 `clicked` 仍触发、禁用态下不可点。
- [禁用态下标题/描述颜色不变灰，视觉与可用态混淆] → 标题/描述颜色尽量走调色板（如 disabled/secondary role），或在 `setEnabled` 联动时刷新样式，保证禁用态有明显弱化。
- [间距改动影响整体观感] → 仅调整两状态行与 root 间距的具体数值，目视核对收紧后自然一致即可，不连带改动卡片网格的行/列间距策略。

## Migration Plan

1. 调整 `_build_ui`：`tunnel_widget` 布局零内边距；`root` 统一较小 spacing。
2. 重写 `_make_tile` 为「标题/描述分层」的可点击卡片；syslog 卡片同步改造为同样的双标签样式。
3. 目视冒烟：iOS17+ 设备（显示 tunnel 行）与 iOS<17（隐藏 tunnel 行）两种情形下行距自然；卡片标题/描述层级清晰；点击与禁用门控行为不变。
4. 回滚：还原 `_build_ui` 与 `_make_tile` 即可（纯展示层、无数据/接口变更）。

## Open Questions

（无）
