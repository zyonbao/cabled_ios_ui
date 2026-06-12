"""diagnostics_tab.py — the "诊断" (Diagnostics) tab.

Two sections of card-like feature tiles backed by the device DiagnosticsService:

- Section 1 「电源控制 / Power」: restart / shutdown / sleep. These are
  disruptive, so each click MUST pass a confirmation dialog before dispatch.
- Section 2 「诊断信息 / Diagnostics」: battery / wifi / diagnostic info /
  ioregistry. A MobileGestalt tile is shown only on iOS < 17.4 (Apple deprecated
  MobileGestalt from 17.4).

All blocking calls go through the shared AsyncRunner; query results are shown in
a read-only, copyable dialog. iOS 17+ needs the XPC tunnel; when it is missing
the toolkit returns a localized TUNNEL_REQUIRED error surfaced via localize_error.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api
from ios_toolkit.ddi_provider import parse_major_minor

from .. import i18n
from ..common import tunnel
from ..common.context_copy import install_plaintext_copy_menu
from ..common.errors import localize_error
from ..common.feature_tile import FeatureTile
from ..common.flow_layout import FlowLayout
from ..common.gate_overlay import GatedTabMixin
from ..common.workers import AsyncRunner

logger = logging.getLogger(__name__)

# Apple deprecated MobileGestalt from iOS 17.4; the tile only shows below this.
_MOBILEGESTALT_MAX = (17, 4)


def _below_mobilegestalt_cutoff(os_version: str) -> bool:
    """True when the device iOS version predates the MobileGestalt deprecation."""
    parsed = parse_major_minor(os_version)
    if parsed is None:
        return False  # unknown version → hide the deprecated affordance
    return parsed < _MOBILEGESTALT_MAX


class DiagnosticsTab(GatedTabMixin, QWidget):
    """The "诊断" tab: power control + read-only device diagnostics."""

    def __init__(
        self,
        runner: AsyncRunner,
        get_target: Callable[[], str],
        get_os_version: Callable[[], str],
    ) -> None:
        super().__init__()
        self.runner = runner
        self._get_target = get_target
        self._get_os_version = get_os_version
        self._op_in_flight = False
        # Open result windows kept alive (non-modal); cleaned up on close.
        self._result_dialogs: list[QDialog] = []
        self._build_ui()
        self._wire()
        self.init_gate(max_width=420)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # XPC tunnel is managed exclusively from the Developer Tools tab. When the
        # tunnel is required (iOS 17+) but not running, the tiles below are gated
        # with a tooltip and the status bar points the user to Developer Tools —
        # there is no tunnel control panel here anymore.

        # Section 1 — power control.
        self.power_header = self._section_header(i18n.t("diagnostics.section.power"))
        root.addWidget(self.power_header)
        power_flow = FlowLayout(spacing=12)
        self.restart_tile = self._tile("restart")
        self.shutdown_tile = self._tile("shutdown")
        self.sleep_tile = self._tile("sleep")
        power_flow.addWidget(self.restart_tile)
        power_flow.addWidget(self.shutdown_tile)
        power_flow.addWidget(self.sleep_tile)
        root.addLayout(power_flow)

        # Section 2 — diagnostic info.
        self.info_header = self._section_header(i18n.t("diagnostics.section.info"))
        root.addWidget(self.info_header)
        info_flow = FlowLayout(spacing=12)
        self.battery_tile = self._tile("battery")
        self.wifi_tile = self._tile("wifi")
        self.info_tile = self._tile("info")
        self.ioregistry_tile = self._tile("ioregistry")
        self.mobilegestalt_tile = self._tile("mobilegestalt")
        info_flow.addWidget(self.battery_tile)
        info_flow.addWidget(self.wifi_tile)
        info_flow.addWidget(self.info_tile)
        info_flow.addWidget(self.ioregistry_tile)
        info_flow.addWidget(self.mobilegestalt_tile)
        root.addLayout(info_flow)
        root.addStretch(1)

        self.status = QLabel(i18n.t("common.select_device_first"))
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        root.addWidget(self.status)

        # Collected for bulk enable/disable on device switch.
        self._all_tiles = [
            self.restart_tile,
            self.shutdown_tile,
            self.sleep_tile,
            self.battery_tile,
            self.wifi_tile,
            self.info_tile,
            self.ioregistry_tile,
            self.mobilegestalt_tile,
        ]

    def _set_gate_overlay(self, text: str | None) -> None:
        """Show the centered gate overlay with ``text``, or hide it when falsy.

        Routed through the shared GatedTabMixin overlay so this tab keeps a single
        gate layer: the pairing gate (driven by the main window) takes priority,
        and this XPC-tunnel gate shows through the same overlay once paired.
        """
        self.set_external_gate(text)

    @staticmethod
    def _section_header(text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        label.setFont(font)
        return label

    def _tile(self, key: str) -> FeatureTile:
        """Build a feature tile from the diagnostics.tile.<key>.{title,sub} keys."""
        tile = FeatureTile(
            i18n.t(f"diagnostics.tile.{key}.title"),
            i18n.t(f"diagnostics.tile.{key}.sub"),
        )
        tile.setEnabled(False)
        return tile

    def _wire(self) -> None:
        # Power actions require a confirmation before dispatch.
        self.restart_tile.clicked.connect(
            lambda: self._confirm_power("restart", api.device_restart)
        )
        self.shutdown_tile.clicked.connect(
            lambda: self._confirm_power("shutdown", api.device_shutdown)
        )
        self.sleep_tile.clicked.connect(
            lambda: self._confirm_power("sleep", api.device_sleep)
        )
        # Info queries open a read-only result dialog.
        self.battery_tile.clicked.connect(
            lambda: self._run_info("battery", api.diagnostics_battery)
        )
        self.wifi_tile.clicked.connect(
            lambda: self._run_info("wifi", api.diagnostics_wifi)
        )
        self.info_tile.clicked.connect(
            lambda: self._run_info("info", api.diagnostics_info)
        )
        self.ioregistry_tile.clicked.connect(
            lambda: self._run_info("ioregistry", api.diagnostics_ioregistry)
        )
        self.mobilegestalt_tile.clicked.connect(
            lambda: self._run_info("mobilegestalt", api.diagnostics_mobilegestalt)
        )

    # ------------------------------------------------------------- target

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        os_version = self._get_os_version()
        # MobileGestalt is deprecated from iOS 17.4; only show it below the cutoff.
        self.mobilegestalt_tile.setVisible(_below_mobilegestalt_cutoff(os_version))
        self._op_in_flight = False
        # _refresh_features drives the centered gate overlay when the tunnel is
        # missing, so the status bar just shows the normal ready / no-device line.
        self._refresh_features()
        self._set_status(
            i18n.t("diagnostics.ready") if target else i18n.t("diagnostics.no_device")
        )

    def shutdown(self) -> None:
        """Close any open result windows on app exit."""
        for dlg in list(self._result_dialogs):
            try:
                dlg.close()
            except RuntimeError:
                pass  # already deleted

    def _set_enabled(self, enabled: bool) -> None:
        for tile in self._all_tiles:
            tile.setEnabled(enabled)

    def _refresh_features(self) -> bool:
        """Drive tile enabled state from device selection + tunnel readiness.

        Diagnostics needs no DDI; on iOS 17+ it only needs the XPC tunnel. When a
        device is selected but the tunnel is required and not running, the tiles
        are disabled with a tooltip pointing to Developer Tools (the only place
        the tunnel can be started). Returns whether the tiles are gated.
        """
        target = self._get_target()
        if not target:
            for tile in self._all_tiles:
                tile.setEnabled(False)
                tile.setToolTip("")
            self._set_gate_overlay(None)
            return False
        needs = tunnel.needs_tunnel(self._get_os_version())
        gated = needs and not tunnel.is_tunnel_running()
        hint = i18n.t("diagnostics.tunnel_required_hint") if gated else ""
        for tile in self._all_tiles:
            tile.setEnabled(not gated)
            tile.setToolTip(hint)
        # Centered mask over the whole tab when gated; cleared once tunnel is up.
        self._set_gate_overlay(i18n.t("diagnostics.tunnel_required_goto") if gated else None)
        return gated

    # -------------------------------------------------------------- tunnel

    def on_tab_activated(self) -> None:
        """Called by the main window when this tab becomes the current one.

        The XPC tunnel is global state that can change while another tab is shown
        (or before this tab is first entered), so re-poll it on activation instead
        of relying solely on device-switch (set_target).
        """
        self._refresh_features()

    # --------------------------------------------------------- power actions

    def _confirm_power(self, action: str, fn: Callable[[str], dict]) -> None:
        target = self._get_target()
        if not target or self._op_in_flight:
            return
        reply = QMessageBox.question(
            self,
            i18n.t(f"diagnostics.confirm.{action}.title"),
            i18n.t(f"diagnostics.confirm.{action}.body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return  # user cancelled — no device request is made
        self._op_in_flight = True
        self._set_enabled(False)
        self._set_status(i18n.t(f"diagnostics.status.{action}_sending"))
        self.runner.submit(
            lambda: fn(target),
            on_done=lambda result: self._on_power_done(action, result),
            on_error=lambda e: self._on_op_error(e),
        )

    def _on_power_done(self, action: str, result: dict) -> None:
        self._op_in_flight = False
        # A successful restart/shutdown drops the tunnel as the device reboots, so
        # re-derive tile state from the (possibly changed) tunnel readiness.
        self._refresh_features()
        if not result.get("ok"):
            self._set_status(localize_error(result.get("error")))
            return
        self._set_status(i18n.t(f"diagnostics.status.{action}_sent"))

    # ----------------------------------------------------------- info queries

    def _run_info(self, name: str, fn: Callable[[str], dict]) -> None:
        target = self._get_target()
        if not target or self._op_in_flight:
            return
        self._op_in_flight = True
        self._set_enabled(False)
        self._set_status(i18n.t("diagnostics.status.querying"))
        self.runner.submit(
            lambda: fn(target),
            on_done=lambda result: self._on_info_done(name, result),
            on_error=lambda e: self._on_op_error(e),
        )

    def _on_info_done(self, name: str, result: dict) -> None:
        self._op_in_flight = False
        self._refresh_features()
        if not result.get("ok"):
            self._set_status(localize_error(result.get("error")))
            return
        info = (result.get("data") or {}).get("info", {})
        self._set_status(i18n.t("diagnostics.status.done"))
        self._show_result(i18n.t(f"diagnostics.tile.{name}.title"), info)

    def _on_op_error(self, error: str) -> None:
        self._op_in_flight = False
        self._refresh_features()
        self._set_status(i18n.t("diagnostics.status.failed", error=error))

    # ------------------------------------------------------------- result UI

    def _show_result(self, title: str, data: object) -> None:
        """Open a non-modal, read-only, copyable window with the query result."""
        try:
            # default=str keeps datetimes / bytes-ish values renderable.
            text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = str(data)

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(560, 460)
        layout = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(text)
        install_plaintext_copy_menu(edit)
        layout.addWidget(edit)
        close_btn = QPushButton(i18n.t("common.close"))
        close_btn.clicked.connect(dlg.close)
        layout.addWidget(close_btn)

        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._result_dialogs.append(dlg)
        dlg.destroyed.connect(lambda *_: self._forget_dialog(dlg))
        dlg.show()
        dlg.raise_()

    def _forget_dialog(self, dlg: QDialog) -> None:
        try:
            self._result_dialogs.remove(dlg)
        except ValueError:
            pass

    # --------------------------------------------------------------- status

    def _set_status(self, text: str) -> None:
        self._status_text = text or ""
        self.status.setToolTip(self._status_text)
        self.status.setText(self._status_text)
