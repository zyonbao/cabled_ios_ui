"""keyboard.py — mirror the host keyboard to the device's focused field.

Reproduces web_console's verified key routing, which is the only combination that
works on iOS via WDA:
  - text / IME composition  -> send_keys  (api.send_keys)
  - editing keys (Enter/Backspace/Tab/Esc, unmodified) -> key_event
  - navigation keys + any Cmd/Ctrl/Alt/Shift chord       -> key_chord

All commands flow through one FIFO worker thread that sends them strictly one at
a time, coalescing consecutive text into a single request, so fast typing never
lands out of order.

macOS note: Qt swaps Control/Meta on macOS by default, so Qt.ControlModifier is
the Command key and Qt.MetaModifier is the physical Control key. The modifier
collection below maps them back to iOS semantics accordingly.
"""

from __future__ import annotations

import queue

from PySide6.QtCore import QEvent, Qt, QThread, Signal
from PySide6.QtWidgets import QLineEdit, QWidget

from executor_ios import toolkit_api as api

# Navigation keys: only the keyboardInput/typeKey channel (key_chord) moves the
# cursor / extends selection on iOS.
_NAV_KEYS = {
    Qt.Key_Up: "UP",
    Qt.Key_Down: "DOWN",
    Qt.Key_Left: "LEFT",
    Qt.Key_Right: "RIGHT",
    Qt.Key_Home: "HOME",
    Qt.Key_End: "END",
    Qt.Key_PageUp: "PAGEUP",
    Qt.Key_PageDown: "PAGEDOWN",
}

# Editing keys: typeKey is a no-op for these on iOS, the W3C key event works.
_EDIT_KEYS = {
    Qt.Key_Return: "ENTER",
    Qt.Key_Enter: "ENTER",
    Qt.Key_Backspace: "BACKSPACE",
    Qt.Key_Tab: "TAB",
    Qt.Key_Backtab: "TAB",  # Shift+Tab arrives as Backtab
    Qt.Key_Escape: "ESCAPE",
}


def _chord_base(event) -> str | None:
    """Resolve the base key for a modifier chord (letter/digit/printable)."""
    key = event.key()
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(ord("a") + (key - Qt.Key_A))
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(ord("0") + (key - Qt.Key_0))
    text = event.text()
    if len(text) == 1 and text.isprintable():
        return text
    return None


def _collect_modifiers(mods) -> list[str]:
    """Map Qt modifiers (macOS semantics) to iOS chord modifier names."""
    out: list[str] = []
    if mods & Qt.ControlModifier:  # Command on macOS (Qt swaps Ctrl/Meta)
        out.append("meta")
    if mods & Qt.MetaModifier:     # physical Control on macOS
        out.append("control")
    if mods & Qt.AltModifier:
        out.append("alt")
    if mods & Qt.ShiftModifier:
        out.append("shift")
    return out


class KeyboardCapture(QLineEdit):
    """A focus-holding field that captures host keystrokes (incl. IME)."""

    text_typed = Signal(str)
    key_pressed = Signal(str)
    chord = Signal(str, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("键盘捕获（开启后在此聚焦）")
        self._composing = False
        self._busy = False
        self.textEdited.connect(self._on_text_edited)

    def _on_text_edited(self, text: str) -> None:
        # Committed text (including IME results) arrives here; forward and clear.
        # clear() can re-enter via inputMethodEvent -> textEdited during IME
        # composition, so guard against recursion with a reentrancy flag.
        if self._busy or not text:
            return
        self._busy = True
        try:
            self.text_typed.emit(text)
            self.clear()
        finally:
            self._busy = False

    def event(self, event) -> bool:  # noqa: N802 - Qt override
        et = event.type()
        # Qt's QWidget.event() consumes Tab/Backtab for focus traversal before
        # keyPressEvent ever sees them, so the host Tab would jump to the next
        # widget instead of reaching the device. Intercept those here and route
        # them through our key handling so Tab is forwarded to the device.
        if et == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(event)
            return True
        # Accepting ShortcutOverride forces any chord that would otherwise be
        # eaten by an app/window shortcut to be delivered to keyPressEvent
        # instead, so all keys this field can receive are mirrored to the
        # device. (OS-level shortcuts like ⌘Q are consumed by macOS earlier and
        # cannot be captured here.)
        if et == QEvent.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def inputMethodEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Track IME composition: a non-empty preedit means we are composing, so
        # keyPressEvent must defer to the input method (matching web isComposing).
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._composing:
            super().keyPressEvent(event)
            return

        key = event.key()
        mods = event.modifiers()
        has_cmd_like = bool(
            mods & (Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier)
        )

        if key in _NAV_KEYS:
            self.chord.emit(_NAV_KEYS[key], _collect_modifiers(mods))
            return
        if key in _EDIT_KEYS:
            if has_cmd_like:
                self.chord.emit(_EDIT_KEYS[key], _collect_modifiers(mods))
            else:
                self.key_pressed.emit(_EDIT_KEYS[key])
            return
        if has_cmd_like:
            base = _chord_base(event)
            if base is not None:
                self.chord.emit(base, _collect_modifiers(mods))
            return
        # Printable characters / IME flow to textEdited.
        super().keyPressEvent(event)


class KeyboardSender(QThread):
    """Serializes keyboard commands and sends them one at a time to the device."""

    failed = Signal(str)

    _STOP = object()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._queue: "queue.Queue" = queue.Queue()
        self._target = ""

    def set_target(self, target: str) -> None:
        self._target = target

    def enqueue_text(self, text: str) -> None:
        self._queue.put(("text", text))

    def enqueue_key(self, name: str) -> None:
        self._queue.put(("key", name))

    def enqueue_chord(self, key: str, modifiers: list) -> None:
        self._queue.put(("chord", key, modifiers))

    def stop(self) -> None:
        self._queue.put(self._STOP)

    def run(self) -> None:  # noqa: D401 - QThread entry point
        pending = None
        while True:
            cmd = pending if pending is not None else self._queue.get()
            pending = None
            if cmd is self._STOP:
                return

            try:
                if cmd[0] == "text":
                    text = cmd[1]
                    # Coalesce immediately-available consecutive text commands.
                    while True:
                        try:
                            nxt = self._queue.get_nowait()
                        except queue.Empty:
                            break
                        if nxt is self._STOP:
                            pending = self._STOP
                            break
                        if nxt[0] == "text":
                            text += nxt[1]
                        else:
                            pending = nxt
                            break
                    self._send(lambda: api.send_keys(self._target, text))
                elif cmd[0] == "key":
                    self._send(lambda: api.key_event(self._target, cmd[1]))
                elif cmd[0] == "chord":
                    self._send(lambda: api.key_chord(self._target, cmd[1], cmd[2]))
            except Exception as exc:  # keep the worker alive on any failure
                self.failed.emit(str(exc))

    def _send(self, call) -> None:
        result = call()
        if isinstance(result, dict) and not result.get("ok"):
            msg = result.get("error", {}).get("message", "input failed")
            self.failed.emit(msg)
