## Context

`web_console` 与 `slide6_console` 都消费 WDA 的 MJPEG broadcaster 来镜像设备画面，并通过 `toolkit_api.window_size(target)` 取得逻辑尺寸用于宽高比布局和"指针坐标 → 设备坐标"的映射。

现状问题：
- WDA 的 MJPEG broadcaster 默认按设备原生（竖屏）方向推送帧，帧像素始终接近竖屏宽高比；
- 而 `window/size` 按**当前**界面方向返回（横屏时 width > height）。

二者方向不一致，导致横屏时：画面被拉伸/挤压，且坐标映射（`fraction × window_size`）把竖屏画面里的点映射到横屏坐标空间，点按/滑动错位。两端目前都没有"获取屏幕方向"的能力。

约束：
- `executor_ios` 当前仅面向 macOS USB 真机（见平台契约），不在本次扩展平台范围。
- WDA 的 tap/swipe 坐标使用**当前方向**的点坐标空间（与 `window/size` 同一空间）。
- 不修改 `executor_ios` 既有公共契约的语义，仅新增接口。

## Goals / Non-Goals

**Goals:**
- 在 `toolkit_api` 暴露统一的"获取当前屏幕方向"接口，返回方向枚举与旋转角度。
- 两端按方向正确渲染视频流：画面朝向与设备一致、宽高比正确、横竖屏下手势坐标映射准确。
- 两端在选中设备后提供"刷新"按钮，动作等同于重新选中当前设备（设备旋转后用于手动重新同步）。

**Non-Goals:**
- 不做设备旋转的自动实时监听/推送（采用"手动刷新"重新同步，不引入轮询或事件订阅）。
- 不扩展平台支持（不涉及 Android/Simulator）。
- 不改变 WDA tap/swipe 的坐标契约。

## Decisions

### 决策 1：方向来源 —— WDA `GET /session/{sid}/rotation`（优先），`/orientation` 回退

> 真机修正：最初用 `GET /session/{sid}/orientation`，但它只返回粗粒度的 `PORTRAIT` / `LANDSCAPE`，无法区分两个横屏方向与倒置竖屏（四方向只显示出两种）。改为**优先** `GET /session/{sid}/rotation` 的 `z` 角（`0/90/180/270`，离散值，由 interface orientation 换算），失败再回退 `/orientation`。

`device.py` 新增方向查询方法（复用 `_get_with_session_retry` 与会话重建）；`toolkit_api.orientation(target)` 包装为统一信封：

```text
{ "ok": true, "data": { "orientation": "LANDSCAPE_LEFT", "degrees": 90 } }
```

- `z` 映射：`0→PORTRAIT(0)`、`90→LANDSCAPE_LEFT(90)`、`180→PORTRAIT_UPSIDE_DOWN(180)`、`270→LANDSCAPE_RIGHT(270)`；`z` 就近取整到 90 倍数。
- `orientation`：归一化枚举 `PORTRAIT | PORTRAIT_UPSIDE_DOWN | LANDSCAPE_LEFT | LANDSCAPE_RIGHT`。
- `degrees`：把竖屏帧旋转到当前方向的角度（0/90/180/270）。
- 错误语义与其它 `*-op` 一致（`SUBPROCESS` / `BAD_TARGET`），未知值/异常回退 `PORTRAIT`。

**备选**：仅用 `/orientation` 或 `window_size` 宽高比推断。**否决**：前者粒度不够（只有横/竖），后者无法区分 LANDSCAPE_LEFT/RIGHT 与 PORTRAIT/UPSIDE_DOWN。

### 决策 2：渲染策略 —— 客户端"按需旋转对齐 + letterbox"

> 真机修正：broadcaster 已自行把帧旋转到与当前方向一致的**宽高比**（横屏时帧本就是横的），但**不处理 180° 翻转**。因此规则定为：
> 1. 比较**帧宽高比**与 **`window_size` 宽高比**——**仅当不一致**才旋转 90/270（按 `degrees`，竖→横）；一致则不动。
> 2. 宽高比一致但属于"翻转"朝向（`PORTRAIT_UPSIDE_DOWN`）时额外 +180°（宽高比判断识别不出 180° 翻转）。

- web：`<img>` 渲染 MJPEG，旋转用 `transform: rotate()`（90/270 交换宽高盒子）；`object-fit: contain` 避免拉伸；`.phone` 宽高比随 `window_size`（当前方向）自动横屏。
- slide6：`ScreenView.on_frame` 收帧时按上述规则用 `QTransform` 旋转 `QPixmap`（90° 倍数无损转置），下游 `image_rect()`/绘制/坐标映射对"已正立 + 当前方向 window_size"均成立。

**为什么用客户端旋转而非服务端 `mjpegFixOrientation`**：服务端设置是 broadcaster 全局开关、不同 WDA 构建行为不一，且无法逐端控制；客户端通过"帧 vs window_size 宽高比"自检 + `orientation` 修正 180°，结果确定、两端复用同一逻辑。**备选**：开启 WDA `mjpegFixOrientation` 让服务端预旋转——作为后续可选优化。

### 决策 3：坐标映射保持映射到 `window_size`（当前方向）空间

旋转后，显示帧与 `window_size` 同方向，"指针 → 分数 → × window_size"的既有映射对横竖屏均成立，WDA tap/swipe 接收的就是当前方向坐标空间，无需额外逆变换。实现上仅需保证 `image_rect()`/触控区与旋转后的显示帧一致。

### 决策 4：刷新动作 = 复用"选中设备"逻辑

把"选中设备"的完整流程（`prepare → window_size → orientation → configure_mjpeg → 重连流`）抽成单一可复用函数：
- web：`onSelectDevice()` 已是该流程入口，新增的刷新按钮直接调用它（而非顶部的"刷新设备列表"`loadDevices`）。
- slide6：将 `_on_device_selected` 的核心抽为 `reselect_current_device()`，下拉变更与刷新按钮都走同一入口，并沿用 generation 计数丢弃过期回调。

刷新按钮仅在已选中设备时可用；点击时按重新选中处理（先停流再重建），天然覆盖"设备已旋转 → 重新取 orientation/window_size → 重渲染"。

### 决策 5：方向查询时机

在 `prepare` 成功后、开流前查询一次 `orientation`，与 `window_size` 同阶段获取（web 经 `/api/orientation`，slide6 在后台线程经 `toolkit_api.orientation`）。后续依赖刷新按钮重新同步，不做持续轮询。

## Risks / Trade-offs

- [方向在选中后改变导致画面/坐标过期] → 由刷新按钮重新同步；文档与提示明确"旋转后点刷新"。
- [WDA 返回的 orientation 取值在不同版本/机型存在差异（LANDSCAPE vs LANDSCAPE_LEFT）] → 在 `device.py` 做归一化映射，未知值回退为 PORTRAIT(0°) 并记录，避免崩溃。
- [客户端逐帧旋转的 CPU 开销（slide6 QImage 旋转）] → 仅横屏时旋转；旋转在后台/绘制阶段一次完成，配合既有"只渲染最新帧"丢帧策略，开销可控。
- [帧宽高比与 window_size 宽高比因缩放出现细微误差，自检误判] → 用"横/竖"二值判断（宽高比是否 > 1）而非精确比值，避免抖动。
- [orientation 查询失败] → 回退为 PORTRAIT 渲染（与当前行为一致），不阻断开流。
