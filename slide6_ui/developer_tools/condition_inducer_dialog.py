"""condition_inducer_dialog.py — DVT Condition Inducer dialog.

Applies a predefined device condition profile (slow network / thermal state /
GPU performance state) via a connection-scoped DVT handle. The condition is only
active while the handle holds its connection, so closing the window auto-reverts.
The device allows a single active condition, so applying a new profile switches
(disable then enable). All blocking calls go through the shared AsyncRunner.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.focus import suppress_auto_focus
from ..common.workers import AsyncRunner


class ConditionInducerDialog(QDialog):
    """Select and apply a single predefined condition profile."""

    def __init__(self, runner: AsyncRunner, target: str, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._target = target
        self._handle = None
        self._active = None  # current active condition dict, or None
        self._group_name_by_id: dict[str, str] = {}
        self._profile_name_by_id: dict[tuple[str, str], str] = {}

        self.setWindowTitle(i18n.t("condition.title"))
        self.resize(640, 260)
        self._build_ui()
        self._wire()
        suppress_auto_focus(self)
        self._open()

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.state_label = QLabel(i18n.t("condition.state.inactive"))
        self.state_label.setMinimumWidth(360)
        self.state_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        form.addRow(i18n.t("condition.state_label"), self.state_label)
        self.group_combo = QComboBox()
        self.profile_combo = QComboBox()
        for combo in (self.group_combo, self.profile_combo):
            combo.setMinimumWidth(360)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        form.addRow(i18n.t("condition.group_label"), self.group_combo)
        form.addRow(i18n.t("condition.profile_label"), self.profile_combo)
        root.addLayout(form)

        controls = QHBoxLayout()
        self.start_btn = QPushButton(i18n.t("condition.start"))
        self.stop_btn = QPushButton(i18n.t("condition.stop"))
        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        self.status = QLabel(i18n.t("condition.connecting"))
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self._set_controls_enabled(False)

    def _wire(self) -> None:
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        self.profile_combo.currentIndexChanged.connect(self._update_profile_tooltip)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.group_combo.setEnabled(enabled)
        self.profile_combo.setEnabled(enabled)
        self.start_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled and self._active is not None)

    # -- Open (enumerate models) ------------------------------------------

    def _open(self) -> None:
        self.runner.submit(
            lambda: api.open_condition_inducer(self._target),
            on_done=self._on_open,
            on_error=lambda e: self.status.setText(
                i18n.t("condition.open_failed", error=e)
            ),
        )

    def _on_open(self, result) -> None:
        if isinstance(result, dict):  # error envelope
            self.status.setText(localize_error(result.get("error")))
            return
        self._handle = result
        models = self._handle.models
        if not models:
            self.status.setText(i18n.t("condition.no_models"))
            return
        self.group_combo.blockSignals(True)
        for group in models:
            gid = str(group.get("identifier") or "")
            gname = self._display_group_name(group)
            if gid:
                self._group_name_by_id[gid] = gname
            self.group_combo.addItem(gname, group)
        self.group_combo.blockSignals(False)
        self._on_group_changed()
        self._set_controls_enabled(True)
        self.status.setText(i18n.t("condition.hint"))

    def _on_group_changed(self) -> None:
        group = self.group_combo.currentData()
        self.profile_combo.clear()
        if not group:
            return
        for prof in group["profiles"]:
            gid = str(group.get("identifier") or "")
            pid = str(prof.get("identifier") or "")
            pname = self._display_profile_name(group, prof)
            if gid and pid:
                self._profile_name_by_id[(gid, pid)] = pname
            self.profile_combo.addItem(pname, prof)
        self.profile_combo.setToolTip(self._current_profile_summary())

    def _update_profile_tooltip(self) -> None:
        self.profile_combo.setToolTip(self._current_profile_summary())

    def _current_profile_summary(self) -> str:
        prof = self.profile_combo.currentData()
        return (prof or {}).get("description") or ""

    # -- Apply / clear -----------------------------------------------------

    def _start(self) -> None:
        if self._handle is None:
            return
        group = self.group_combo.currentData()
        prof = self.profile_combo.currentData()
        if not group or not prof:
            return
        name = f"{self._display_group_name(group)} / {self._display_profile_name(group, prof)}"
        body = i18n.t("condition.confirm_body", name=name)
        summary = prof.get("description") or ""
        if summary:
            body = f"{body}\n\n{summary}"
        if group.get("is_destructive"):
            body = f"{body}\n\n⚠ {i18n.t('condition.confirm_destructive')}"
        confirm = QMessageBox.question(
            self, i18n.t("condition.confirm_title"), body,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Ok:
            return
        gid, pid = group["identifier"], prof["identifier"]
        self.status.setText(i18n.t("condition.applying", name=name))
        self._set_controls_enabled(False)
        self.runner.submit(
            lambda: self._handle.apply(gid, pid),
            on_done=self._on_apply,
            on_error=lambda e: self._after(i18n.t("condition.apply_failed", error=e)),
        )

    def _on_apply(self, result: dict) -> None:
        if not result.get("ok"):
            self._after(localize_error(result.get("error")))
            return
        data = result["data"]
        self._active = data
        self._refresh_state()
        self._after(i18n.t("condition.applied", name=self._active_name()))

    def _stop(self) -> None:
        if self._handle is None:
            return
        self.status.setText(i18n.t("condition.stopping"))
        self._set_controls_enabled(False)
        self.runner.submit(
            lambda: self._handle.clear(),
            on_done=self._on_clear,
            on_error=lambda e: self._after(i18n.t("condition.apply_failed", error=e)),
        )

    def _on_clear(self, result: dict) -> None:
        if not result.get("ok"):
            self._after(localize_error(result.get("error")))
            return
        self._active = None
        self._refresh_state()
        self._after(i18n.t("condition.cleared"))

    # -- State helpers -----------------------------------------------------

    def _active_name(self) -> str:
        if not self._active:
            return ""
        gid = str(self._active.get("group") or "")
        pid = str(self._active.get("profile") or "")
        gname = self._group_name_by_id.get(gid) or str(
            self._active.get("group_name") or gid
        )
        pname = self._profile_name_by_id.get((gid, pid)) or str(
            self._active.get("profile_name") or pid
        )
        return f"{gname} / {pname}"

    def _display_group_name(self, group: dict) -> str:
        gid = str(group.get("identifier") or "")
        fallback = str(group.get("name") or gid)
        direct = self._translate_identifier("condition.group", gid)
        if direct:
            return direct
        guessed = self._translate_guess(fallback)
        return guessed or fallback

    def _display_profile_name(self, group: dict, profile: dict) -> str:
        gid = str(group.get("identifier") or "")
        pid = str(profile.get("identifier") or "")
        fallback = str(profile.get("name") or pid)
        scoped = self._translate_identifier("condition.profile", f"{gid}.{pid}")
        if scoped:
            return scoped
        direct = self._translate_identifier("condition.profile", pid)
        if direct:
            return direct
        guessed = self._translate_guess(fallback)
        return guessed or fallback

    def _translate_identifier(self, prefix: str, raw: str) -> str | None:
        if not raw:
            return None
        safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in raw).strip("_")
        while "__" in safe:
            safe = safe.replace("__", "_")
        key = f"{prefix}.{safe}"
        if i18n.has(key):
            return i18n.t(key)
        return None

    def _translate_guess(self, label: str) -> str | None:
        low = label.lower()
        guess_map = (
            ("network", "condition.label.network"),
            ("thermal", "condition.label.thermal"),
            ("gpu", "condition.label.gpu"),
            ("cpu", "condition.label.cpu"),
            ("power", "condition.label.power"),
        )
        for token, key in guess_map:
            if token in low and i18n.has(key):
                return i18n.t(key)
        return None

    def _refresh_state(self) -> None:
        if self._active:
            self.state_label.setText(
                i18n.t("condition.state.active", name=self._active_name())
            )
            self.start_btn.setText(i18n.t("condition.switch"))
        else:
            self.state_label.setText(i18n.t("condition.state.inactive"))
            self.start_btn.setText(i18n.t("condition.start"))

    def _after(self, message: str) -> None:
        self._set_controls_enabled(self._handle is not None)
        self.status.setText(message)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Close the handle off the UI thread: reverting a condition can take a few
        # seconds (confirm-poll), so don't freeze the window on close. The handle
        # stays alive via the closure until close() finishes; the condition reverts
        # in the background (and the dropped connection auto-reverts as a backstop).
        handle = self._handle
        self._handle = None
        if handle is not None:
            self.runner.submit(lambda: handle.close(), on_error=lambda e: None)
        super().closeEvent(event)
