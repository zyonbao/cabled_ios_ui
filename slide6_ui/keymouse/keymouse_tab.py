"""keymouse_tab.py — the "键鼠操作" tab: live mirror, gestures, keyboard, actions.

Owns the live screen mirror plus the full WDA / tunnel / streaming lifecycle for
the currently selected device. MainWindow drives it through a small delegation
surface (`select_device`, `on_enter`, `on_leave`, `set_overlay`, `shutdown`); all
blocking ios_toolkit calls go through the shared AsyncRunner and the live mirror
runs in its own thread (see mirror.py).
"""

from __future__ import annotations

import base64
import os
import sys
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QBuffer, QIODevice, QStandardPaths, Qt
from PySide6.QtGui import QImage, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common import readiness, tunnel
from ..common.workers import AsyncRunner
from .keyboard import KeyboardCapture, KeyboardSender
from .mirror import MjpegThread, ScreenView

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

_ORIENT_KEYS = {
    "PORTRAIT": "keymouse.orient.portrait",
    "PORTRAIT_UPSIDE_DOWN": "keymouse.orient.portrait_upside_down",
    "LANDSCAPE_LEFT": "keymouse.orient.landscape_left",
    "LANDSCAPE_RIGHT": "keymouse.orient.landscape_right",
}


def _orient_label(orientation: "str | None") -> str:
    """Localized orientation label (lazy so i18n is ready); '—' when unknown."""
    key = _ORIENT_KEYS.get(orientation)
    return i18n.t(key) if key else "—"


