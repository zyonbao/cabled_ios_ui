"""gate_overlay.py — a reusable single-layer gate overlay.

A `GateOverlay` floats above a host widget, covering it entirely (and
intercepting clicks) while showing one centered message card. The card behind
the text is fully opaque so the gated widgets never bleed through the hint.

Centralizing the overlay here keeps every tab to a single, consistently styled
gate layer: the pairing gate (main window), the XPC-tunnel gate (diagnostics)
and the key/mouse readiness hints all reuse this one component. It can be
reparented across pages via `attach`, so a single instance can guard whichever
tab is currently visible.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class GateOverlay(QWidget):
    """Full-host gate overlay with one centered, opaque message card."""

    def __init__(self, host: QWidget, *, max_width: int = 460) -> None:
        super().__init__(host)
        self.setObjectName("gateOverlay")
        # Dim backdrop over the whole host; the message card itself is opaque so
        # text never has gated widgets showing through it.
        self.setStyleSheet(
            "#gateOverlay { background-color: rgba(20, 20, 20, 170); }"
        )
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        self._label = QLabel("", self)
        self._label.setObjectName("gateOverlayLabel")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(max_width)
        self._label.setStyleSheet(
            "#gateOverlayLabel { color: #f0f0f0; font-size: 14px;"
            " background-color: #2b2b2b; padding: 18px 24px; border-radius: 10px; }"
        )
        layout.addWidget(self._label)
        host.installEventFilter(self)
        self.hide()

    def attach(self, host: QWidget) -> None:
        """Reparent the overlay onto ``host`` (tracking its resizes)."""
        old = self.parentWidget()
        if old is host:
            return
        if old is not None:
            old.removeEventFilter(self)
        self.setParent(host)
        if host is not None:
            host.installEventFilter(self)

    def set_message(self, text: str | None) -> None:
        """Show the centered card with ``text``, or hide the overlay when falsy."""
        host = self.parentWidget()
        if text and host is not None:
            self._label.setText(text)
            self.setGeometry(host.rect())
            self.show()
            self.raise_()
        else:
            self.hide()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt override
        if (
            obj is self.parentWidget()
            and event.type() == QEvent.Resize
            and self.isVisible()
        ):
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(obj, event)


class GatedTabMixin:
    """Gives a tab a single full-tab gate overlay.

    One overlay layer serves two concerns, so a tab never stacks gates:

    - the host-pairing gate, driven by the main window via `set_pair_gate`;
    - the tab's own external precondition gate (e.g. a missing XPC tunnel / DDI),
      driven by the tab itself via `set_external_gate`.

    Pairing takes priority: an unpaired device always shows the pairing hint, and
    once paired the tab's own gate (if any) shows through the same single layer.

    The host tab MUST call `init_gate()` once after building its UI.
    """

    def init_gate(self, *, max_width: int = 460) -> None:
        self._gate_overlay = GateOverlay(self, max_width=max_width)
        self._pair_gate_text: str | None = None
        self._external_gate_text: str | None = None

    def set_pair_gate(self, text: str | None) -> None:
        """Show/hide the pairing gate (highest priority)."""
        self._pair_gate_text = text or None
        self._refresh_gate()

    def set_external_gate(self, text: str | None) -> None:
        """Show/hide the tab's own precondition gate (below the pairing gate)."""
        self._external_gate_text = text or None
        self._refresh_gate()

    def _refresh_gate(self) -> None:
        text = self._pair_gate_text or self._external_gate_text
        self._gate_overlay.set_message(text)
        on_changed = getattr(self, "_on_gate_visibility_changed", None)
        if callable(on_changed):
            on_changed(bool(text))
