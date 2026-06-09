"""main_window.py — the slide6_console main window and device lifecycle.

Wires the device picker, tunnel bootstrap, WDA preparation, live screen mirror,
mouse gestures, keyboard mirroring, and device action buttons together. All
blocking executor_ios calls go through AsyncRunner; the live mirror runs in its
own thread (see mirror.py).
"""

from __future__ import annotations

import base64
import os
import sys
from datetime import datetime

from PySide6.QtCore import QBuffer, QIODevice, QSettings, QStandardPaths, Qt
from PySide6.QtGui import QAction, QImage, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from executor_ios import toolkit_api as api

from . import tunnel
from .app_manager import AppManagerTab
from .device_info import DeviceInfoTab
from .keyboard import KeyboardCapture, KeyboardSender
from .mirror import MjpegThread, ScreenView
from .sidebar_tabs import SidebarTabs
from .workers import AsyncRunner

# Opt-in lifecycle tracing: set SLIDE6_DEBUG=1 to print device-lifecycle steps.
_DEBUG = os.environ.get("SLIDE6_DEBUG", "").strip().lower() not in ("", "0", "false", "no")


def _dbg(message: str) -> None:
    # Lightweight stderr trace for real-device debugging of the device lifecycle.
    if _DEBUG:
        print(f"[slide6 {datetime.now():%H:%M:%S}] {message}", file=sys.stderr, flush=True)


_FPS_CHOICES = [5, 10, 15, 20]
_DEFAULT_FPS = 10
_MJPEG_SCALING = 60
_MJPEG_QUALITY = 70
_SETTINGS_ORG = "ios_ui_ta_proxy"
_SETTINGS_APP = "slide6_console"
_ASK_CLEAN_TUNNEL_ON_EXIT_KEY = "settings/ask_clean_tunnel_on_exit"

