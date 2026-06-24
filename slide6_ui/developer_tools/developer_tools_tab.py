"""developer_tools_tab.py — the "开发者工具" tab (DDI / DVT, Phase 1).

Layout: a DDI status bar on top (mount state + mount/unmount controls) and a
feature-tile grid below (process management, virtual location). The feature
tiles stay disabled until the DeveloperDiskImage is mounted, then auto-enable —
the grid is intended to grow with Phase 2 DVT tools.

DDI mount/unmount/status run over usbmux lockdown and need no XPC tunnel. The
DVT-backed features (process / location) additionally require the tunnel on
iOS 17+, so a tunnel hint + launch affordance is shown for those devices. All
blocking calls go through the shared AsyncRunner.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.file_dialogs import open_existing_file
from ..common.feature_tile import FeatureTile
from ..common.flow_layout import FlowLayout
from ..common.gate_overlay import GatedTabMixin
from ..common import readiness, tunnel
from ..common.workers import AsyncRunner
from ..syslog import LogDialog
from .condition_inducer_dialog import ConditionInducerDialog
from .location_dialog import LocationDialog
from .network_monitor_dialog import NetworkMonitorDialog
from .performance_dialog import PerformanceDialog
from .web_inspector_dialog import WebInspectorDialog
from .process_dialog import ProcessDialog
from .tunnel_manager_dialog import TunnelManagerDialog

logger = logging.getLogger(__name__)

# Mount-method picker labels mapped to the platform-layer method keys. The
# "auto" flow is version-aware and consumes the DDI source config from Settings;
# the old explicit personalized/developer methods are folded into it.
# Mount-method picker: stable keys mapped to i18n label keys (labels resolved lazily).
_MOUNT_METHOD_KEYS = ["auto", "manual"]


def _mount_method_labels() -> list[str]:
    return [i18n.t(f"dev_tools.mount_method.{k}") for k in _MOUNT_METHOD_KEYS]


# Card-like feature button (title + muted subtitle), shared with the Diagnostics
# tab. Aliased to the historic local name to keep existing call sites unchanged.
_FeatureTile = FeatureTile

# DDI source-config keys (mirror slide6_ui/main_window.py — keep in sync).
_SETTINGS_ORG = "unnamed"
_SETTINGS_APP = "cabled_ios"
_DDI_LOCAL_ENABLED_KEY = "settings/ddi_local_enabled"
_DDI_LEGACY_DIR_KEY = "settings/ddi_legacy_dir"
_DDI_MODERN_DIR_KEY = "settings/ddi_modern_dir"
_DDI_GITHUB_ENABLED_KEY = "settings/ddi_github_enabled"
_DDI_GITHUB_TOKEN_KEY = "settings/ddi_github_token"
_DDI_GITHUB_SAVE_DIR_KEY = "settings/ddi_github_save_dir"
_DDI_SOURCE_PRIORITY_KEY = "settings/ddi_source_priority"
_DDI_DEFAULT_PRIORITY = "local,github"


class DeveloperToolsTab(GatedTabMixin, QWidget):
    """The "开发者工具" tab: DDI mount state + DVT feature tiles."""

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
        self._ios_major = 0
        self._mounted = False
        self._status_loading = False
        # DVT-readiness probe state: after a successful mount the device may need
        # up to a few minutes to finalise the (personalized) image before its
        # developer services answer. We gate the feature tiles on a background
        # readiness probe and keep the label showing "准备中" until it resolves.
        self._ready_probing = False
        self._ready_token = 0
        # Whether the DVT / RSD developer-services path is usable (gates feature
        # tiles together with mount state + tunnel; see _refresh_features).
        self._dvt_ready = False
        # Open sub-feature windows, keyed by feature name. At most one window per
        # feature: re-triggering raises the existing one instead of opening a new.
        self._subwindows: dict[str, QWidget] = {}
        # While a mount/unmount RPC is in flight the device-side mounter is busy;
        # suppress concurrent ddi_status queries so they don't time out and get
        # mistaken for an operation failure.
        self._op_in_flight = False
        # Live system-log windows opened from the log tile (kept so their stream
        # threads can be stopped on app exit). The log viewer needs no DDI/tunnel.
        self._log_dialogs: list[LogDialog] = []
        self._build_ui()
        self._wire()
        self.init_gate()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        # Unified, tight row spacing so the DDI and tunnel status rows sit close
        # and natural; the tunnel row's wrapper margins are zeroed below so it
        # does not add an extra gap on top of this spacing.
        root.setSpacing(6)

        # DDI status bar.
        ddi_row = QHBoxLayout()
        self.ddi_label = QLabel(i18n.t("dev_tools.ddi.unknown"))
        self.mount_btn = QPushButton(i18n.t("dev_tools.ddi.mount"))
        self.unmount_btn = QPushButton(i18n.t("dev_tools.ddi.unmount"))
        self.ddi_refresh_btn = QPushButton(i18n.t("dev_tools.ddi.refresh"))
        ddi_row.addWidget(self.ddi_label, 1)
        ddi_row.addWidget(self.mount_btn)
        ddi_row.addWidget(self.unmount_btn)
        ddi_row.addWidget(self.ddi_refresh_btn)
        root.addLayout(ddi_row)

        # XPC tunnel status panel (iOS 17+ only). Reflects running state and
        # offers start (when down) or stop + restart (when up). All actions reuse
        # the native-authorization tunnel helpers via the AsyncRunner.
        tunnel_row = QHBoxLayout()
        # Zero the wrapper's margins so the tunnel row aligns with the DDI row
        # and inherits only the unified root spacing (no extra vertical gap).
        tunnel_row.setContentsMargins(0, 0, 0, 0)
        self.tunnel_label = QLabel(i18n.t("dev_tools.tunnel.unknown"))
        self.tunnel_btn = QPushButton(i18n.t("dev_tools.tunnel.start"))
        self.tunnel_stop_btn = QPushButton(i18n.t("dev_tools.tunnel.stop"))
        self.tunnel_restart_btn = QPushButton(i18n.t("dev_tools.tunnel.restart"))
        self.tunnel_refresh_btn = QPushButton(i18n.t("dev_tools.tunnel.refresh"))
        # Manage ALL active tunneld processes (any port), not just the current
        # one — discovery needs no elevation; batch-kill uses a single auth.
        self.tunnel_manage_btn = QPushButton(i18n.t("dev_tools.tunnel.manage"))
        tunnel_row.addWidget(self.tunnel_label, 1)
        tunnel_row.addWidget(self.tunnel_btn)
        tunnel_row.addWidget(self.tunnel_stop_btn)
        tunnel_row.addWidget(self.tunnel_restart_btn)
        tunnel_row.addWidget(self.tunnel_refresh_btn)
        tunnel_row.addWidget(self.tunnel_manage_btn)
        self.tunnel_widget = QWidget()
        self.tunnel_widget.setLayout(tunnel_row)
        self.tunnel_widget.setVisible(False)
        root.addWidget(self.tunnel_widget)

        # Feature-tile flow grid: evenly spaced cards that wrap responsively
        # (more per row when wide, fewer when narrow) with identical horizontal
        # and vertical gaps. Extensible for future tools — just add more tiles.
        flow = FlowLayout(spacing=12)
        self._feature_buttons: list[QToolButton] = []
        self.process_tile = self._make_tile(
            i18n.t("dev_tools.tile.process_title"), i18n.t("dev_tools.tile.process_sub")
        )
        self.location_tile = self._make_tile(
            i18n.t("dev_tools.tile.location_title"), i18n.t("dev_tools.tile.location_sub")
        )
        self.performance_tile = self._make_tile(
            i18n.t("dev_tools.tile.performance_title"),
            i18n.t("dev_tools.tile.performance_sub"),
        )
        self.condition_tile = self._make_tile(
            i18n.t("dev_tools.tile.condition_title"),
            i18n.t("dev_tools.tile.condition_sub"),
        )
        self.network_tile = self._make_tile(
            i18n.t("dev_tools.tile.network_title"),
            i18n.t("dev_tools.tile.network_sub"),
        )
        # Web Inspector is a lockdown service: it needs tunnel (17+) but NOT a
        # mounted DDI, so it is not DDI-gated (not in _feature_buttons); a missing
        # tunnel surfaces as a readable error inside the dialog at runtime.
        _wi_title = i18n.t("dev_tools.tile.webinspector_title")
        _wi_sub = i18n.t("dev_tools.tile.webinspector_sub")
        self.webinspector_tile = _FeatureTile(_wi_title, _wi_sub)
        flow.addWidget(self.process_tile)
        flow.addWidget(self.location_tile)
        flow.addWidget(self.performance_tile)
        flow.addWidget(self.condition_tile)
        flow.addWidget(self.network_tile)
        flow.addWidget(self.webinspector_tile)
        # System log is a lockdown service: it needs neither DDI nor a tunnel, so
        # this tile stays enabled regardless of mount state (not in _feature_buttons).
        # The catalog value packs title + description on two lines; split it so the
        # tile renders the same layered title/subtitle as the other cards.
        _syslog_title, _, _syslog_sub = i18n.t("dev_tools.tile.syslog").partition("\n")
        self.syslog_tile = _FeatureTile(_syslog_title, _syslog_sub)
        flow.addWidget(self.syslog_tile)
        root.addLayout(flow)
        # Keep tiles packed at the top; absorb extra vertical space below them.
        root.addStretch(1)

        # Bottom status. It MUST NOT widen the window when a long error appears,
        # so its horizontal size hint is ignored (it only consumes available
        # width) and long text is elided to at most 3 lines (full text in
        # tooltip). _status_text holds the untruncated string for re-eliding on
        # resize. See _set_status / _elide_status / resizeEvent.
        self.status = QLabel(i18n.t("common.select_device_first"))
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._status_text = i18n.t("common.select_device_first")
        root.addWidget(self.status)

    def _make_tile(self, title: str, subtitle: str) -> QToolButton:
        """Create a large, card-like feature tile with a layered title/subtitle."""
        btn = _FeatureTile(title, subtitle)
        btn.setEnabled(False)
        self._feature_buttons.append(btn)
        return btn

    def _wire(self) -> None:
        self.ddi_refresh_btn.clicked.connect(self.refresh_status)
        self.mount_btn.clicked.connect(self._on_mount_clicked)
        self.unmount_btn.clicked.connect(self._on_unmount_clicked)
        self.tunnel_btn.clicked.connect(self._on_start_tunnel)
        self.tunnel_stop_btn.clicked.connect(self._on_stop_tunnel)
        self.tunnel_restart_btn.clicked.connect(self._on_restart_tunnel)
        self.tunnel_refresh_btn.clicked.connect(self._on_refresh_tunnel)
        self.tunnel_manage_btn.clicked.connect(self._open_tunnel_manager)
        self.process_tile.clicked.connect(self._open_process)
        self.location_tile.clicked.connect(self._open_location)
        self.performance_tile.clicked.connect(self._open_performance)
        self.condition_tile.clicked.connect(self._open_condition)
        self.network_tile.clicked.connect(self._open_network)
        self.webinspector_tile.clicked.connect(self._open_webinspector)
        self.syslog_tile.clicked.connect(self._open_syslog)

    # ------------------------------------------------------------- target

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        self._mounted = False
        self._dvt_ready = False
        # Invalidate any in-flight readiness probe from the previous device.
        self._ready_probing = False
        self._ready_token += 1
        self._ios_major = tunnel.ios_major(self._get_os_version())
        self.tunnel_widget.setVisible(tunnel.needs_tunnel(self._get_os_version()))
        self._refresh_tunnel_panel()
        self._refresh_features()
        if target:
            self.refresh_status()
        else:
            self.ddi_label.setText(i18n.t("dev_tools.ddi.unknown"))
            self._set_controls_enabled(False)
            self._set_status(i18n.t("dev_tools.no_device"))

    def shutdown(self) -> None:
        """Release background sessions / log streams on app exit."""
        # Stop any live system-log streams so their QThreads don't outlive the app.
        for dlg in list(self._log_dialogs):
            try:
                dlg.shutdown()
            except RuntimeError:
                pass  # already deleted
        # Close any open non-modal sub-feature windows (process / location).
        for dlg in list(self._subwindows.values()):
            try:
                dlg.close()
            except RuntimeError:
                pass  # already deleted
        target = self._get_target()
        if not target:
            return
        # Best-effort: clear simulation so no background session is left running.
        self.runner.submit(lambda: api.clear_location(target))

    # ----------------------------------------------------------- DDI state

    def _set_controls_enabled(self, enabled: bool) -> None:
        # The refresh button stays enabled at all times (re-entrancy is guarded
        # by _status_loading); only the mount/unmount actions are gated here.
        self.mount_btn.setEnabled(enabled)
        self.unmount_btn.setEnabled(enabled)

    def _refresh_features(self) -> None:
        """Drive feature-tile enabled state + tooltip from the readiness check.

        Disabled-gating: tiles are enabled only when every applicable
        precondition is met; otherwise they are disabled and their tooltip
        explains what is missing (tunnel / DDI / RSD). Called whenever a
        precondition changes (device switch, tunnel op, DDI/DVT state change).
        """
        os_version = self._get_os_version()
        needs_tunnel = tunnel.needs_tunnel(os_version)
        result = readiness.evaluate(
            os_version,
            tunnel_running=tunnel.is_tunnel_running() if needs_tunnel else False,
            ddi_mounted=self._mounted,
            rsd_ok=self._dvt_ready,
        )
        for btn in self._feature_buttons:
            btn.setEnabled(result.ready)
            btn.setToolTip("" if result.ready else result.message)

    def _refresh_tunnel_panel(self) -> None:
        """Update the iOS 17+ tunnel panel label + buttons from running state."""
        if not self.tunnel_widget.isVisible():
            return
        running = tunnel.is_tunnel_running()
        self.tunnel_label.setText(
            i18n.t("dev_tools.tunnel.running") if running else i18n.t("dev_tools.tunnel.stopped")
        )
        # When up: stop + restart are relevant; when down: only start.
        self.tunnel_btn.setVisible(not running)
        self.tunnel_btn.setEnabled(not running)
        self.tunnel_stop_btn.setVisible(running)
        self.tunnel_restart_btn.setVisible(running)
        self.tunnel_stop_btn.setEnabled(running)
        self.tunnel_restart_btn.setEnabled(running)

    def _cancel_ready_probe(self) -> None:
        """Invalidate any in-flight DVT readiness probe and restore refresh."""
        self._ready_probing = False
        self._ready_token += 1
        self.ddi_refresh_btn.setEnabled(True)

    def _sync_dvt_state_for_tunnel(self) -> None:
        """Recompute DVT gating immediately after a tunnel transition."""
        if not tunnel.needs_tunnel(self._get_os_version()):
            return
        self._dvt_ready = False
        self._refresh_features()

    # ----------------------------------------------------------- status text

    def _set_status(self, text: str) -> None:
        """Set bottom status text, elided to <=3 lines so it never widens the tab."""
        self._status_text = text or ""
        self.status.setToolTip(self._status_text)
        self._elide_status()

    def _elide_status(self) -> None:
        """Elide the stored status text to at most 3 lines at the current width."""
        text = self._status_text
        width = max(1, self.status.width())
        fm = QFontMetrics(self.status.font())
        # Greedily wrap into at most 3 lines; tail-elide the 3rd if it overflows.
        words = text.split(" ")
        lines: list[str] = []
        cur = ""
        for word in words:
            trial = word if not cur else cur + " " + word
            if fm.horizontalAdvance(trial) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
                if len(lines) == 3:
                    break
        if len(lines) < 3 and cur:
            lines.append(cur)
        if len(lines) == 3:
            # There may be leftover content beyond 3 lines: elide the last line.
            consumed = len(" ".join(lines))
            if consumed < len(text):
                lines[2] = fm.elidedText(
                    lines[2] + " …", Qt.ElideRight, width
                )
        self.status.setText("\n".join(lines) if lines else "")

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._elide_status()

    def refresh_status(self) -> None:
        target = self._get_target()
        if not target:
            self._set_status(i18n.t("dev_tools.no_device"))
            return
        # Once the UI already knows "DDI mounted + iOS 17+ tunnel not running",
        # a direct ddi_status round-trip is expected to stall in this device
        # state. Short-circuit to the actionable guidance instead of issuing a
        # query that predictably times out.
        if self._mounted and tunnel.needs_tunnel(self._get_os_version()) and not tunnel.is_tunnel_running():
            self._refresh_tunnel_panel()
            self._refresh_features()
            self._set_status(i18n.t("dev_tools.ddi.mounted_need_tunnel"))
            return
        if self._ready_probing:
            # Keep showing "已挂载（准备中…）" — a mounter query here would just
            # hit the busy service and clobber the readiness state.
            return
        if self._op_in_flight:
            # A mount/unmount is running; the mounter is busy and a status query
            # would just time out. The op's own callback updates the state.
            return
        if self._status_loading:
            return  # a query is already in flight; ignore the extra click
        self._status_loading = True
        self._set_status(i18n.t("dev_tools.ddi.querying"))
        self.runner.submit(
            lambda: api.ddi_status(target),
            on_done=self._on_status,
            on_error=lambda e: self._fail(i18n.t("dev_tools.ddi.query_failed_detail", error=e)),
        )

    def _on_status(self, result: dict) -> None:
        self._status_loading = False
        if not result.get("ok"):
            self._fail(localize_error(result.get("error")))
            return
        data = result["data"]
        self._mounted = bool(data.get("mounted"))
        self._ios_major = int(data.get("iosMajor", self._ios_major))
        dev_mode = data.get("developerMode", True)
        dev_hint = "" if dev_mode else i18n.t("dev_tools.ddi.dev_mode_off")
        if self._mounted:
            images = data.get("images") or []
            if images:
                # Show the actual mounted image type(s) + path(s).
                detail = "；".join(
                    f"{img.get('diskImageType') or '?'} @ {img.get('mountPath') or '?'}"
                    for img in images
                )
            else:
                detail = data.get("imageType", "")
            self.ddi_label.setText(i18n.t("dev_tools.ddi.mounted_detail", detail=detail, hint=dev_hint))
        else:
            self.ddi_label.setText(i18n.t("dev_tools.ddi.not_mounted", hint=dev_hint))
        self.mount_btn.setEnabled(not self._mounted)
        self.unmount_btn.setEnabled(self._mounted)
        self._refresh_tunnel_panel()
        if not self._mounted:
            self._dvt_ready = False
            self._refresh_features()
            self._set_status(i18n.t("dev_tools.ddi.unmounted_hint"))
            return
        if tunnel.needs_tunnel(self._get_os_version()):
            # iOS 17+: mounted is necessary but not sufficient — the RSD service
            # must also be enumerated over the tunnel. Probing RSD without a
            # running tunnel would wrongly report "service inactive"; gate on the
            # tunnel first and tell the user to start it.
            self._dvt_ready = False
            self._refresh_features()
            if not tunnel.is_tunnel_running():
                self._set_status(i18n.t("dev_tools.ddi.mounted_need_tunnel"))
                return
            self._set_status(i18n.t("dev_tools.ddi.mounted_probing"))
            self._probe_rsd(target=self._get_target())
        else:
            # iOS < 17: DDI mount is the only gate.
            self._dvt_ready = True
            self._refresh_features()
            self._set_status(i18n.t("dev_tools.ddi.mounted_unlocked"))

    def _probe_rsd(self, target: str) -> None:
        """Lightweight RSD-service probe (iOS 17+) to set _dvt_ready + gate tiles."""
        if not target:
            return
        self.runner.submit(
            lambda: api.rsd_service_available(target),
            on_done=self._on_rsd_probe,
            on_error=lambda e: self._on_rsd_probe({"ok": False}),
        )

    def _on_rsd_probe(self, result: dict) -> None:
        if result.get("ok"):
            available = bool(result.get("data", {}).get("available"))
        else:
            # Inconclusive probe (timeout / handshake error under load): tunnel +
            # DDI are up, so don't falsely gate features on a probe miss — assume
            # ready. Only a definitive ok=True/available=False keeps tiles off.
            available = True
        self._dvt_ready = available
        self._refresh_features()
        if available:
            self._set_status(i18n.t("dev_tools.ddi.service_ready"))
        else:
            self._set_status(i18n.t("dev_tools.ddi.service_inactive"))

    def _fail(self, message: str) -> None:
        self._status_loading = False
        self._set_status(message)

    # --------------------------------------------------------------- mount

    def _on_mount_clicked(self) -> None:
        target = self._get_target()
        if not target:
            return
        labels = _mount_method_labels()
        label, ok = QInputDialog.getItem(
            self, i18n.t("dev_tools.mount.pick_title"), i18n.t("dev_tools.mount.pick_label"),
            labels, 0, False,
        )
        if not ok:
            return
        method = dict(zip(labels, _MOUNT_METHOD_KEYS))[label]
        logger.info("user requested DDI mount: method=%s target=%s", method, target)
        kwargs: dict = {}
        if method == "manual":
            files = self._collect_manual_files()
            if files is None:
                return  # cancelled
            kwargs = files
            self._set_status(i18n.t("dev_tools.mount.mounting", target=target))
        else:  # auto: feed the source config from Settings
            kwargs = self._read_ddi_source_config()
            if not kwargs.get("sources"):
                self._set_status(i18n.t("dev_tools.mount.no_source"))
                return
            self._set_status(i18n.t("dev_tools.mount.mounting_auto", target=target))
        self._op_in_flight = True
        self._set_controls_enabled(False)
        self.runner.submit(
            lambda: api.ddi_mount(target, method, **kwargs),
            on_done=self._on_mounted,
            on_error=lambda e: self._after_mount(i18n.t("dev_tools.mount.mount_failed_detail", error=e)),
        )

    def _read_ddi_source_config(self) -> dict:
        """Read the DDI source config (priority/dirs/token) from Settings.

        Returns kwargs for ``api.ddi_mount`` with ``sources`` already filtered to
        the enabled ones in priority order (disabled sources are dropped).
        """
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        local_on = bool(s.value(_DDI_LOCAL_ENABLED_KEY, True, type=bool))
        github_on = bool(s.value(_DDI_GITHUB_ENABLED_KEY, True, type=bool))
        raw = s.value(_DDI_SOURCE_PRIORITY_KEY, _DDI_DEFAULT_PRIORITY, type=str) or ""
        order = [x.strip() for x in raw.split(",") if x.strip() in ("local", "github")]
        for src in ("local", "github"):
            if src not in order:
                order.append(src)
        enabled = {"local": local_on, "github": github_on}
        sources = [src for src in order if enabled.get(src)]
        return {
            "sources": sources,
            "legacy_dir": s.value(_DDI_LEGACY_DIR_KEY, "", type=str) or None,
            "modern_dir": s.value(_DDI_MODERN_DIR_KEY, "", type=str) or None,
            "github_token": s.value(_DDI_GITHUB_TOKEN_KEY, "", type=str) or None,
            "github_save_dir": s.value(_DDI_GITHUB_SAVE_DIR_KEY, "", type=str) or None,
        }

    def _collect_manual_files(self) -> "dict | None":
        """Collect the local image files required for a manual mount."""
        image = open_existing_file(
            self, i18n.t("dev_tools.mount.pick_image"),
            ["Disk image (*.dmg)", i18n.t("dev_tools.mount.all_files")],
        )
        if not image:
            return None
        if self._ios_major >= 17:
            manifest = open_existing_file(
                self, i18n.t("dev_tools.mount.pick_manifest"),
                ["Plist (*.plist)", i18n.t("dev_tools.mount.all_files")],
            )
            if not manifest:
                return None
            trustcache = open_existing_file(
                self, i18n.t("dev_tools.mount.pick_trustcache"),
                [i18n.t("dev_tools.mount.all_files")],
            )
            if not trustcache:
                return None
            return {"image": image, "build_manifest": manifest, "trustcache": trustcache}
        signature = open_existing_file(
            self, i18n.t("dev_tools.mount.pick_signature"),
            ["Signature (*.signature)", i18n.t("dev_tools.mount.all_files")],
        )
        if not signature:
            return None
        return {"image": image, "signature": signature}

    def _on_mounted(self, result: dict) -> None:
        self._op_in_flight = False
        if not result.get("ok"):
            self._after_mount(localize_error(result.get("error")))
            return
        # mount() returning success is the authoritative "mounted" signal — reflect
        # it optimistically. Do NOT query ddi_status now: right after a fresh
        # (personalized) mount the device-side mounter stays unresponsive for up
        # to a few minutes, so we instead probe DVT readiness in the background.
        target = self._get_target()
        self._mounted = True
        self._dvt_ready = False
        self.mount_btn.setEnabled(False)
        self.unmount_btn.setEnabled(True)
        self._refresh_features()
        self.ddi_label.setText(i18n.t("dev_tools.ddi.mounted_preparing"))
        self._set_status(i18n.t("dev_tools.mount.mount_ok", target=target))
        # iOS 17+: when a tunnel is already running, probe DVT readiness directly —
        # restarting the tunnel after a mount is not required for the developer
        # services to become usable. If no tunnel is running yet, ask the user to
        # start one (a fresh launch enumerates the just-mounted services).
        if tunnel.needs_tunnel(self._get_os_version()):
            if tunnel.is_tunnel_running():
                self._start_ready_probe(target)
                return
            # No tunnel yet: probing DVT readiness here would just block on the
            # long ddi_wait_ready timeout. Tell the user to start the tunnel
            # first; a fresh launch will enumerate the just-mounted services.
            self._refresh_features()
            self._set_status(i18n.t("dev_tools.ddi.mounted_need_tunnel"))
            return
        self._start_ready_probe(target)

    def _on_tunnel_restarted(self, ok: bool, target: str) -> None:
        self._set_tunnel_busy(False)
        self._refresh_tunnel_panel()
        if ok:
            self._set_status(i18n.t("dev_tools.tunnel.restarted"))
        else:
            self._set_status(i18n.t("dev_tools.tunnel.restart_failed"))
        # Re-probe DVT readiness only when a DDI is mounted (otherwise the probe
        # would just fail); the tunnel refresh re-enumerates RSD services.
        if target and self._mounted:
            self._start_ready_probe(target)
        else:
            self._refresh_features()

    def _start_ready_probe(self, target: str) -> None:
        """Probe DVT readiness in the background; gate feature tiles on success."""
        if not target:
            return
        self._ready_probing = True
        self._ready_token += 1
        token = self._ready_token
        # Refresh is suppressed while probing (see refresh_status); only the
        # readiness result flips the label/tiles, so a stale mounter query can't.
        self.ddi_refresh_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.ddi_wait_ready(target, timeout=500.0),
            on_done=lambda r: self._on_ready(r, token),
            on_error=lambda e: self._on_ready({"ok": False}, token),
        )

    def _on_ready(self, result: dict, token: int) -> None:
        if token != self._ready_token:
            return  # superseded by a newer mount / device switch
        self._ready_probing = False
        self.ddi_refresh_btn.setEnabled(True)
        if result.get("ok"):
            self._dvt_ready = True
            self.ddi_label.setText(i18n.t("dev_tools.ddi.mounted"))
            self._refresh_features()
            self._set_status(i18n.t("dev_tools.ready.unlocked"))
        else:
            # On iOS 17+ with a running tunnel, a mounted-but-unready developer
            # path usually means the current tunnel session never enumerated the
            # service; guide the user to restart the tunnel rather than showing a
            # generic timeout. Lower versions still surface a plain ready timeout.
            self._dvt_ready = False
            self._refresh_features()
            if tunnel.needs_tunnel(self._get_os_version()) and tunnel.is_tunnel_running():
                self.ddi_label.setText(i18n.t("dev_tools.ddi.mounted"))
                self._set_status(i18n.t("dev_tools.ddi.service_inactive"))
            else:
                self.ddi_label.setText(i18n.t("dev_tools.ddi.mounted_timeout"))
                self._set_status(i18n.t("dev_tools.ready.timeout"))

    def _after_mount(self, message: str) -> None:
        self._op_in_flight = False
        self._set_controls_enabled(True)
        self._set_status(message)

    # ------------------------------------------------------------- unmount

    def _on_unmount_clicked(self) -> None:
        target = self._get_target()
        if not target:
            return
        logger.info("user requested DDI unmount: target=%s", target)
        # Cancel any in-flight readiness probe and re-enable refresh.
        self._cancel_ready_probe()
        self._dvt_ready = False
        self._refresh_features()
        self._set_status(i18n.t("dev_tools.unmount.unmounting", target=target))
        self._op_in_flight = True
        self._set_controls_enabled(False)
        self.runner.submit(
            lambda: api.ddi_unmount(target),
            on_done=self._on_unmounted,
            on_error=lambda e: self._after_mount(i18n.t("dev_tools.unmount.failed_detail", error=e)),
        )

    def _on_unmounted(self, result: dict) -> None:
        self._op_in_flight = False
        if not result.get("ok"):
            self._after_mount(localize_error(result.get("error")))
            return
        # unmount() returning success is authoritative. Reflect "未挂载"
        # optimistically and do NOT query ddi_status now: right after (un)mount on
        # iOS 17+ the mounter stays unresponsive, so a refresh would just time out
        # and be mistaken for an unmount failure. The user can refresh later.
        self._mounted = False
        self._dvt_ready = False
        self._refresh_features()
        self.mount_btn.setEnabled(True)
        self.unmount_btn.setEnabled(False)
        self.ddi_label.setText(i18n.t("dev_tools.ddi.not_mounted", hint=""))
        self._set_status(i18n.t("dev_tools.unmount.done"))
        # On iOS 17+ with Xcode installed, macOS CoreDevice daemons auto-remount
        # the personalized DDI within seconds, so a later refresh may show it
        # mounted again — explain this once so it is not mistaken for a failure.
        if self._ios_major >= 17:
            QMessageBox.information(
                self, i18n.t("dev_tools.unmount.info_title"),
                i18n.t("dev_tools.unmount.info_body"),
            )

    # -------------------------------------------------------------- tunnel

    def _set_tunnel_busy(self, busy: bool) -> None:
        """Disable all tunnel controls while a tunnel op is in flight."""
        for btn in (self.tunnel_btn, self.tunnel_stop_btn, self.tunnel_restart_btn):
            btn.setEnabled(not busy)

    def _on_start_tunnel(self) -> None:
        if tunnel.is_tunnel_running():
            self._set_status(i18n.t("dev_tools.tunnel.already_running"))
            self._refresh_tunnel_panel()
            return
        self._set_status(i18n.t("dev_tools.tunnel.starting"))
        self._set_tunnel_busy(True)
        self.runner.submit(
            tunnel.launch_tunneld,
            on_done=self._on_tunnel_started,
            on_error=lambda e: self._after_tunnel(i18n.t("dev_tools.tunnel.start_failed_detail", error=e)),
        )

    def _on_stop_tunnel(self) -> None:
        self._cancel_ready_probe()
        self._sync_dvt_state_for_tunnel()
        self._set_status(i18n.t("dev_tools.tunnel.stopping"))
        self._set_tunnel_busy(True)
        self.runner.submit(
            tunnel.stop_tunneld,
            on_done=self._on_tunnel_stopped,
            on_error=lambda e: self._after_tunnel(i18n.t("dev_tools.tunnel.stop_failed_detail", error=e)),
        )

    def _on_restart_tunnel(self) -> None:
        self._cancel_ready_probe()
        self._sync_dvt_state_for_tunnel()
        self._set_status(i18n.t("dev_tools.tunnel.restarting_once"))
        self._set_tunnel_busy(True)
        target = self._get_target()
        self.runner.submit(
            tunnel.restart_tunneld,
            on_done=lambda ok: self._on_tunnel_restarted(bool(ok), target),
            on_error=lambda e: self._on_tunnel_restarted(False, target),
        )

    def _on_tunnel_started(self, ok: bool) -> None:
        self._after_tunnel(i18n.t("dev_tools.tunnel.started_ok") if ok else i18n.t("dev_tools.tunnel.start_failed"))
        # iOS 17+ DVT readiness needs the tunnel; if the DDI is already mounted
        # but not yet ready (e.g. mounted before the tunnel was up), re-probe now.
        if ok and self._mounted and not self._ready_probing:
            target = self._get_target()
            if target:
                self.ddi_label.setText(i18n.t("dev_tools.ddi.mounted_preparing"))
                self._set_status(i18n.t("dev_tools.tunnel.started_reprobe"))
                self._start_ready_probe(target)

    def _on_tunnel_stopped(self, ok: bool) -> None:
        self._set_tunnel_busy(False)
        self._refresh_tunnel_panel()
        self._sync_dvt_state_for_tunnel()
        if not ok:
            self._set_status(i18n.t("dev_tools.tunnel.stop_failed"))
            return
        if self._mounted and tunnel.needs_tunnel(self._get_os_version()):
            self._set_status(i18n.t("dev_tools.ddi.mounted_need_tunnel"))
            return
        self._set_status(i18n.t("dev_tools.tunnel.stopped_ok"))

    def on_tab_activated(self) -> None:
        """Called by the main window when this tab becomes the current one.

        The XPC tunnel is global state that can change while another tab is shown,
        so re-poll it on activation instead of relying solely on device-switch
        (set_target) or a manual refresh.
        """
        self._refresh_tunnel_panel()
        self._refresh_features()

    def _on_refresh_tunnel(self) -> None:
        """Re-read the tunnel running state and update the status label + tiles."""
        self._refresh_tunnel_panel()
        self._refresh_features()
        self._set_status(i18n.t("dev_tools.tunnel.refreshed"))

    def _after_tunnel(self, message: str) -> None:
        self._set_tunnel_busy(False)
        self._refresh_tunnel_panel()
        self._refresh_features()
        self._set_status(message)

    def _open_tunnel_manager(self) -> None:
        """Open the active-tunnel manager (list/batch-kill all tunneld procs)."""
        dlg = TunnelManagerDialog(self.runner, self)
        dlg.exec()
        # A batch kill may have stopped the current-port tunnel too; resync panel.
        self._refresh_tunnel_panel()
        self._refresh_features()

    # ------------------------------------------------------------ features

    def _open_subwindow(self, name: str, factory: "Callable[[], QWidget]") -> None:
        """Open (or raise) a non-modal sub-feature window — one per feature.

        Non-modal so the main UI and other sub-windows stay usable; singleton per
        feature so re-triggering brings the existing window to front instead of
        opening a duplicate. The window self-deletes on close (WA_DeleteOnClose)
        and is removed from the registry then.
        """
        existing = self._subwindows.get(name)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        dlg = factory()
        dlg.setModal(False)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._subwindows[name] = dlg
        dlg.destroyed.connect(lambda *_: self._subwindows.pop(name, None))
        dlg.show()

    def _open_process(self) -> None:
        target = self._get_target()
        if not target:
            return
        logger.info("open process manager: target=%s", target)
        self._open_subwindow(
            "process", lambda: ProcessDialog(self.runner, target, self)
        )

    def _open_location(self) -> None:
        target = self._get_target()
        if not target:
            return
        logger.info("open virtual location: target=%s", target)
        self._open_subwindow(
            "location", lambda: LocationDialog(self.runner, target, self)
        )

    def _open_performance(self) -> None:
        target = self._get_target()
        if not target:
            return
        logger.info("open performance monitor: target=%s", target)
        self._open_subwindow(
            "performance", lambda: PerformanceDialog(self.runner, target, self)
        )

    def _open_condition(self) -> None:
        target = self._get_target()
        if not target:
            return
        logger.info("open condition inducer: target=%s", target)
        self._open_subwindow(
            "condition", lambda: ConditionInducerDialog(self.runner, target, self)
        )

    def _open_network(self) -> None:
        target = self._get_target()
        if not target:
            return
        logger.info("open network monitor: target=%s", target)
        self._open_subwindow(
            "network", lambda: NetworkMonitorDialog(self.runner, target, self)
        )

    def _open_webinspector(self) -> None:
        target = self._get_target()
        if not target:
            return
        logger.info("open web inspector: target=%s", target)
        self._open_subwindow(
            "webinspector", lambda: WebInspectorDialog(self.runner, target, self)
        )

    def _open_syslog(self) -> None:
        target = self._get_target()
        if not target:
            self._set_status(i18n.t("dev_tools.no_device"))
            return
        logger.info("open system log: target=%s", target)
        dlg = LogDialog(self.runner, self._get_target, self._get_os_version, self)
        self._log_dialogs.append(dlg)
        dlg.destroyed.connect(lambda *_: self._forget_log_dialog(dlg))
        dlg.show()

    def _forget_log_dialog(self, dlg: LogDialog) -> None:
        try:
            self._log_dialogs.remove(dlg)
        except ValueError:
            pass
