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

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QPoint, QSettings, QStandardPaths, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.file_dialogs import open_existing_file, save_file
from ..common.gate_overlay import GatedTabMixin
from ..common.keymouse_settings import (
    SWIPE_UP_BOTTOM,
    SWIPE_UP_CONTROL_CENTER,
    SWIPE_UP_DISABLED,
    SWIPE_UP_HOLD_APP_SWITCHER,
    SWIPE_UP_HOLD_DISABLED,
    get_pasteboard_auto_copy_host,
    get_ui_xml_auto_copy_host,
    resolve_bottom_edge_gesture_row,
)
from ..common import readiness
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

# Image file extensions accepted for pasteboard image writes (drag-drop / picker).
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tiff", ".tif")
# Soft threshold above which writing an image is confirmed (it is slow over WDA).
_PASTEBOARD_IMAGE_WARN_BYTES = 10 * 1024 * 1024


def _looks_like_url(text: str) -> bool:
    """A trimmed single token with a scheme + host is treated as a URL.

    Anything with internal whitespace/newlines stays plaintext so long text
    that merely contains a URL is not misclassified.
    """
    trimmed = (text or "").strip()
    if not trimmed or any(ch.isspace() for ch in trimmed):
        return False
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(trimmed)
    except ValueError:
        return False
    return bool(parts.scheme and parts.netloc)

_ORIENT_KEYS = {
    "PORTRAIT": "keymouse.orient.portrait",
    "PORTRAIT_UPSIDE_DOWN": "keymouse.orient.portrait_upside_down",
    "LANDSCAPE_LEFT": "keymouse.orient.landscape_left",
    "LANDSCAPE_RIGHT": "keymouse.orient.landscape_right",
}

_BOTTOM_EDGE_LABEL_KEYS = {
    SWIPE_UP_HOLD_APP_SWITCHER: "keymouse.bottom_edge.app_switcher",
    SWIPE_UP_BOTTOM: "keymouse.bottom_edge.bottom_swipe_up",
    SWIPE_UP_CONTROL_CENTER: "keymouse.bottom_edge.control_center",
}


def _orient_label(orientation: "str | None") -> str:
    """Localized orientation label (lazy so i18n is ready); '—' when unknown."""
    key = _ORIENT_KEYS.get(orientation)
    return i18n.t(key) if key else "—"


class SendTextEdit(QTextEdit):
    """Multi-line text-send box for the device.

    Enter sends (emits ``send_requested``); Shift+Enter inserts a newline so
    multi-line text can be composed. The widget auto-grows with its content up
    to ``_MAX_LINES`` visible lines, after which it keeps that height and shows
    a vertical scrollbar. Pasted multi-line content therefore renders across
    lines instead of being flattened onto one row.
    """

    send_requested = Signal()

    _MAX_LINES = 5

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(False)  # plain text only; device input is text
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.textChanged.connect(self._adjust_height)
        self._adjust_height()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Plain Enter sends; Shift+Enter falls through to insert a newline.
        # During IME composition Enter is consumed by the input method (it
        # commits the candidate) and never reaches here, so composing is safe.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        # Width changes alter wrapping, so recompute the clamped height.
        self._adjust_height()

    def _adjust_height(self) -> None:
        doc = self.document()
        doc.setTextWidth(self.viewport().width())
        line_h = self.fontMetrics().lineSpacing()
        chrome = 2 * doc.documentMargin() + 2 * self.frameWidth()
        content = doc.size().height() + 2 * self.frameWidth()
        one_line = line_h + chrome
        max_h = line_h * self._MAX_LINES + chrome
        self.setFixedHeight(int(min(max(content, one_line), max_h)))