class KeymouseTab(QWidget):
    """Live mirror + gesture/keyboard/action controls for the selected device.

    `runner` is the shared AsyncRunner owned by MainWindow; `set_status` updates
    the shared top-bar status label; `reload_callback` re-runs MainWindow's full
    device-select flow (the refresh button intentionally refreshes every tab,
    matching the pre-extraction behavior).
    """

    def __init__(
        self,
        runner: AsyncRunner,
        set_status: Callable[[str], None],
        reload_callback: Callable[[], None],
    ) -> None:
        super().__init__()
        self.runner = runner
        self._status_cb = set_status
        self._reload_cb = reload_callback

        self.target = ""
        self.dev: dict | None = None
        self.win_size: dict | None = None
        self.orientation: dict = {"orientation": "PORTRAIT", "degrees": 0}
        self.fps = _DEFAULT_FPS
        self.mirror_thread: MjpegThread | None = None
        self.kbd_on = False

        self._build_ui()
        self._wire()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        center = QHBoxLayout(self)
        self.screen = ScreenView()
        center.addWidget(self.screen, stretch=1)

        # Right-side operation area: a fixed-width container so its background
        # box does not stretch/collapse with the mirror view.
        sidebar_box = QWidget()
        sidebar_box.setFixedWidth(260)
        sidebar = QVBoxLayout(sidebar_box)
        sidebar.setContentsMargins(8, 0, 0, 0)

        # Non-interactive device info first (read-only): resolution / orientation.
        # Use left-aligned stacked rows (not a two-column form) so these labels
        # line up with the buttons / fields below them.
        self.info_size = QLabel(i18n.t("keymouse.info.size_unknown"))
        self.info_orient = QLabel(i18n.t("keymouse.info.orient_unknown"))
        for lbl in (self.info_size, self.info_orient):
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            sidebar.addWidget(lbl)

        # Refresh (screen / orientation) sits directly under the info labels and
        # above the fps selector. It is enabled as soon as a device is selected
        # (it just re-runs the device select flow), independent of WDA/streaming.
        self.reload_btn = QPushButton(i18n.t("keymouse.reload"))
        self.reload_btn.setEnabled(False)
        sidebar.addWidget(self.reload_btn)

        # Interactive controls: fps (moved off the top bar).
        fps_row = QWidget()
        fps_layout = QHBoxLayout(fps_row)
        fps_layout.setContentsMargins(0, 0, 0, 0)
        self.fps_combo = QComboBox()
        for f in _FPS_CHOICES:
            self.fps_combo.addItem(f"{f} fps", f)
        self.fps_combo.setCurrentText(f"{_DEFAULT_FPS} fps")
        fps_layout.addWidget(QLabel(i18n.t("keymouse.fps")))
        fps_layout.addWidget(self.fps_combo, 1)
        sidebar.addWidget(fps_row)

        self.home_btn = QPushButton(i18n.t("keymouse.home"))
        self.switcher_btn = QPushButton(i18n.t("keymouse.switcher"))
        self.kbd_btn = QPushButton(i18n.t("keymouse.kbd_off"))
        self.shot_btn = QPushButton(i18n.t("keymouse.screenshot"))
        for btn in (self.home_btn, self.switcher_btn):
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
        self.kbd_close_btn.setToolTip(i18n.t("keymouse.kbd_exit_tip"))
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
        self.send_input.setPlaceholderText(i18n.t("keymouse.send_placeholder"))
        self.send_input.setEnabled(False)
        self.send_btn = QPushButton(i18n.t("keymouse.send"))
        self.send_btn.setEnabled(False)
        send_row = QWidget()
        send_layout = QHBoxLayout(send_row)
        send_layout.setContentsMargins(0, 0, 0, 0)
        send_layout.addWidget(self.send_input, 1)
        send_layout.addWidget(self.send_btn)
        sidebar.addWidget(send_row)

        # Pasteboard buttons.
        self.set_pb_btn = QPushButton(i18n.t("keymouse.set_pasteboard"))
        self.get_pb_btn = QPushButton(i18n.t("keymouse.get_pasteboard"))
        for btn in (self.set_pb_btn, self.get_pb_btn):
            btn.setEnabled(False)
            sidebar.addWidget(btn)

        sidebar.addStretch(1)
        center.addWidget(sidebar_box)

        # Keyboard sender worker (started lazily on first enable).
        self.kbd_sender = KeyboardSender(self)

    def _wire(self) -> None:
        self.fps_combo.activated.connect(self.on_fps_changed)
        self.home_btn.clicked.connect(self.on_home)
        self.switcher_btn.clicked.connect(self.on_switcher)
        # Per-device refresh: re-run the full select flow for the current device.
        self.reload_btn.clicked.connect(self._reload_cb)
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
        self.kbd_sender.failed.connect(lambda m: self._flash(i18n.t("keymouse.input_failed", msg=m)))

    # -------------------------------------------------------------- status

    def _set_status(self, text: str) -> None:
        self._status_cb(text)

    def _flash(self, message: str) -> None:
        self._status_cb(message)

    def set_overlay(self, text: str | None) -> None:
        self.screen.set_overlay(text)

    # ------------------------------------------------- MainWindow delegation

    def select_device(self, target: str, dev: dict | None, active: bool) -> None:
        """Switch to a device: reset mirror state and (when active) start the flow.

        `active` is True when the key/mouse tab is the current tab; otherwise the
        costly WDA/mirror startup is deferred until the tab is entered.
        """
        gen = self.runner.bump_generation()
        self.stop_stream()
        self.target = target or ""
        self.dev = dev
        self.win_size = None
        self.orientation = {"orientation": "PORTRAIT", "degrees": 0}
        self.screen.set_window_size(0, 0)
        self.screen.set_orientation(0)
        self.info_orient.setText(i18n.t("keymouse.info.orient_unknown"))
        # Refresh button only needs a selected device (it re-runs this flow), so
        # enable/disable it purely on target presence.
        self.reload_btn.setEnabled(bool(self.target))

        if not self.target:
            self._fill_info(None)
            self._set_status(i18n.t("main_window.status.disconnected"))
            self.screen.set_overlay(i18n.t("common.select_device_first"))
            return

        self._fill_info(dev)
        if not dev or dev.get("state") != "online":
            self._set_status(i18n.t("keymouse.no_wda_status"))
            self.screen.set_overlay(i18n.t("keymouse.no_wda_overlay"))
            return

        # WDA / mirror startup is costly and only this tab needs it. Defer it
        # until the tab is active (start now if it already is).
        if active:
            self._start_mirror_flow(gen)
        else:
            self._set_status(i18n.t("keymouse.device_selected"))
            self.screen.set_overlay(i18n.t("keymouse.switch_tab_hint"))

    def on_enter(self) -> None:
        # Entering: lazily start the WDA / mirror flow for a connected,
        # not-yet-streaming device.
        if not self.target or self.mirror_thread is not None:
            return
        if not self.dev or self.dev.get("state") != "online":
            return
        gen = self.runner.bump_generation()
        self._start_mirror_flow(gen)

    def on_leave(self) -> None:
        # Leaving: stop mirroring and the WDA runner to free the device.
        self._teardown_mirror()

    def shutdown(self) -> None:
        # Called from MainWindow.closeEvent before tunnel cleanup.
        self.stop_stream()
        if self.kbd_sender.isRunning():
            self.kbd_sender.stop()
            self.kbd_sender.wait(1000)

    # ---------------------------------------------------- mirror lifecycle

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
        self.screen.set_overlay(i18n.t("keymouse.switch_tab_hint"))

    def _start_mirror_flow(self, gen: int) -> None:
        dev = self.dev
        if not dev:
            return
        os_version = (dev.get("metadata") or {}).get("os_version", "")
        need = tunnel.needs_tunnel(os_version)
        running = tunnel.is_tunnel_running()
        _dbg(f"select target={self.target} os={os_version} need_tunnel={need} tunnel_running={running} gen={gen}")
        if need and not running:
            self._gate_tunnel(self.target, gen)
        else:
            self._check_readiness(self.target, gen)

    def _gate_tunnel(self, target: str, gen: int) -> None:
        reply = QMessageBox.question(
            self,
            i18n.t("keymouse.tunnel_need.title"),
            i18n.t("keymouse.tunnel_need.body"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            self._set_status(i18n.t("keymouse.tunnel_not_started"))
            self.screen.set_overlay(i18n.t("keymouse.tunnel_unavailable_overlay"))
            return

        self._set_status(i18n.t("keymouse.tunnel_starting"))
        self.screen.set_overlay(i18n.t("keymouse.tunnel_starting_overlay"))

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
            self._tunnel_failed(i18n.t("keymouse.tunnel_not_ready"))
            return
        self._check_readiness(target, gen)

    # --------------------------------------------------- readiness precheck

    def _check_readiness(self, target: str, gen: int) -> None:
        """Verify DDI (and, on iOS 17+, the RSD service) before starting WDA.

        WDA needs a mounted DeveloperDiskImage on every iOS version, plus the
        ``testmanagerd.remote`` RSD service on iOS 17+. Probing here turns the
        otherwise cryptic WDA failure into actionable guidance (mount DDI /
        restart tunnel). The tunnel itself is already handled by _gate_tunnel.
        """
        dev = self.dev or {}
        os_version = (dev.get("metadata") or {}).get("os_version", "")
        _dbg(f"check_readiness target={target} os={os_version} gen={gen}")
        self._set_status(i18n.t("keymouse.checking_ready"))
        self.screen.set_overlay(i18n.t("keymouse.checking_ready"))
        self.runner.submit(
            lambda: readiness.probe(target, os_version),
            on_done=lambda r: self._on_readiness(r, target, gen),
            on_error=lambda e: self._on_readiness(
                readiness.Readiness(False, None, i18n.t("keymouse.ready_check_failed", error=e)), target, gen
            ),
            generation=gen,
        )

    def _on_readiness(self, result: "readiness.Readiness", target: str, gen: int) -> None:
        _dbg(f"on_readiness ready={result.ready} missing={result.missing} gen={gen}")
        if result.ready:
            self._prepare_device(target, gen)
            return
        # Not ready: surface actionable guidance and stop (user fixes it in the
        # developer-tools tab, then reselects the device to retry).
        self._set_status(i18n.t("keymouse.device_not_ready"))
        if result.missing == readiness.MISSING_DDI:
            self.screen.set_overlay(i18n.t("keymouse.overlay_need_ddi"))
        elif result.missing == readiness.MISSING_RSD:
            self.screen.set_overlay(i18n.t("keymouse.overlay_need_rsd"))
        else:
            self.screen.set_overlay(i18n.t("keymouse.overlay_unavailable", message=result.message))

    def _tunnel_failed(self, detail: str) -> None:
        _dbg(f"tunnel_failed detail={detail}")
        self._set_status(i18n.t("keymouse.tunnel_start_failed"))
        self.screen.set_overlay(i18n.t("keymouse.tunnel_failed_overlay", detail=detail))

    # ------------------------------------------------------- prepare / WDA

    def _prepare_device(self, target: str, gen: int) -> None:
        _dbg(f"prepare_device target={target} gen={gen}")
        self._set_status(i18n.t("keymouse.wda_starting"))
        self.screen.set_overlay(i18n.t("keymouse.wda_starting_overlay"))
        self.runner.submit(
            lambda: api.prepare(target),
            on_done=lambda r: self._on_prepared(r, target, gen),
            on_error=lambda e: self._prepare_failed(e),
            generation=gen,
        )

    def _on_prepared(self, result: dict, target: str, gen: int) -> None:
        _dbg(f"on_prepared ok={result.get('ok')} gen={gen} cur_gen={self.runner.generation}")
        if not result.get("ok"):
            self._prepare_failed(localize_error(result.get("error")))
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
            self._prepare_failed(localize_error(result.get("error")))
            return
        self.win_size = result["data"]
        self.screen.set_window_size(self.win_size["width"], self.win_size["height"])
        self.info_size.setText(
            i18n.t("keymouse.info.size", width=self.win_size['width'], height=self.win_size['height'])
        )

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
        self.info_orient.setText(
            i18n.t("keymouse.info.orient", value=_orient_label(self.orientation.get("orientation")))
        )

        # Apply requested framerate, then start the stream (non-fatal on failure).
        self.runner.submit(
            lambda: api.configure_mjpeg(target, self.fps, _MJPEG_SCALING, _MJPEG_QUALITY),
            on_done=lambda _: self._begin_stream(target, gen),
            on_error=lambda _: self._begin_stream(target, gen),
            generation=gen,
        )

    def _prepare_failed(self, detail: str) -> None:
        _dbg(f"prepare_failed detail={detail}")
        self._set_status(i18n.t("keymouse.start_failed"))
        self.screen.set_overlay(i18n.t("keymouse.wda_failed_overlay", detail=detail))

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
            self.screen.set_overlay(i18n.t("keymouse.stream_unavailable_overlay"))
            self._set_status(i18n.t("keymouse.stream_unavailable"))
            return

        self._set_status(i18n.t("keymouse.connected"))
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
        self._set_status(i18n.t("keymouse.stream_disconnected"))
        self.screen.set_overlay(i18n.t("keymouse.stream_error_overlay", message=message))

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
                           on_error=lambda e: self._flash(i18n.t("keymouse.tap_failed", error=e)))

    def on_long_press(self, x: int, y: int, dur: int) -> None:
        target = self.target
        self.runner.submit(lambda: api.long_press(target, x, y, dur),
                           on_error=lambda e: self._flash(i18n.t("keymouse.long_press_failed", error=e)))

    def on_swipe(self, x1: int, y1: int, x2: int, y2: int, dur: int) -> None:
        target = self.target
        self.runner.submit(lambda: api.swipe(target, x1, y1, x2, y2, dur),
                           on_error=lambda e: self._flash(i18n.t("keymouse.swipe_failed", error=e)))

    def on_home(self) -> None:
        target = self.target
        self.runner.submit(lambda: api.key_event(target, "HOME"),
                           on_error=lambda e: self._flash(i18n.t("keymouse.home_failed", error=e)))

    def on_switcher(self) -> None:
        target = self.target
        self._set_status(i18n.t("keymouse.switcher_opening"))
        self.runner.submit(
            lambda: api.app_switcher(target),
            on_done=lambda r: self._set_status(i18n.t("keymouse.connected")) if r.get("ok") else self._flash(i18n.t("keymouse.switcher_failed")),
            on_error=lambda e: self._flash(i18n.t("keymouse.switcher_failed_detail", error=e)),
        )
        self._refocus_keyboard()

    def on_screenshot(self) -> None:
        target = self.target
        self.runner.submit(
            lambda: api.screenshot(target),
            on_done=self._save_screenshot,
            on_error=lambda e: self._flash(i18n.t("keymouse.screenshot_failed_detail", error=e)),
        )

    def _save_screenshot(self, result: dict) -> None:
        if not result.get("ok"):
            self._flash(i18n.t("keymouse.screenshot_failed"))
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
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("keymouse.save_screenshot"), default, i18n.t("keymouse.png_filter")
        )
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(png)
            self._set_status(i18n.t("keymouse.screenshot_saved", path=path))
        except OSError as exc:
            self._flash(i18n.t("keymouse.save_failed", error=exc))
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
            on_error=lambda e: self._flash(i18n.t("keymouse.fps_failed", error=e)),
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
            self.kbd_btn.setText(i18n.t("keymouse.kbd_off"))

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
            on_error=lambda e: self._flash(i18n.t("keymouse.send_failed_detail", error=e)),
        )

    def _on_send_done(self, result: dict) -> None:
        if result.get("ok"):
            self.send_input.clear()  # clear only on success; keep on failure
        else:
            msg = localize_error(result.get("error"))
            self._flash(i18n.t("keymouse.send_failed_msg", msg=msg))
        self._refocus_keyboard()

    def on_set_pasteboard(self) -> None:
        if not self.target:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, i18n.t("keymouse.pb_set_title"), i18n.t("keymouse.pb_content_label"), ""
        )
        if not ok:
            return
        target = self.target
        self._set_status(i18n.t("keymouse.pb_setting"))
        self.runner.submit(
            lambda: api.set_pasteboard(target, text),
            on_done=lambda r: self._flash(i18n.t("keymouse.pb_set_ok")) if r.get("ok")
            else self._flash(i18n.t("keymouse.pb_set_failed") + ": " + localize_error(r.get("error"))),
            on_error=lambda e: self._flash(i18n.t("keymouse.pb_set_failed_detail", error=e)),
        )
        self._refocus_keyboard()

    def on_get_pasteboard(self) -> None:
        if not self.target:
            return
        target = self.target
        self._set_status(i18n.t("keymouse.pb_reading"))
        self.runner.submit(
            lambda: api.get_pasteboard(target),
            on_done=self._show_pasteboard,
            on_error=lambda e: self._flash(i18n.t("keymouse.pb_read_failed_detail", error=e)),
        )

    def _show_pasteboard(self, result: dict) -> None:
        if not result.get("ok"):
            msg = localize_error(result.get("error"))
            self._flash(i18n.t("keymouse.pb_read_failed_msg", msg=msg) if msg else i18n.t("keymouse.pb_read_failed"))
            return
        data = result.get("data", {})
        is_text = bool(data.get("isText"))
        self._flash(i18n.t("keymouse.pb_read_ok") if is_text else i18n.t("keymouse.pb_empty"))

        dlg = QDialog(self)
        dlg.setWindowTitle(i18n.t("keymouse.pb_dialog_title"))
        layout = QVBoxLayout(dlg)
        text = data.get("text", "")
        if is_text:
            view = QPlainTextEdit()
            view.setPlainText(text)
            view.setReadOnly(True)  # read-only but still selectable / copyable
            layout.addWidget(view)
        else:
            layout.addWidget(QLabel(i18n.t("keymouse.pb_empty_detail")))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        if is_text:
            copy_btn = buttons.addButton(i18n.t("keymouse.pb_copy_to_host"), QDialogButtonBox.ActionRole)
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
        self._flash(i18n.t("keymouse.pb_copied"))

    # ------------------------------------------------------------- helpers

    def _connected_buttons(self) -> tuple:
        # Buttons enabled only while a device is connected / streaming. The
        # refresh (screen / orientation) button is intentionally excluded: it is
        # gated on device selection alone (see select_device), not on WDA.
        return (
            self.home_btn, self.switcher_btn, self.kbd_btn,
            self.shot_btn, self.send_btn, self.set_pb_btn, self.get_pb_btn,
        )

    def _fill_info(self, dev: dict | None) -> None:
        self.info_size.setText(
            i18n.t("keymouse.info.size", width=self.win_size['width'], height=self.win_size['height'])
            if self.win_size else i18n.t("keymouse.info.size_unknown")
        )
