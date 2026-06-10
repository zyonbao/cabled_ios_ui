# Tasks

## 1. Settings 窗口骨架（QTabWidget）

- [x] 1.1 `slide6_ui/main_window.py`：`_open_preferences` 重构为承载 `QTabWidget`，建 General / Logging / DeveloperDiskImage 三标签
- [x] 1.2 新增 DDI 相关 `QSettings` 键常量（`ddi_local_enabled` / `ddi_legacy_dir` / `ddi_modern_dir` / `ddi_github_enabled` / `ddi_github_token` / `ddi_github_save_dir` / `ddi_source_priority`）与读写辅助方法

## 2. General 标签

- [x] 2.1 迁移「Ask to clean XPC tunnel on exit」开关到 General 标签，沿用 `settings/ask_clean_tunnel_on_exit`

## 3. Logging 标签

- [x] 3.1 迁移启用开关 + 目录输入 + 浏览到 Logging 标签
- [x] 3.2 目录为空时占位文案改为「默认:~/Library/Logs/CablediOS」，移除"留空使用默认…"提示

## 4. DeveloperDiskImage 标签

- [x] 4.1 System Developer Image section：启用开关 + legacy 目录 + modern 目录（浏览/直填）；默认占位（legacy=Xcode DeviceSupport via `xcode-select -p`，modern=`/Library/Developer/CoreDevice/CandidateDDIs`）
- [x] 4.2 开关关闭时 section 内控件全部 disable 的联动
- [x] 4.3 GitHub Download Image section：启用开关 + Token（密码遮挡 + 说明文案）+ 保存目录（默认占位 `~/Library/CablediOS/DDI`）
- [x] 4.4 来源优先级 section：可上移/下移的有序列表（默认 local 在前），禁用来源联动 disable，两来源均禁用时整体 disable + 提示
- [x] 4.5 确认 Token 等敏感值不写入任何日志（脱敏自检）

## 5. 验证

- [x] 5.1 lint 无误 + 导入冒烟（含 offscreen 构建 + 开关联动 + 优先级排序自动化验证）
- [ ] 5.2 桌面手验：三标签切换；各项写入/重启沿用；section 开关联动 disable；目录占位展示默认路径
- [ ] 5.3 回归：General 退出清理隧道行为、Logging 即时生效行为不受影响