class _SetPasteboardDialog(QDialog):
    """Set-pasteboard input: text OR image, mutually exclusive.

    Text and image share a single content area (a stacked widget): the text
    editor is shown in text mode and the image preview replaces it in image
    mode. An image can be added via the button or by dropping an image file on
    the dialog; adding one while text is present clears the text after a
    confirmation. "Remove image" returns to text mode.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("keymouse.pb_set_title"))
        self.setAcceptDrops(True)
        self._image_bytes: bytes | None = None
        self._pixmap_full: QPixmap | None = None

        layout = QVBoxLayout(self)

        # Text and image occupy the same region via a stacked widget.
        self.stack = QStackedWidget()
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(i18n.t("keymouse.pb_input_placeholder"))
        # The editor accepts file drops by default and would paste the URL as
        # text; disable on both the widget and its viewport (the real drop
        # target for a scroll area) so image drops bubble up to the dialog.
        self.text_edit.setAcceptDrops(False)
        self.text_edit.viewport().setAcceptDrops(False)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(200)
        self.image_label.setAcceptDrops(False)
        self.stack.addWidget(self.text_edit)   # index 0: text
        self.stack.addWidget(self.image_label)  # index 1: image
        layout.addWidget(self.stack, 1)

        # Bottom row: add/remove image left-aligned, Cancel/OK right-aligned.
        bottom = QHBoxLayout()
        self.add_image_btn = QPushButton(i18n.t("keymouse.pb_add_image"))
        self.remove_image_btn = QPushButton(i18n.t("keymouse.pb_remove_image"))
        self.remove_image_btn.setVisible(False)
        bottom.addWidget(self.add_image_btn)
        bottom.addWidget(self.remove_image_btn)
        bottom.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

        self.add_image_btn.clicked.connect(self._on_add_image)
        self.remove_image_btn.clicked.connect(self._remove_image)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.resize(440, 380)

    # -- drag & drop into the dialog --------------------------------------

    def _first_image_drop(self, mime) -> str:
        if not mime.hasUrls():
            return ""
        for url in mime.urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(_IMAGE_EXTS):
                return url.toLocalFile()
        return ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._first_image_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._first_image_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        path = self._first_image_drop(event.mimeData())
        if path:
            event.acceptProposedAction()
            self._load_image_from_path(path)
        else:
            event.ignore()

    # -- image handling ----------------------------------------------------

    def _confirm_replace_text(self) -> bool:
        """Confirm clearing entered text before loading an image (Yes/No)."""
        if not self.text_edit.toPlainText().strip():
            return True
        answer = QMessageBox.question(
            self,
            i18n.t("keymouse.pb_set_title"),
            i18n.t("keymouse.pb_image_replaces_text"),
        )
        return answer == QMessageBox.Yes

    def _on_add_image(self) -> None:
        # Button path: confirm the text-clearing BEFORE opening the picker so the
        # user is not made to choose a file only to then be asked to discard it.
        if not self._confirm_replace_text():
            return
        path = open_existing_file(
            self, i18n.t("keymouse.pb_pick_image"), [i18n.t("keymouse.image_filter")]
        )
        if path:
            self._load_image_from_path(path, confirm_replace=False)

    def _load_image_from_path(self, path: str, confirm_replace: bool = True) -> None:
        # Drop path passes confirm_replace=True (cannot ask before the drop);
        # the button path confirms earlier and passes False.
        if confirm_replace and not self._confirm_replace_text():
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            QMessageBox.warning(
                self, i18n.t("keymouse.pb_set_title"),
                i18n.t("keymouse.pb_image_read_failed", error=exc),
            )
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            QMessageBox.warning(
                self, i18n.t("keymouse.pb_set_title"), i18n.t("keymouse.pb_not_image")
            )
            return
        self._image_bytes = data
        self._pixmap_full = pixmap
        self.text_edit.clear()
        self._rescale_preview()
        self.stack.setCurrentWidget(self.image_label)
        self.remove_image_btn.setVisible(True)

    def _remove_image(self) -> None:
        self._image_bytes = None
        self._pixmap_full = None
        self.image_label.clear()
        self.stack.setCurrentWidget(self.text_edit)
        self.remove_image_btn.setVisible(False)
        self.text_edit.setFocus()

    def _rescale_preview(self) -> None:
        if self._pixmap_full is None:
            return
        area = self.image_label.size()
        self.image_label.setPixmap(
            self._pixmap_full.scaled(area, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self._image_bytes is not None:
            self._rescale_preview()

    def result_content(self) -> "tuple[str, object]":
        """Return ``("image", bytes)`` or ``("text", str)``."""
        if self._image_bytes is not None:
            return ("image", self._image_bytes)
        return ("text", self.text_edit.toPlainText())


class _KeyboardInputPopup(QWidget):
    """Floating, draggable keyboard-capture window over the keymouse tab.

    A single compact row — capture field + close (✕) — with an opaque
    background, sized to (and shown covering) the entry button. It is a child of
    the tab so it can be constrained to the tab's bounds while dragging, and
    floats above the mirror/sidebar via raise_(). Clicking the field types;
    pressing the background (margins/gap) drags the window. Dragging is clamped
    so no part of the window ever leaves the tab.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # Opaque rounded panel is hand-painted in paintEvent. A stylesheet
        # border would be folded into the box model and unbalance the row's
        # top/bottom margins, so it is intentionally not used here.
        self.setCursor(Qt.SizeAllCursor)
        self._press_global: QPoint | None = None
        self._start_pos = QPoint()
        # Re-clamp into view when the tab resizes (window shrink / sidebar width
        # change), otherwise a once-placed popup can end up partly off-screen.
        parent.installEventFilter(self)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(4)
        # Field + close button on one row. No forced heights and no per-item
        # alignment: the row takes the taller control's height, the popup is
        # that height + symmetric margins, and Qt vertically centers the shorter
        # field. (Passing Qt.AlignVCenter here actually breaks it — the field
        # then top-aligns and leaves extra space at the bottom — so rely on the
        # default behavior.)
        self.capture = KeyboardCapture()
        self.close_btn = QPushButton()
        self.close_btn.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.close_btn.setFixedWidth(24)
        self.close_btn.setToolTip(i18n.t("keymouse.kbd_exit_tip"))
        row.addWidget(self.capture, 1)
        row.addWidget(self.close_btn)

    def show_over(self, anchor: QWidget) -> None:
        """Show over the entry button: button width, natural (symmetric) height."""
        parent = self.parentWidget()
        # Width follows the button; height is the row's natural height (max of
        # field/button) plus margins, keeping the contents vertically centered.
        # Use sizeHint directly — adjustSize() takes a different layout path that
        # top-aligns the shorter field and unbalances the margins.
        self.resize(anchor.width(), self.sizeHint().height())
        top_left = anchor.mapTo(parent, anchor.rect().topLeft())
        self.move(self._clamped(top_left))
        self.show()
        self.raise_()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Only background presses reach here (the field / ✕ consume their own).
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._start_pos = self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._press_global is not None:
            # Parent isn't scaled, so a global delta equals a parent-local delta.
            delta = event.globalPosition().toPoint() - self._press_global
            self.move(self._clamped(self._start_pos + delta))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        was_dragging = self._press_global is not None
        self._press_global = None
        # The IME caches the candidate-window position from when the field
        # gained focus, and a plain micro-focus update does NOT refresh it. After
        # a drag, re-focus the field so the IME re-queries the field's new
        # position — the same effect as manually switching focus away and back.
        if was_dragging and self.capture.hasFocus():
            self.capture.clearFocus()
            self.capture.setFocus()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Hand-paint an opaque rounded background + border (no stylesheet) so the
        # panel has no see-through gaps and the layout margins stay symmetric.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self.palette().window())
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)

    def _clamped(self, pos: QPoint) -> QPoint:
        # Keep the whole window inside the tab: x∈[0, W-w], y∈[0, H-h].
        parent = self.parentWidget()
        max_x = max(0, parent.width() - self.width())
        max_y = max(0, parent.height() - self.height())
        return QPoint(min(max(0, pos.x()), max_x), min(max(0, pos.y()), max_y))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        # When the tab resizes, pull a shown popup back inside the new bounds.
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and not self.isHidden():
            self.move(self._clamped(self.pos()))
        return super().eventFilter(obj, event)