_ORIENT_LABEL = {
    "PORTRAIT": "竖屏",
    "PORTRAIT_UPSIDE_DOWN": "竖屏（倒置）",
    "LANDSCAPE_LEFT": "横屏（左）",
    "LANDSCAPE_RIGHT": "横屏（右）",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CablediOS")
        self.resize(1100, 820)

        self.settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self.runner = AsyncRunner()
        self.devices: dict = {}
        self.target = ""
        self.win_size: dict | None = None
        self.orientation: dict = {"orientation": "PORTRAIT", "degrees": 0}
        self.fps = _DEFAULT_FPS
        self.mirror_thread: MjpegThread | None = None
        self.kbd_on = False

        self._build_ui()
        self._build_menu()
        self._wire()
        self.load_devices()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        # Top bar: device picker / refresh / status. The top bar is shared across
        # tabs; detailed device info now lives in the "设备信息" tab and the fps
        # control lives in the key/mouse tab.
        top = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(320)
        self.refresh_btn = QPushButton("刷新")
        self.status_label = QLabel("未连接")
        top.addWidget(QLabel("设备"))
        top.addWidget(self.device_combo)
        top.addWidget(self.refresh_btn)
        top.addStretch(1)
        top.addWidget(self.status_label)
        root.addLayout(top)

        # Tabbed body: key/mouse control + app manager + device info. Tabs run
        # down the left side (vertical column, horizontal labels) via SidebarTabs.
        self.tabs = SidebarTabs()
        self.device_info_tab = DeviceInfoTab(self.runner, lambda: self.target)
        self.tabs.addTab(self.device_info_tab, "设备信息")
        self.keymouse_tab = self._build_keymouse_tab()
        self.tabs.addTab(self.keymouse_tab, "键鼠操作")
        self.app_tab = AppManagerTab(self.runner, lambda: self.target)
        self.tabs.addTab(self.app_tab, "App 列表")
        root.addWidget(self.tabs, stretch=1)

        self.setCentralWidget(central)

        # Keyboard sender worker (started lazily on first enable).
        self.kbd_sender = KeyboardSender(self)

    def _build_keymouse_tab(self) -> QWidget:
        tab = QWidget()
        center = QHBoxLayout(tab)
        self.screen = ScreenView()
        center.addWidget(self.screen, stretch=1)

        # Right-side operation area: a fixed-width container so its background
        # box does not stretch/collapse with the mirror view.
        sidebar_box = QWidget()
        sidebar_box.setFixedWidth(260)
        sidebar = QVBoxLayout(sidebar_box)
        sidebar.setContentsMargins(8, 0, 0, 0)

        # Non-interactive device info first (read-only): resolution / orientation.
        info_box = QWidget()
        info = QFormLayout(info_box)
        self.info_size = QLabel("—")
        self.info_orient = QLabel("—")
        info.addRow("分辨率(点)", self.info_size)
        info.addRow("方向", self.info_orient)
        sidebar.addWidget(info_box)

        # Interactive controls below the read-only info: fps (moved off the top bar).
        fps_row = QWidget()
        fps_layout = QHBoxLayout(fps_row)
        fps_layout.setContentsMargins(0, 0, 0, 0)
        self.fps_combo = QComboBox()
        for f in _FPS_CHOICES:
            self.fps_combo.addItem(f"{f} fps", f)
        self.fps_combo.setCurrentText(f"{_DEFAULT_FPS} fps")
        fps_layout.addWidget(QLabel("帧率"))
        fps_layout.addWidget(self.fps_combo, 1)
        sidebar.addWidget(fps_row)

        self.home_btn = QPushButton("主屏幕 (HOME)")
        self.switcher_btn = QPushButton("应用切换 (后台)")
        self.reload_btn = QPushButton("刷新画面 / 方向")
        self.kbd_btn = QPushButton("键盘输入: 关")
        self.shot_btn = QPushButton("截图并保存")
        for btn in (self.home_btn, self.switcher_btn, self.reload_btn):
            btn.setEnabled(False)
            sidebar.addWidget(btn)

        # Keyboard area: the toggle button and the active-capture row share the
        # same slot. When keyboard mirroring is on, the button is hidden and the
        # capture field + exit (✕) button take its place; toggling off restores
        # the button.
        self.kbd_btn.setEnabled(False)
        sidebar.addWidget(self.kbd_btn)

        self.kbd_capture = KeyboardCapture()
        self.kbd_close_btn = QPushButton("✕")
        self.kbd_close_btn.setToolTip("退出键盘输入")
        self.kbd_close_btn.setFixedWidth(36)
        self.kbd_active_row = QWidget()
        kbd_row = QHBoxLayout(self.kbd_active_row)
        kbd_row.setContentsMargins(0, 0, 0, 0)
        kbd_row.addWidget(self.kbd_capture, 1)
        kbd_row.addWidget(self.kbd_close_btn)
        self.kbd_active_row.setVisible(False)
        sidebar.addWidget(self.kbd_active_row)

        self.shot_btn.setEnabled(False)
        sidebar.addWidget(self.shot_btn)

        # Text send row: a standalone field + send button, independent of the
        # keyboard-mirroring capture above.
        self.send_input = QLineEdit()
        self.send_input.setPlaceholderText("输入文本后发送到设备")
        self.send_input.setEnabled(False)
        self.send_btn = QPushButton("发送")
        self.send_btn.setEnabled(False)
        send_row = QWidget()
        send_layout = QHBoxLayout(send_row)
        send_layout.setContentsMargins(0, 0, 0, 0)
        send_layout.addWidget(self.send_input, 1)
        send_layout.addWidget(self.send_btn)
        sidebar.addWidget(send_row)

        # Pasteboard buttons.
        self.set_pb_btn = QPushButton("设置剪贴板")
        self.get_pb_btn = QPushButton("读取剪贴板")
        for btn in (self.set_pb_btn, self.get_pb_btn):
            btn.setEnabled(False)
            sidebar.addWidget(btn)

        sidebar.addStretch(1)
        center.addWidget(sidebar_box)
        return tab

    def _build_menu(self) -> None:
        settings_menu = self.menuBar().addMenu("Settings")
        self.preferences_action = QAction("Preferences...", self)
        settings_menu.addAction(self.preferences_action)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(self.load_devices)
        self.device_combo.activated.connect(self.on_select_device)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.fps_combo.activated.connect(self.on_fps_changed)
        self.home_btn.clicked.connect(self.on_home)
        self.switcher_btn.clicked.connect(self.on_switcher)
        # Per-device refresh: re-run the full select flow for the current device.
        self.reload_btn.clicked.connect(self.on_select_device)
        self.kbd_btn.clicked.connect(self.on_toggle_keyboard)
        self.kbd_close_btn.clicked.connect(lambda: self._set_keyboard(False))
        self.shot_btn.clicked.connect(self.on_screenshot)
        self.send_btn.clicked.connect(self.on_send_text)
        self.send_input.returnPressed.connect(self.on_send_text)
        self.set_pb_btn.clicked.connect(self.on_set_pasteboard)
        self.get_pb_btn.clicked.connect(self.on_get_pasteboard)

        self.screen.tap.connect(self.on_tap)
        self.screen.long_press.connect(self.on_long_press)
        self.screen.swipe.connect(self.on_swipe)
        self.screen.gesture_finished.connect(self._refocus_keyboard)

        self.kbd_capture.text_typed.connect(self.kbd_sender.enqueue_text)
        self.kbd_capture.key_pressed.connect(self.kbd_sender.enqueue_key)
        self.kbd_capture.chord.connect(self.kbd_sender.enqueue_chord)
        self.kbd_sender.failed.connect(lambda m: self._flash(f"输入失败: {m}"))
        self.preferences_action.triggered.connect(self._open_preferences)

    # -------------------------------------------------------------- status

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _flash(self, message: str) -> None:
        self._set_status(message)

    def _ask_clean_tunnel_on_exit(self) -> bool:
        value = self.settings.value(_ASK_CLEAN_TUNNEL_ON_EXIT_KEY, True, type=bool)
        return bool(value)

    def _set_ask_clean_tunnel_on_exit(self, enabled: bool) -> None:
        self.settings.setValue(_ASK_CLEAN_TUNNEL_ON_EXIT_KEY, enabled)

    def _open_preferences(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Preferences")
        layout = QVBoxLayout(dlg)

        general_box = QWidget(dlg)
        general = QVBoxLayout(general_box)
        general.setContentsMargins(0, 0, 0, 0)
        general.addWidget(QLabel("General"))

        ask_clean_checkbox = QCheckBox("Ask to clean XPC tunnel on exit", general_box)
        ask_clean_checkbox.setChecked(self._ask_clean_tunnel_on_exit())
        ask_clean_checkbox.toggled.connect(self._set_ask_clean_tunnel_on_exit)
        general.addWidget(ask_clean_checkbox)
        layout.addWidget(general_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, dlg)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)

        dlg.resize(360, 140)
        dlg.exec()

    # --------------------------------------------------------- device list

    def load_devices(self) -> None:
        self._set_status("正在扫描设备…")
        self.runner.submit(api.list_targets, on_done=self._on_devices,
                           on_error=lambda e: self._set_status(f"设备列表加载失败: {e}"))

    def _on_devices(self, result: dict) -> None:
        if not result.get("ok"):
            self._set_status("设备列表加载失败")
            return
        targets = result["data"].get("targets", [])
        prev = self.target
        self.devices = {}
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("— 选择设备 —", "")
        for t in targets:
            self.devices[t["id"]] = t
            wda = "" if t.get("state") == "online" else "（未装 WDA）"
            model = (t.get("metadata") or {}).get("model", "")
            label = f"{t.get('name') or t['id']}  {model} {wda}".strip()
            self.device_combo.addItem(label, t["id"])
        if prev and prev in self.devices:
            idx = self.device_combo.findData(prev)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
        self.device_combo.blockSignals(False)
        self._set_status(f"发现 {len(targets)} 台设备")
        if not targets:
            self.screen.set_overlay("未检测到 USB 设备\n请连接并信任后点击刷新")

    # ---------------------------------------------------- device selection

    def on_select_device(self) -> None:
        gen = self.runner.bump_generation()
        self.stop_stream()
        target = self.device_combo.currentData()
        self.target = target or ""
        self.win_size = None
        self.orientation = {"orientation": "PORTRAIT", "degrees": 0}
        self.screen.set_window_size(0, 0)
        self.screen.set_orientation(0)
        self.info_orient.setText("—")
        # App management / device info work without WDA/tunnel, so refresh those
        # tabs for any selected device (they clear when no device is selected).
        self.app_tab.set_target(self.target)
        self.device_info_tab.set_target(self.target)
        # Device info is the default landing tab on selection; the user opts into
        # the key/mouse tab to pay the WDA/mirror startup cost.
        if self.target:
            self.tabs.setCurrentWidget(self.device_info_tab)

        if not self.target:
            self._fill_info(None)
            self._set_status("未连接")
            self.screen.set_overlay("请选择一个设备")
            return

        dev = self.devices.get(self.target)
        self._fill_info(dev)
        if not dev or dev.get("state") != "online":
            self._set_status("该设备未安装 WDA")
            self.screen.set_overlay("该设备未安装 WebDriverAgent (WDA)\n无法镜像或控制此设备")
            return

        # WDA / mirror startup is costly and only the key/mouse tab needs it.
        # Defer it until that tab is active (start now if it already is).
        if self._on_keymouse_tab():
            self._start_mirror_flow(gen)
        else:
            self._set_status("已选择设备")
            self.screen.set_overlay("切换到「键鼠操作」标签以启动镜像与控制")

    def _on_keymouse_tab(self) -> bool:
        return self.tabs.currentWidget() is self.keymouse_tab

    def _on_tab_changed(self, _index: int) -> None:
        if self._on_keymouse_tab():
            # Entering: lazily start the WDA / mirror flow for a connected,
            # not-yet-streaming device.
            if not self.target or self.mirror_thread is not None:
                return
            dev = self.devices.get(self.target)
            if not dev or dev.get("state") != "online":
                return
            gen = self.runner.bump_generation()
            self._start_mirror_flow(gen)
        else:
            # Leaving: stop mirroring and the WDA runner to free the device.
            self._teardown_mirror()

    def _teardown_mirror(self) -> None:
        # Bump generation so any in-flight prepare/tunnel callbacks are dropped.
        self.runner.bump_generation()
        self.stop_stream()
        target = self.target
        if target:
            self.runner.submit(
                lambda: api.stop_wda(target),
                on_error=lambda e: _dbg(f"stop_wda error: {e}"),
            )
        self.screen.set_overlay("切换到「键鼠操作」标签以启动镜像与控制")

    def _start_mirror_flow(self, gen: int) -> None:
        dev = self.devices.get(self.target)
        if not dev:
            return
        os_version = (dev.get("metadata") or {}).get("os_version", "")
        need = tunnel.needs_tunnel(os_version)
        running = tunnel.is_tunnel_running()
        _dbg(f"select target={self.target} os={os_version} need_tunnel={need} tunnel_running={running} gen={gen}")
        if need and not running:
            self._gate_tunnel(self.target, gen)
        else:
            self._prepare_device(self.target, gen)

    def _gate_tunnel(self, target: str, gen: int) -> None:
        reply = QMessageBox.question(
            self,
            "需要 XPC tunnel",
            "该 iOS 17+ 设备需要 XPC tunnel 才能控制。\n"
            "是否现在以管理员权限启动 XPC tunnel？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            self._set_status("未启动 XPC tunnel")
            self.screen.set_overlay("该 iOS 17+ 设备暂不可用\n（未启动 XPC tunnel，可重选设备重试）")
            return

        self._set_status("正在启动 XPC tunnel…")
        self.screen.set_overlay("正在请求管理员授权并启动 XPC tunnel…")

        def work():
            # launch_tunneld already polls the port and returns True only once the
            # tunnel is reachable (or False on cancel/failure/timeout).
            _dbg("work: calling launch_tunneld")
            ready = tunnel.launch_tunneld()
            _dbg(f"work: launch_tunneld ready={ready}")
            return "ok" if ready else "fail"

        self.runner.submit(
            work,
            on_done=lambda r: self._after_tunnel(r, target, gen),
            on_error=lambda e: (_dbg(f"work on_error: {e}"), self._tunnel_failed(e)),
            generation=gen,
        )

    def _after_tunnel(self, result, target: str, gen: int) -> None:
        _dbg(f"after_tunnel status={result} gen={gen} cur_gen={self.runner.generation}")
        if result != "ok":
            self._tunnel_failed("tunnel 未就绪")
            return
        self._prepare_device(target, gen)

    def _tunnel_failed(self, detail: str) -> None:
        _dbg(f"tunnel_failed detail={detail}")
        self._set_status("XPC tunnel 启动失败")
        self.screen.set_overlay(f"无法启动 XPC tunnel\n{detail}\n该 iOS 17+ 设备暂不可用，可重试")

    # ------------------------------------------------------- prepare / WDA

    def _prepare_device(self, target: str, gen: int) -> None:
        _dbg(f"prepare_device target={target} gen={gen}")
        self._set_status("正在启动 WebDriverAgent…")
        self.screen.set_overlay("正在启动 WebDriverAgent…\n首次启动可能需要数十秒")
        self.runner.submit(
            lambda: api.prepare(target),
            on_done=lambda r: self._on_prepared(r, target, gen),
            on_error=lambda e: self._prepare_failed(e),
            generation=gen,
        )

    def _on_prepared(self, result: dict, target: str, gen: int) -> None:
        _dbg(f"on_prepared ok={result.get('ok')} gen={gen} cur_gen={self.runner.generation}")
        if not result.get("ok"):
            self._prepare_failed(result.get("error", {}).get("message", "prepare failed"))
            return
        self.runner.submit(
            lambda: api.window_size(target),
            on_done=lambda r: self._on_winsize(r, target, gen),
            on_error=lambda e: self._prepare_failed(e),
            generation=gen,
        )

    def _on_winsize(self, result: dict, target: str, gen: int) -> None:
        _dbg(f"on_winsize ok={result.get('ok')} data={result.get('data')} gen={gen}")
        if not result.get("ok"):
            self._prepare_failed(result.get("error", {}).get("message", "window_size failed"))
            return
        self.win_size = result["data"]
        self.screen.set_window_size(self.win_size["width"], self.win_size["height"])
        self.info_size.setText(f"{self.win_size['width']} × {self.win_size['height']}")

        # Fetch orientation next so frames are rotated upright; non-fatal on failure.
        self.runner.submit(
            lambda: api.orientation(target),
            on_done=lambda r: self._on_orientation(r, target, gen),
            on_error=lambda _: self._on_orientation(None, target, gen),
            generation=gen,
        )

    def _on_orientation(self, result, target: str, gen: int) -> None:
        if result and result.get("ok"):
            self.orientation = result["data"]
        else:
            self.orientation = {"orientation": "PORTRAIT", "degrees": 0}
        _dbg(f"on_orientation {self.orientation} gen={gen}")
        self.screen.set_orientation(self.orientation.get("degrees", 0))
        self.info_orient.setText(_ORIENT_LABEL.get(self.orientation.get("orientation"), "—"))

        # Apply requested framerate, then start the stream (non-fatal on failure).
        self.runner.submit(
            lambda: api.configure_mjpeg(target, self.fps, _MJPEG_SCALING, _MJPEG_QUALITY),
            on_done=lambda _: self._begin_stream(target, gen),
            on_error=lambda _: self._begin_stream(target, gen),
            generation=gen,
        )

    def _prepare_failed(self, detail: str) -> None:
        _dbg(f"prepare_failed detail={detail}")
        self._set_status("启动失败")
        self.screen.set_overlay(f"无法启动 WebDriverAgent\n{detail}")

    # ------------------------------------------------------------- stream

    def _begin_stream(self, target: str, gen: int) -> None:
        if gen != self.runner.generation:
            _dbg(f"begin_stream STALE gen={gen} cur_gen={self.runner.generation}")
            return
        manager = api._get_manager()
        device = manager.get_device(target)
        port = getattr(device, "mjpeg_local_port", 0) if device else 0
        _dbg(f"begin_stream target={target} mjpeg_port={port}")
        if not port:
            self.screen.set_overlay("画面流不可用（MJPEG 端口未就绪）")
            self._set_status("画面流不可用")
            return

        self._set_status("已连接")
        self.screen.set_overlay(None)
        for btn in self._connected_buttons():
            btn.setEnabled(True)
        self.send_input.setEnabled(True)
        self.kbd_capture.setEnabled(True)

        self.mirror_thread = MjpegThread("127.0.0.1", port, self)
        self.mirror_thread.frame_ready.connect(self.screen.on_frame)
        self.mirror_thread.stream_error.connect(self._on_stream_error)
        self.mirror_thread.start()

    def _on_stream_error(self, message: str) -> None:
        self._set_status("画面已断开")
        self.screen.set_overlay(f"{message}\n请重新选择设备重试")

    def stop_stream(self) -> None:
        if self.mirror_thread is not None:
            self.mirror_thread.stop()
            self.mirror_thread.wait(2000)
            self.mirror_thread = None
        self.screen.clear_frame()
        self._set_keyboard(False)
        for btn in self._connected_buttons():
            btn.setEnabled(False)
        self.send_input.setEnabled(False)
        self.kbd_capture.setEnabled(False)

    # ------------------------------------------------------------ actions

    def on_tap(self, x: int, y: int) -> None:
        target = self.target
        self.runner.submit(lambda: api.tap(target, x, y),
                           on_error=lambda e: self._flash(f"点按失败: {e}"))

    def on_long_press(self, x: int, y: int, dur: int) -> None:
        target = self.target
        self.runner.submit(lambda: api.long_press(target, x, y, dur),
                           on_error=lambda e: self._flash(f"长按失败: {e}"))

    def on_swipe(self, x1: int, y1: int, x2: int, y2: int, dur: int) -> None:
        target = self.target
        self.runner.submit(lambda: api.swipe(target, x1, y1, x2, y2, dur),
                           on_error=lambda e: self._flash(f"滑动失败: {e}"))

    def on_home(self) -> None:
        target = self.target
        self.runner.submit(lambda: api.key_event(target, "HOME"),
                           on_error=lambda e: self._flash(f"HOME 失败: {e}"))

    def on_switcher(self) -> None:
        target = self.target
        self._set_status("正在打开应用切换…")
        self.runner.submit(
            lambda: api.app_switcher(target),
            on_done=lambda r: self._set_status("已连接") if r.get("ok") else self._flash("应用切换失败"),
            on_error=lambda e: self._flash(f"应用切换失败: {e}"),
        )
        self._refocus_keyboard()

    def on_screenshot(self) -> None:
        target = self.target
        self.runner.submit(
            lambda: api.screenshot(target),
            on_done=self._save_screenshot,
            on_error=lambda e: self._flash(f"截图失败: {e}"),
        )

    def _save_screenshot(self, result: dict) -> None:
        if not result.get("ok"):
            self._flash("截图失败")
            return
        png = base64.b64decode(result["data"]["base64"])
        png = self._orient_screenshot(png)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"ios-{self.target[:8]}-{ts}.png"
        # Default the dialog to the user's Downloads folder (falls back to the
        # home dir, then the bare filename, if Downloads cannot be resolved).
        download_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        ) or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.HomeLocation
        )
        default = os.path.join(download_dir, filename) if download_dir else filename
        path, _ = QFileDialog.getSaveFileName(self, "保存截图", default, "PNG 图片 (*.png)")
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(png)
            self._set_status(f"截图已保存: {path}")
        except OSError as exc:
            self._flash(f"保存失败: {exc}")
        self._refocus_keyboard()

    def _orient_screenshot(self, png: bytes) -> bytes:
        # WDA's screenshot already corrects the 90° landscape rotation but not the
        # 180° flip, so an upside-down portrait device yields an inverted PNG. Mirror
        # the mirror.py render correction here so saved files match what's on screen.
        if int(self.orientation.get("degrees", 0)) % 360 != 180:
            return png
        image = QImage.fromData(png, "PNG")
        if image.isNull():
            return png
        rotated = image.transformed(QTransform().rotate(180), Qt.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        if not rotated.save(buffer, "PNG"):
            return png
        return bytes(buffer.data())

    def on_fps_changed(self) -> None:
        self.fps = self.fps_combo.currentData() or _DEFAULT_FPS
        if not self.target or self.mirror_thread is None:
            return
        target = self.target
        self.runner.submit(
            lambda: api.configure_mjpeg(target, self.fps, _MJPEG_SCALING, _MJPEG_QUALITY),
            on_error=lambda e: self._flash(f"帧率设置失败: {e}"),
        )

    # ----------------------------------------------------------- keyboard

    def on_toggle_keyboard(self) -> None:
        self._set_keyboard(not self.kbd_on)

    def _set_keyboard(self, on: bool) -> None:
        self.kbd_on = on and self.mirror_thread is not None
        if self.kbd_on:
            # In-place swap: hide the toggle button, reveal capture field + exit.
            self.kbd_btn.setVisible(False)
            self.kbd_active_row.setVisible(True)
            self.kbd_sender.set_target(self.target)
            if not self.kbd_sender.isRunning():
                self.kbd_sender.start()
            self.kbd_capture.clear()
            self.kbd_capture.setFocus()
        else:
            self.kbd_capture.clearFocus()
            self.kbd_active_row.setVisible(False)
            self.kbd_btn.setVisible(True)
            self.kbd_btn.setText("键盘输入: 关")

    def _refocus_keyboard(self) -> None:
        if self.kbd_on:
            self.kbd_capture.setFocus()

    # ----------------------------------------------------- text & pasteboard

    def on_send_text(self) -> None:
        text = self.send_input.text()
        if not text or not self.target:
            return
        target = self.target
        self.runner.submit(
            lambda: api.send_keys(target, text),
            on_done=self._on_send_done,
            on_error=lambda e: self._flash(f"发送失败: {e}"),
        )

    def _on_send_done(self, result: dict) -> None:
        if result.get("ok"):
            self.send_input.clear()  # clear only on success; keep on failure
        else:
            msg = result.get("error", {}).get("message", "发送失败")
            self._flash(f"发送失败: {msg}")
        self._refocus_keyboard()

    def on_set_pasteboard(self) -> None:
        if not self.target:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "设置设备剪贴板", "内容:", ""
        )
        if not ok:
            return
        target = self.target
        self._set_status("正在设置剪贴板…")
        self.runner.submit(
            lambda: api.set_pasteboard(target, text),
            on_done=lambda r: self._flash("已设置设备剪贴板") if r.get("ok")
            else self._flash("设置剪贴板失败: " + r.get("error", {}).get("message", "")),
            on_error=lambda e: self._flash(f"设置剪贴板失败: {e}"),
        )
        self._refocus_keyboard()

    def on_get_pasteboard(self) -> None:
        if not self.target:
            return
        target = self.target
        self._set_status("正在读取剪贴板…")
        self.runner.submit(
            lambda: api.get_pasteboard(target),
            on_done=self._show_pasteboard,
            on_error=lambda e: self._flash(f"读取剪贴板失败: {e}"),
        )

    def _show_pasteboard(self, result: dict) -> None:
        if not result.get("ok"):
            msg = result.get("error", {}).get("message", "")
            self._flash(f"读取剪贴板失败: {msg}" if msg else "读取剪贴板失败")
            return
        data = result.get("data", {})
        is_text = bool(data.get("isText"))
        self._flash("已读取设备剪贴板" if is_text else "剪贴板为空或为非文本内容")

        dlg = QDialog(self)
        dlg.setWindowTitle("设备剪贴板")
        layout = QVBoxLayout(dlg)
        text = data.get("text", "")
        if is_text:
            view = QPlainTextEdit()
            view.setPlainText(text)
            view.setReadOnly(True)  # read-only but still selectable / copyable
            layout.addWidget(view)
        else:
            layout.addWidget(QLabel("剪贴板为空或为非文本内容，无法显示/复制\n（请确认设备上已复制文本）"))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        if is_text:
            copy_btn = buttons.addButton("复制到本机", QDialogButtonBox.ActionRole)
            copy_btn.clicked.connect(lambda: self._copy_to_host(text))
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        dlg.resize(420, 320)
        dlg.exec()
        self._refocus_keyboard()

    def _copy_to_host(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self._flash("已复制到本机剪贴板")

    # ------------------------------------------------------------- helpers

    def _connected_buttons(self) -> tuple:
        # Buttons enabled only while a device is connected / streaming.
        return (
            self.home_btn, self.switcher_btn, self.reload_btn, self.kbd_btn,
            self.shot_btn, self.send_btn, self.set_pb_btn, self.get_pb_btn,
        )

    def _fill_info(self, dev: dict | None) -> None:
        self.info_size.setText(
            f"{self.win_size['width']} × {self.win_size['height']}" if self.win_size else "—"
        )

    # ------------------------------------------------------------- closing

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.stop_stream()
        if self.kbd_sender.isRunning():
            self.kbd_sender.stop()
            self.kbd_sender.wait(1000)

        if self._ask_clean_tunnel_on_exit() and tunnel.is_tunnel_running():
            reply = QMessageBox.question(
                self,
                "停止 XPC tunnel",
                "检测到 XPC tunnel 仍在运行。\n是否停止它？（停止需要管理员授权）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                tunnel.stop_tunneld()
        event.accept()
