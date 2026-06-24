> 状态：**已调研 / 不予实施（REJECTED）**。本文件保留调研过程与结论，供日后查阅，避免重复评估。

## Context（调研起点）

现状（`slide6_ui/keymouse/keyboard.py`）：

- `KeyboardCapture` 是一个 `QLineEdit`，**有意保留宿主 IME**：`inputMethodEvent` 跟踪组合态，组合中的击键交给输入法，组合完成的文本经 `send_keys`（WDA `/wda/keys` → `FBTypeText`，即 typeText）发送。
- 编辑键经 `key_event`（W3C key channel）、导航键与修饰组合键经 `key_chord`。
- `key_chord` 走 WDA `/wda/element/0/keyboardInput` → XCUIElement `typeKey:modifierFlags:`，是 iOS 上模拟「键盘命令」的通道；其无修饰单字符走字符串形式（直接传单个字符）。

最初设想：新增「原始按键模式」，逐键捕获并发送到设备，**由设备端 IME 组合中文**（敲 `n i h a o` 由 iOS 端拼音组合），像真实蓝牙硬件键盘。

## 结论：不可行（核心前提不成立）

iOS 键盘输入分层：**HID 层 → 硬件键盘/IME 组合层 → 文本输入层**。设备端 IME 的拼音组合引擎只挂在「硬件键盘」流水线上，且**只对真正从底层 HID 进入的输入做组合**。

WDA / XCUITest 的三条通道全部是**上层合成事件**，没有一条是底层 HID 注入：

| 通道 | WDA 端点 | XCUITest API | 能力 | 能否驱动设备端 IME 组合 |
| --- | --- | --- | --- | --- |
| `send_keys` | `/wda/keys` | `typeText:` | 批量文本插入 | 否（直接落字符） |
| `key_chord` | `/wda/element/0/keyboardInput` | `typeKey:modifierFlags:` | 键盘命令/单键 | **否**（绕过组合层，字母以字符插入落地） |
| `key_event` | `/session/.../actions` | W3C keyDown/keyUp | 编辑/导航键 | 否 |

因此：`typeKey` 能让 ⌘A 这类命令生效、也能把单字符敲进去，但它**绕过了 IME 组合层**——设备端拼音不会把注入的字母组合成中文。要实现「设备端 IME 组合」必须注入真正的 HID 键盘报文，iOS 无公开 API、USB/WDA 路径也拿不到。

## 剩余价值评估（不足以支撑实现）

- **中文（真正痛点）**：无解。宿主 IME 组合后发文本，几乎是 WDA 体系下 iOS 真机中文输入的唯一可行方式；「先组合再发送」是宿主 IME 固有行为，绕不过去。
- **英文 / 数字 / 符号**：现有「文本模式」已可正常输入，且 `send_keys` 是**批量**发送；逐键反而**每键一次 HTTP 往返、更慢**，是退步。
- **快捷键 / 组合键 / 导航键**：现有 `key_chord` / `key_event` 已覆盖。

## 重新评估的触发条件

仅当出现可用的**底层 HID 键盘注入**手段时（例如设备端配套组件、或新的 WDA 能力），才有必要重启本评估。届时需重新验证「注入字母能否被设备端拼音组合」。
