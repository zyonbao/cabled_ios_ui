## MODIFIED Requirements

### Requirement: 查询设备当前屏幕方向

`ios_toolkit.toolkit_api` SHALL 提供 `orientation(target)` 接口，返回设备当前屏幕方向。底层 SHALL **优先**通过 WDA `GET /session/{sid}/rotation` 的 `z` 角（`0/90/180/270`）解析完整四方向；当该接口不可用时 SHALL 回退 `GET /session/{sid}/orientation`。两者均复用既有会话准备与重建逻辑（必要时自动 `prepare`）。

返回 MUST 使用统一成功信封，`data` 至少包含：
- `orientation`：归一化方向枚举，取值 `PORTRAIT` | `PORTRAIT_UPSIDE_DOWN` | `LANDSCAPE_LEFT` | `LANDSCAPE_RIGHT`。
- `degrees`：把设备原生竖屏帧顺时针旋转到当前方向所需角度，取值 `0` | `90` | `180` | `270`。

#### Scenario: 竖屏

- **WHEN** 设备处于竖屏且调用 `orientation(target)`
- **THEN** 返回 `{ ok: true, data: { orientation: "PORTRAIT", degrees: 0 } }`

#### Scenario: 横屏

- **WHEN** 设备处于横屏且调用 `orientation(target)`
- **THEN** 返回成功信封，`orientation` 为 `LANDSCAPE_LEFT` 或 `LANDSCAPE_RIGHT`，`degrees` 为 `90` 或 `270`

#### Scenario: 四方向可区分

- **WHEN** 设备分别处于竖屏 / 横屏(左) / 横屏(右) / 倒置竖屏
- **THEN** `orientation` 能分别返回 `PORTRAIT` / `LANDSCAPE_LEFT` / `LANDSCAPE_RIGHT` / `PORTRAIT_UPSIDE_DOWN`（不因接口粒度退化为两种）