class KeymouseTab(GatedTabMixin, QWidget):
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
        self.init_gate()

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
        self.kbd_btn = QPushButton(i18n.t("keymouse.kbd_off"))
        self.shot_btn = QPushButton(i18n.t("keymouse.screenshot"))
        self.home_btn.setEnabled(False)
        sidebar.addWidget(self.home_btn)

        self.bottom_edge_box = QWidget()
        self.bottom_edge_layout = QVBoxLayout(self.bottom_edge_box)
        self.bottom_edge_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_edge_layout.setSpacing(6)
        self.bottom_edge_buttons: list[QPushButton] = []
        sidebar.addWidget(self.bottom_edge_box)

        self.input_group = QWidget()
        input_layout = QVBoxLayout(self.input_group)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)

        # Keyboard entry button: a fixed-position toggle whose text flips between
        # "off" and "on". The capture field itself lives in a separate floating
        # popup (see _KeyboardInputPopup), so toggling never resizes this row.
        self.kbd_btn.setEnabled(False)
        input_layout.addWidget(self.kbd_btn)

        # Keyboard capture lives in a draggable popup over the tab (not inline),
        # so toggling it never changes the sidebar height. The entry button's
        # text toggles instead (Off / On).
        self.kbd_popup = _KeyboardInputPopup(self)
        self.kbd_capture = self.kbd_popup.capture
        self.kbd_close_btn = self.kbd_popup.close_btn
        self.kbd_popup.hide()

        # Text send row: a standalone field + send button, independent of the
        # keyboard-mirroring capture above. The field is multi-line and grows
        # with its content (Enter sends, Shift+Enter inserts a newline).
        self.send_input = SendTextEdit()
        self.send_input.setPlaceholderText(i18n.t("keymouse.send_placeholder"))
        self.send_input.setToolTip(i18n.t("keymouse.send_tip"))
        self.send_input.setEnabled(False)
        self.send_btn = QPushButton(i18n.t("keymouse.send"))
        self.send_btn.setEnabled(False)
        send_row = QWidget()
        send_layout = QHBoxLayout(send_row)
        send_layout.setContentsMargins(0, 0, 0, 0)
        send_layout.addWidget(self.send_input, 1)
        send_layout.addWidget(self.send_btn, 0, Qt.AlignVCenter)
        input_layout.addWidget(send_row)
        sidebar.addWidget(self.input_group)

        self.shot_btn.setEnabled(False)
        sidebar.addWidget(self.shot_btn)

        self.clipboard_group = QWidget()
        clipboard_layout = QVBoxLayout(self.clipboard_group)
        clipboard_layout.setContentsMargins(0, 0, 0, 0)
        clipboard_layout.setSpacing(6)

        # Pasteboard buttons.
        self.set_pb_btn = QPushButton(i18n.t("keymouse.set_pasteboard"))
        self.get_pb_btn = QPushButton(i18n.t("keymouse.get_pasteboard"))
        for btn in (self.set_pb_btn, self.get_pb_btn):
            btn.setEnabled(False)
            clipboard_layout.addWidget(btn)
        sidebar.addWidget(self.clipboard_group)

        self.ui_xml_group = QWidget()
        ui_xml_layout = QVBoxLayout(self.ui_xml_group)
        ui_xml_layout.setContentsMargins(0, 0, 0, 0)
        ui_xml_layout.setSpacing(6)
        self.ui_xml_btn = QPushButton(i18n.t("keymouse.ui_xml"))
        self.ui_xml_btn.setEnabled(False)
        ui_xml_layout.addWidget(self.ui_xml_btn)
        sidebar.addWidget(self.ui_xml_group)

        sidebar.addStretch(1)
        center.addWidget(sidebar_box)

        # Keyboard sender worker (started lazily on first enable).
        self.kbd_sender = KeyboardSender(self)

    def _wire(self) -> None:
        self.fps_combo.activated.connect(self.on_fps_changed)
        self.home_btn.clicked.connect(self.on_home)
        # Per-device refresh: re-run the full select flow for the current device.
        self.reload_btn.clicked.connect(self._reload_cb)
        self.kbd_btn.clicked.connect(self.on_toggle_keyboard)
        self.kbd_close_btn.clicked.connect(lambda: self._set_keyboard(False))
        self.shot_btn.clicked.connect(self.on_screenshot)
        self.send_btn.clicked.connect(self.on_send_text)
        self.send_input.send_requested.connect(self.on_send_text)
        self.set_pb_btn.clicked.connect(self.on_set_pasteboard)
        self.get_pb_btn.clicked.connect(self.on_get_pasteboard)
        self.ui_xml_btn.clicked.connect(self.on_dump_ui)

        self.screen.tap.connect(self.on_tap)
        self.screen.long_press.connect(self.on_long_press)
        self.screen.swipe.connect(self.on_swipe)
        self.screen.gesture_finished.connect(self._refocus_keyboard)
        self.screen.file_dropped.connect(self.on_file_dropped)

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

    def _on_gate_visibility_changed(self, visible: bool) -> None:
        self.screen.set_gate_blocked(visible)
        if visible:
            self.screen.set_overlay(None)

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
        self.screen.set_overlay(None)
        # Reset the full-tab external gate; only the tunnel/DDI readiness phase
        # (re)raises it. Internal/render hints below live on the ScreenView.
        self.set_external_gate(None)
        self.info_orient.setText(i18n.t("keymouse.info.orient_unknown"))
        # Refresh button only needs a selected device (it re-runs this flow), so
        # enable/disable it purely on target presence.
        self.reload_btn.setEnabled(bool(self.target))
        self.refresh_bottom_edge_gesture_buttons()

        if not self.target:
            self._fill_info(None)
            self._set_status(i18n.t("main_window.status.disconnected"))
            self.screen.set_overlay(i18n.t("common.select_device_first"))
            self._schedule_focus_clear()
            return

        self._fill_info(dev)
        if not dev or dev.get("state") != "online":
            # Only surface "WDA not installed" in the shared top-bar status when
            # this tab is actually active; a deferred selection (user sitting on
            # another tab) must not hijack the global status line.
            self.screen.set_overlay(i18n.t("keymouse.no_wda_overlay"))
            if active:
                self._set_status(i18n.t("keymouse.no_wda_status"))
            self._schedule_focus_clear()
            return

        # WDA / mirror startup is costly and only this tab needs it. Defer it
        # until the tab is active (start now if it already is).
        if active:
            self._start_mirror_flow(gen)
        else:
            self.screen.set_overlay(None)
        self._schedule_focus_clear()

    def on_enter(self) -> None:
        # Entering: lazily start the WDA / mirror flow for a connected,
        # not-yet-streaming device.
        self._schedule_focus_clear()
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
        self.set_external_gate(None)
        self.screen.set_overlay(None)

    def _start_mirror_flow(self, gen: int) -> None:
        dev = self.dev
        if not dev:
            return
        os_version = (dev.get("metadata") or {}).get("os_version", "")
        _dbg(f"select target={self.target} os={os_version} gen={gen}")
        # XPC tunnel is managed solely from the Developer Tools tab. Here we only
        # run the unified readiness check and, when a precondition is missing,
        # surface non-modal guidance (overlay/status) pointing the user there —
        # no modal prompt and no auto-launch of the tunnel from this tab.
        self._check_readiness(self.target, gen)

    # --------------------------------------------------- readiness precheck

    def _check_readiness(self, target: str, gen: int) -> None:
        """Verify tunnel / DDI / RSD before starting WDA, guiding non-modally.

        WDA needs a mounted DeveloperDiskImage on every iOS version, plus the
        XPC tunnel and ``testmanagerd.remote`` RSD service on iOS 17+. Probing
        here turns the otherwise cryptic WDA failure into actionable guidance
        (start tunnel / mount DDI / restart tunnel) shown as a non-modal overlay;
        the tunnel is started by the user in the Developer Tools tab, not here.
        """
        dev = self.dev or {}
        os_version = (dev.get("metadata") or {}).get("os_version", "")
        _dbg(f"check_readiness target={target} os={os_version} gen={gen}")
        self._set_status(i18n.t("keymouse.checking_ready"))
        self.stop_stream()
        # Tunnel/DDI readiness is an external precondition: surface it on the
        # full-tab gate overlay, not the ScreenView (which is only used for the
        # mirror render flow once the device is ready).
        self.set_external_gate(i18n.t("keymouse.checking_ready"))
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
        # Missing tunnel / DDI / RSD are external preconditions the user fixes in
        # the Developer Tools tab — show them on the full-tab gate overlay.
        if result.missing == readiness.MISSING_TUNNEL_AND_DDI:
            self.set_external_gate(i18n.t("keymouse.overlay_need_tunnel_ddi"))
        elif result.missing == readiness.MISSING_TUNNEL:
            self.set_external_gate(i18n.t("keymouse.overlay_need_tunnel"))
        elif result.missing == readiness.MISSING_DDI:
            self.set_external_gate(i18n.t("keymouse.overlay_need_ddi"))
        elif result.missing == readiness.MISSING_RSD:
            self.set_external_gate(i18n.t("keymouse.overlay_need_rsd"))
        else:
            self.set_external_gate(i18n.t("keymouse.overlay_unavailable", message=result.message))

    # ------------------------------------------------------- prepare / WDA

    def _prepare_device(self, target: str, gen: int) -> None:
        _dbg(f"prepare_device target={target} gen={gen}")
        self._set_status(i18n.t("keymouse.wda_starting"))
        # Readiness passed: drop the external gate so the mirror render flow's
        # hints (WDA starting / failures / stream) show on the ScreenView.
        self.set_external_gate(None)
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
        # Device ready: allow dropping an image onto the mirror to set pasteboard.
        self.screen.set_drop_enabled(True)

        self.mirror_thread = MjpegThread("127.0.0.1", port, self)
        self.mirror_thread.frame_ready.connect(self.screen.on_frame)
        self.mirror_thread.stream_error.connect(self._on_stream_error)
        self.mirror_thread.start()

    def _on_stream_error(self, message: str) -> None:
        self._set_status(i18n.t("keymouse.stream_disconnected"))
        self.screen.clear_frame()
        self.screen.set_overlay(i18n.t("keymouse.stream_error_overlay", message=message))

    def stop_stream(self) -> None:
        if self.mirror_thread is not None:
            self.mirror_thread.stop()
            self.mirror_thread.wait(2000)
            self.mirror_thread = None
        self.screen.clear_frame()
        self._set_keyboard(False)
        self.screen.set_drop_enabled(False)
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

    def on_bottom_edge_action(self, action: str) -> None:
        target = self.target
        label = i18n.t(_BOTTOM_EDGE_LABEL_KEYS[action])
        if action == SWIPE_UP_HOLD_APP_SWITCHER:
            self._set_status(i18n.t("keymouse.switcher_opening"))
            self.runner.submit(
                lambda: api.app_switcher(target),
                on_done=lambda r: self._set_status(i18n.t("keymouse.connected")) if r.get("ok") else self._flash(i18n.t("keymouse.switcher_failed")),
                on_error=lambda e: self._flash(i18n.t("keymouse.switcher_failed_detail", error=e)),
            )
        else:
            self._set_status(i18n.t("keymouse.bottom_edge.opening", name=label))
            self.runner.submit(
                lambda: api.bottom_edge_swipe(target),
                on_done=lambda r: self._set_status(i18n.t("keymouse.connected")) if r.get("ok") else self._flash(i18n.t("keymouse.bottom_edge.failed", name=label)),
                on_error=lambda e: self._flash(i18n.t("keymouse.bottom_edge.failed_detail", name=label, error=e)),
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
        path = save_file(
            self, i18n.t("keymouse.save_screenshot"), default, [i18n.t("keymouse.png_filter")]
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
            self.kbd_sender.set_target(self.target)
            if not self.kbd_sender.isRunning():
                self.kbd_sender.start()
            self.kbd_capture.clear()
            # Float the capture popup over the entry button, then focus it.
            self.kbd_popup.show_over(self.kbd_btn)
            self.kbd_capture.setFocus()
            self.kbd_btn.setText(i18n.t("keymouse.kbd_on"))
        else:
            self.kbd_capture.clearFocus()
            self.kbd_popup.hide()
            self.kbd_btn.setText(i18n.t("keymouse.kbd_off"))

    def _refocus_keyboard(self) -> None:
        if self.kbd_on:
            self.kbd_capture.setFocus()

    def should_preserve_focus(self) -> bool:
        return self.kbd_on

    def _schedule_focus_clear(self) -> None:
        QTimer.singleShot(0, self._clear_focus_if_idle)

    def _clear_focus_if_idle(self) -> None:
        if self.should_preserve_focus():
            return
        focused = QApplication.focusWidget()
        if focused is not None and self.isAncestorOf(focused):
            focused.clearFocus()

    # ----------------------------------------------------- text & pasteboard

    def on_send_text(self) -> None:
        text = self.send_input.toPlainText()
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
        dlg = _SetPasteboardDialog(self)
        if dlg.exec() != QDialog.Accepted:
            self._refocus_keyboard()
            return
        kind, payload = dlg.result_content()
        if kind == "image":
            self._send_image_pasteboard(payload)
            return
        text = payload
        if not text:
            self._refocus_keyboard()
            return
        # A bare URL is written as a `url` pasteboard item; otherwise plaintext.
        content_type = "url" if _looks_like_url(text) else "plaintext"
        target = self.target
        self._set_status(i18n.t("keymouse.pb_setting"))
        self.runner.submit(
            lambda: api.set_pasteboard(target, text, content_type),
            on_done=lambda r: self._flash(i18n.t("keymouse.pb_set_ok")) if r.get("ok")
            else self._flash(i18n.t("keymouse.pb_set_failed") + ": " + localize_error(r.get("error"))),
            on_error=lambda e: self._flash(i18n.t("keymouse.pb_set_failed_detail", error=e)),
        )
        self._refocus_keyboard()

    def on_file_dropped(self, path: str) -> None:
        # Drag-to-pasteboard only makes sense once the device is connected; the
        # tab validates image-ness here so non-image drops get a clear hint.
        if not self.target or self.mirror_thread is None:
            return
        if not path.lower().endswith(_IMAGE_EXTS):
            self._flash(i18n.t("keymouse.pb_drop_not_image"))
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            self._flash(i18n.t("keymouse.pb_image_read_failed", error=exc))
            return
        self._send_image_pasteboard(data)

    def _send_image_pasteboard(self, data: bytes) -> None:
        if not self.target or not data:
            self._refocus_keyboard()
            return
        if len(data) > _PASTEBOARD_IMAGE_WARN_BYTES:
            answer = QMessageBox.question(
                self, i18n.t("keymouse.pb_set_title"), i18n.t("keymouse.pb_image_too_large")
            )
            if answer != QMessageBox.Yes:
                self._refocus_keyboard()
                return
        target = self.target
        self._set_status(i18n.t("keymouse.pb_setting"))
        self.runner.submit(
            lambda: api.set_pasteboard(target, data, "image"),
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
        text = data.get("text", "")

        # Setting on: skip the display dialog and copy text straight to the host.
        if get_pasteboard_auto_copy_host(QSettings()):
            if is_text:
                self._copy_to_host(text)  # flashes "已复制到本机"
            else:
                self._flash(i18n.t("keymouse.pb_empty"))
            self._refocus_keyboard()
            return

        self._flash(i18n.t("keymouse.pb_read_ok") if is_text else i18n.t("keymouse.pb_empty"))

        dlg = QDialog(self)
        dlg.setWindowTitle(i18n.t("keymouse.pb_dialog_title"))
        layout = QVBoxLayout(dlg)
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

    def on_dump_ui(self) -> None:
        if not self.target:
            return
        target = self.target
        self._set_status(i18n.t("keymouse.ui_xml_loading"))
        self.runner.submit(
            lambda: api.dump_ui(target),
            on_done=self._show_ui_xml,
            on_error=lambda e: self._flash(i18n.t("keymouse.ui_xml_failed_detail", error=e)),
        )

    def _show_ui_xml(self, result: dict) -> None:
        if not result.get("ok"):
            msg = localize_error(result.get("error"))
            self._flash(i18n.t("keymouse.ui_xml_failed_msg", msg=msg) if msg else i18n.t("keymouse.ui_xml_failed"))
            return

        raw = (result.get("data") or {}).get("raw", "")

        # Setting on: skip the viewer dialog and copy the XML straight to host.
        if get_ui_xml_auto_copy_host(QSettings()):
            if raw:
                self._copy_to_host(raw)  # flashes "已复制到本机"
            else:
                self._flash(i18n.t("keymouse.ui_xml_ready"))
            self._refocus_keyboard()
            return

        self._flash(i18n.t("keymouse.ui_xml_ready"))

        dlg = QDialog(self)
        dlg.setWindowTitle(i18n.t("keymouse.ui_xml_dialog_title"))
        layout = QVBoxLayout(dlg)
        view = QPlainTextEdit()
        view.setPlainText(raw)
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(view)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy_btn = buttons.addButton(i18n.t("keymouse.pb_copy_to_host"), QDialogButtonBox.ButtonRole.ActionRole)
        copy_btn.clicked.connect(lambda: self._copy_to_host(raw))
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        dlg.resize(760, 520)
        dlg.exec()
        self._refocus_keyboard()

    # ------------------------------------------------------------- helpers

    def _connected_buttons(self) -> tuple:
        # Buttons enabled only while a device is connected / streaming. The
        # refresh (screen / orientation) button is intentionally excluded: it is
        # gated on device selection alone (see select_device), not on WDA.
        return (
            self.home_btn, *self.bottom_edge_buttons, self.kbd_btn,
            self.shot_btn, self.send_btn, self.set_pb_btn, self.get_pb_btn, self.ui_xml_btn,
        )

    def refresh_bottom_edge_gesture_buttons(self) -> None:
        while self.bottom_edge_layout.count():
            item = self.bottom_edge_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.bottom_edge_buttons = []

        row = resolve_bottom_edge_gesture_row(self.target, QSettings())
        actions: list[str] = []
        if row["swipeUpHold"] != SWIPE_UP_HOLD_DISABLED:
            actions.append(row["swipeUpHold"])
        if row["swipeUp"] != SWIPE_UP_DISABLED:
            actions.append(row["swipeUp"])

        for action in actions:
            button = QPushButton(i18n.t(_BOTTOM_EDGE_LABEL_KEYS[action]))
            button.setEnabled(self.mirror_thread is not None)
            button.clicked.connect(lambda _checked=False, value=action: self.on_bottom_edge_action(value))
            self.bottom_edge_layout.addWidget(button)
            self.bottom_edge_buttons.append(button)

        self.bottom_edge_box.setVisible(bool(self.bottom_edge_buttons))

    def _fill_info(self, dev: dict | None) -> None:
        self.info_size.setText(
            i18n.t("keymouse.info.size", width=self.win_size['width'], height=self.win_size['height'])
            if self.win_size else i18n.t("keymouse.info.size_unknown")
        )
