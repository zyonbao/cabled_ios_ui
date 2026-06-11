# Tasks

## 1. 状态行间距收紧

- [x] 1.1 `_build_ui`：将 `tunnel_widget` 内部布局 `setContentsMargins(0,0,0,0)`，并对 `root`（`QVBoxLayout`）设定统一且较小的 `setSpacing(6)`，使 DDI 行与 Tunnel 行间距收紧、自然、一致
- [x] 1.2 目视核对：iOS17+（显示 Tunnel 行）与 iOS<17（隐藏 Tunnel 行）两种情形下行距均自然，无多余空隙（headless 校验 root spacing=6；隐藏行不增加额外空隙）

## 2. 功能位卡片标题/描述分层

- [x] 2.1 新增 `_FeatureTile(QToolButton)` 子类卡片，内嵌 `QVBoxLayout` + 两个 `QLabel`（title 加粗/+2pt、subtitle -1pt/次要色且 `setWordWrap(True)`）；子 `QLabel` 设 `Qt.WA_TransparentForMouseEvents` 使点击穿透；`_make_tile` 改用该类
- [x] 2.2 保留卡片对外接口与门控：`.clicked` / `.setEnabled` / `.setToolTip` 与 `_feature_buttons` 行为不变；禁用态下子标签随父弱化
- [x] 2.3 syslog 卡片同步改造：`partition("\n")` 拆出标题/描述，复用 `_FeatureTile` 同样式

## 3. 验证

- [x] 3.1 字节编译通过；headless（offscreen）构造 Tab 不崩溃，zh-CN/en-US 下校验 root spacing=6、卡片为 `_FeatureTile` 且标题加粗、描述为次要态、syslog 标题/描述拆分正确
- [ ] 3.2 手验（待真机/带屏运行）：卡片标题/描述层级清晰；点击进程/定位/syslog 仍正常打开；门控禁用态下不可点且视觉弱化
