# 新增「主机配对（Pair / Unpair）」功能

## Why

- 几乎所有 lockdown 服务（应用安装、AFC 文件、崩溃日志、描述文件、DDI/DVT、WDA、诊断）都依赖一条**有效的主机配对记录**。此前工具没有任何「配对状态检测 / 主动配对 / 取消配对」入口。
- 当设备未配对（未信任本机）时，各 tab 会直接对依赖配对的服务发起请求并抛出 `NotPairedError`，用户看不到明确原因，只看到一堆失败与报错。
- 设备配对状态需要在选择设备后清晰呈现，并对依赖配对的功能做前置门控——与「诊断」缺少 XPC tunnel 时盖蒙版提示的处理保持一致。

需要一个集中的配对入口：检测配对状态、发起配对（触发设备端「信任此电脑」）、取消配对，并据此门控其余功能。

## What Changes

- 在顶栏设备下拉框右侧新增一个**配对按钮**：
  - 已配对显示「取消配对」，点击后二次确认再 unpair。
  - 未配对显示「配对」，点击后发起 pair，设备弹出「信任此电脑」。
  - 探测中显示「检查配对中…」并禁用。
- 选择设备后**异步探测**配对状态，并据此门控：所有依赖配对的 tab（除「设备信息」外）在未配对时由一个共享**蒙版**覆盖并给出提示；只有确认配对后才真正加载这些 tab。
- 设备列表项只显示设备标识（有名称时为 `名称 (UDID)`，否则 `UDID`），不再展示 model / 「未安装WDA」等易误导信息。
- toolkit 新增 `pairing_state` / `pair_device` / `unpair_device` 三个同步接口，底层基于 `pymobiledevice3` 的 lockdown 能力实现。
- 记录并规避本次实现遇到的若干 `pymobiledevice3` / 环境坑（见 design.md 与 spec），保证配对稳定可用。

## Impact

- Affected specs:
  - 新增 `slide6-host-pairing`（顶栏配对按钮、配对状态探测与广播、共享配对蒙版、依赖配对的 tab 门控）。
  - 新增 `host-pairing-op`（toolkit 层 `pairing_state` / `pair` / `unpair` 行为与健壮性约束）。
  - 修改 `device-discovery`（设备列表项标识展示去除 model / WDA 后缀；WDA 安装探测仅在已配对时进行）。
- Affected code:
  - `ios_toolkit/device.py`：新增 `_open_lockdown_no_autopair` / `_clear_unwritable_pair_cache` / `_probe_paired_async` / `pairing_state` / `pair` / `unpair`；自定义配对记录目录常量 `_PAIRING_RECORDS_DIR`。
  - `ios_toolkit/toolkit_api.py`：新增 `pairing_state` / `pair_device` / `unpair_device` 包装；`list_targets` 未配对时跳过 WDA 探测。
  - `slide6_ui/main_window.py`：顶栏配对按钮、配对探测/广播、共享配对蒙版、依赖配对 tab 的门控加载（`_apply_gated_targets`）。
  - `slide6_ui/keymouse/keymouse_tab.py`：延迟（非活动）选择设备时不再劫持共享顶栏状态。
  - `slide6_ui/languages/zh-CN.json` / `en-US.json`：新增配对相关文案键。
- 不改变已配对设备下各功能的既有行为；本功能是其前置入口与门控。
