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
    QFileDialog,
    QGridLayout,
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

from ..common import readiness, tunnel
from ..common.workers import AsyncRunner
from ..syslog import LogDialog
from .location_dialog import LocationDialog
from .process_dialog import ProcessDialog

logger = logging.getLogger(__name__)

# Mount-method picker labels mapped to the platform-layer method keys. The
# "auto" flow is version-aware and consumes the DDI source config from Settings;
# the old explicit personalized/developer methods are folded into it.
_MOUNT_METHODS = [
    ("自动（按系统版本）", "auto"),
    ("手动选择本地镜像文件", "manual"),
]

# DDI source-config keys (mirror slide6_ui/main_window.py — keep in sync).
_SETTINGS_ORG = "ios_ui_ta_proxy"
_SETTINGS_APP = "slide6_console"
_DDI_LOCAL_ENABLED_KEY = "settings/ddi_local_enabled"
_DDI_LEGACY_DIR_KEY = "settings/ddi_legacy_dir"
_DDI_MODERN_DIR_KEY = "settings/ddi_modern_dir"
_DDI_GITHUB_ENABLED_KEY = "settings/ddi_github_enabled"
_DDI_GITHUB_TOKEN_KEY = "settings/ddi_github_token"
_DDI_GITHUB_SAVE_DIR_KEY = "settings/ddi_github_save_dir"
_DDI_SOURCE_PRIORITY_KEY = "settings/ddi_source_priority"
_DDI_DEFAULT_PRIORITY = "local,github"


class DeveloperToolsTab(QWidget):
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

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # DDI status bar.
        ddi_row = QHBoxLayout()
        self.ddi_label = QLabel("DeveloperDiskImage：未知")
        self.mount_btn = QPushButton("挂载")
        self.unmount_btn = QPushButton("卸载")
        self.ddi_refresh_btn = QPushButton("刷新状态")
        ddi_row.addWidget(self.ddi_label, 1)
        ddi_row.addWidget(self.mount_btn)
        ddi_row.addWidget(self.unmount_btn)
        ddi_row.addWidget(self.ddi_refresh_btn)
        root.addLayout(ddi_row)

        # XPC tunnel status panel (iOS 17+ only). Reflects running state and
        # offers start (when down) or stop + restart (when up). All actions reuse
        # the native-authorization tunnel helpers via the AsyncRunner.
        tunnel_row = QHBoxLayout()
        self.tunnel_label = QLabel("XPC tunnel：未知")
        self.tunnel_btn = QPushButton("启动")
        self.tunnel_stop_btn = QPushButton("停止")
        self.tunnel_restart_btn = QPushButton("重启")
        tunnel_row.addWidget(self.tunnel_label, 1)
        tunnel_row.addWidget(self.tunnel_btn)
        tunnel_row.addWidget(self.tunnel_stop_btn)
        tunnel_row.addWidget(self.tunnel_restart_btn)
        self.tunnel_widget = QWidget()
        self.tunnel_widget.setLayout(tunnel_row)
        self.tunnel_widget.setVisible(False)
        root.addWidget(self.tunnel_widget)

        # Feature-tile grid (kept extensible for Phase 2 tools).
        grid = QGridLayout()
        self._feature_buttons: list[QToolButton] = []
        self.process_tile = self._make_tile("进程管理", "查看进程列表 / 启动 / 结束 / 明细")
        self.location_tile = self._make_tile("虚拟定位", "设定 / 清除虚拟 GPS 坐标")
        grid.addWidget(self.process_tile, 0, 0)
        grid.addWidget(self.location_tile, 0, 1)
        # System log is a lockdown service: it needs neither DDI nor a tunnel, so
        # this tile stays enabled regardless of mount state (not in _feature_buttons).
        self.syslog_tile = QToolButton()
        self.syslog_tile.setText("系统日志\n实时 syslog / oslog（按版本，无需 DDI）")
        self.syslog_tile.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.syslog_tile.setMinimumSize(220, 90)
        grid.addWidget(self.syslog_tile, 1, 0)
        grid.setRowStretch(2, 1)
        root.addLayout(grid)

        # Bottom status. It MUST NOT widen the window when a long error appears,
        # so its horizontal size hint is ignored (it only consumes available
        # width) and long text is elided to at most 3 lines (full text in
        # tooltip). _status_text holds the untruncated string for re-eliding on
        # resize. See _set_status / _elide_status / resizeEvent.
        self.status = QLabel("请选择一个设备")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._status_text = "请选择一个设备"
        root.addWidget(self.status)

    def _make_tile(self, title: str, subtitle: str) -> QToolButton:
        """Create a large, card-like feature tile button."""
        btn = QToolButton()
        btn.setText(f"{title}\n{subtitle}")
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn.setMinimumSize(220, 90)
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
        self.process_tile.clicked.connect(self._open_process)
        self.location_tile.clicked.connect(self._open_location)
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
            self.ddi_label.setText("DeveloperDiskImage：未知")
            self._set_controls_enabled(False)
            self._set_status("未选择设备")

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
        self.tunnel_label.setText("XPC tunnel：已启动" if running else "XPC tunnel：未启动")
        # When up: stop + restart are relevant; when down: only start.
        self.tunnel_btn.setVisible(not running)
        self.tunnel_btn.setEnabled(not running)
        self.tunnel_stop_btn.setVisible(running)
        self.tunnel_restart_btn.setVisible(running)
        self.tunnel_stop_btn.setEnabled(running)
        self.tunnel_restart_btn.setEnabled(running)

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
            self._set_status("未选择设备")
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
        self._set_status("正在查询 DDI 状态…")
        self.runner.submit(
            lambda: api.ddi_status(target),
            on_done=self._on_status,
            on_error=lambda e: self._fail(f"查询失败: {e}"),
        )

    def _on_status(self, result: dict) -> None:
        self._status_loading = False
        if not result.get("ok"):
            self._fail(result.get("error", {}).get("message", "查询失败"))
            return
        data = result["data"]
        self._mounted = bool(data.get("mounted"))
        self._ios_major = int(data.get("iosMajor", self._ios_major))
        dev_mode = data.get("developerMode", True)
        dev_hint = "" if dev_mode else "（开发者模式未开启）"
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
            self.ddi_label.setText(f"DeveloperDiskImage：已挂载（{detail}）{dev_hint}")
        else:
            self.ddi_label.setText(f"DeveloperDiskImage：未挂载{dev_hint}")
        self.mount_btn.setEnabled(not self._mounted)
        self.unmount_btn.setEnabled(self._mounted)
        self._refresh_tunnel_panel()
        if not self._mounted:
            self._dvt_ready = False
            self._refresh_features()
            self._set_status("DDI 未挂载，请先挂载以解锁功能")
            return
        if tunnel.needs_tunnel(self._get_os_version()):
            # iOS 17+: mounted is necessary but not sufficient — the RSD service
            # must also be enumerated. Probe it (lightweight) to gate features.
            self._dvt_ready = False
            self._refresh_features()
            self._set_status("DDI 已挂载，正在检测开发者服务就绪…")
            self._probe_rsd(target=self._get_target())
        else:
            # iOS < 17: DDI mount is the only gate.
            self._dvt_ready = True
            self._refresh_features()
            self._set_status("DDI 已挂载，功能已解锁")

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
            self._set_status("开发者服务已就绪，功能已解锁")
        else:
            self._set_status(
                "DDI 已挂载但开发者服务未生效：请重启 XPC tunnel 或重新挂载 DDI"
            )

    def _fail(self, message: str) -> None:
        self._status_loading = False
        self._set_status(message)

    # --------------------------------------------------------------- mount

    def _on_mount_clicked(self) -> None:
        target = self._get_target()
        if not target:
            return
        labels = [label for label, _ in _MOUNT_METHODS]
        label, ok = QInputDialog.getItem(
            self, "选择挂载方式", "DDI 挂载方式：", labels, 0, False
        )
        if not ok:
            return
        method = dict((lbl, m) for lbl, m in _MOUNT_METHODS)[label]
        logger.info("user requested DDI mount: method=%s target=%s", method, target)
        kwargs: dict = {}
        if method == "manual":
            files = self._collect_manual_files()
            if files is None:
                return  # cancelled
            kwargs = files
            self._set_status(f"正在挂载 DDI 到设备 {target}…")
        else:  # auto: feed the source config from Settings
            kwargs = self._read_ddi_source_config()
            if not kwargs.get("sources"):
                self._set_status(
                    "没有启用的 DDI 来源：请在 Settings → DDI Mount 启用本地或下载来源。"
                )
                return
            self._set_status(
                f"正在挂载 DDI 到设备 {target}…（本地优先；如需联网下载镜像首次可能较久）"
            )
        self._op_in_flight = True
        self._set_controls_enabled(False)
        self.runner.submit(
            lambda: api.ddi_mount(target, method, **kwargs),
            on_done=self._on_mounted,
            on_error=lambda e: self._after_mount(f"挂载失败: {e}"),
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
        image, _ = QFileDialog.getOpenFileName(
            self, "选择镜像文件 (Image.dmg / DeveloperDiskImage.dmg)", "",
            "Disk image (*.dmg);;所有文件 (*)",
        )
        if not image:
            return None
        if self._ios_major >= 17:
            manifest, _ = QFileDialog.getOpenFileName(
                self, "选择 BuildManifest.plist", "", "Plist (*.plist);;所有文件 (*)"
            )
            if not manifest:
                return None
            trustcache, _ = QFileDialog.getOpenFileName(
                self, "选择 Image.trustcache", "", "所有文件 (*)"
            )
            if not trustcache:
                return None
            return {"image": image, "build_manifest": manifest, "trustcache": trustcache}
        signature, _ = QFileDialog.getOpenFileName(
            self, "选择签名文件 (.signature)", "", "Signature (*.signature);;所有文件 (*)"
        )
        if not signature:
            return None
        return {"image": image, "signature": signature}

    def _on_mounted(self, result: dict) -> None:
        self._op_in_flight = False
        if not result.get("ok"):
            self._after_mount(result.get("error", {}).get("message", "挂载失败"))
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
        self.ddi_label.setText("DeveloperDiskImage：已挂载（准备中…）")
        self._set_status(f"已成功挂载 DDI 到设备 {target}，等待 DVT 就绪…")
        # iOS 17+: a tunnel established BEFORE this mount has a stale RSD service
        # list that lacks the just-published developer services (notably
        # com.apple.dt.testmanagerd.remote), so WDA / keyboard-mouse would fail.
        # Offer to restart the tunnel so RSD re-enumerates them. If no tunnel is
        # running, a later fresh launch already includes them — nothing to do.
        if tunnel.needs_tunnel(self._get_os_version()) and tunnel.is_tunnel_running():
            self._prompt_restart_tunnel(target)
            return
        self._start_ready_probe(target)

    def _prompt_restart_tunnel(self, target: str) -> None:
        """Ask the user to restart the tunnel (admin auth) after an iOS 17+ mount."""
        resp = QMessageBox.question(
            self,
            "重启 XPC tunnel",
            "DDI 挂载成功。\n\n"
            "iOS 17+ 上，挂载前已建立的 XPC tunnel 不包含本次挂载后才出现的开发者服务"
            "（如 testmanagerd），会导致键鼠 / WDA 无法启动。\n\n"
            "需要重启 XPC tunnel 以启用这些服务（将请求管理员授权）。是否现在重启？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if resp != QMessageBox.Yes:
            self._set_status(
                "已挂载；未重启 XPC tunnel——键鼠 / WDA 可能不可用，"
                "可稍后在上方 tunnel 面板点「重启」手动重启重试"
            )
            self._start_ready_probe(target)
            return
        self._set_status("正在重启 XPC tunnel（需管理员授权）…")
        self._set_tunnel_busy(True)
        self.runner.submit(
            lambda: tunnel.restart_tunneld(),
            on_done=lambda ok: self._on_tunnel_restarted(bool(ok), target),
            on_error=lambda e: self._on_tunnel_restarted(False, target),
        )

    def _on_tunnel_restarted(self, ok: bool, target: str) -> None:
        self._set_tunnel_busy(False)
        self._refresh_tunnel_panel()
        if ok:
            self._set_status("XPC tunnel 已重启，开发者服务已刷新；等待 DVT 就绪…")
        else:
            self._set_status(
                "XPC tunnel 重启失败 / 已取消；键鼠 / WDA 可能不可用，"
                "可稍后在上方 tunnel 面板点「重启」手动重试"
            )
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
            self.ddi_label.setText("DeveloperDiskImage：已挂载")
            self._refresh_features()
            self._set_status("DVT 已就绪，功能已解锁")
        else:
            # The image is mounted, but its developer services never came up in
            # time. Keep mounted state; surface the timeout and leave tiles off.
            self._dvt_ready = False
            self.ddi_label.setText("DeveloperDiskImage：已挂载（准备超时…）")
            self._refresh_features()
            self._set_status("DVT 准备超时：可点「刷新状态」重试或重新挂载")

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
        self._ready_probing = False
        self._ready_token += 1
        self.ddi_refresh_btn.setEnabled(True)
        self._dvt_ready = False
        self._refresh_features()
        self._set_status(f"正在卸载设备 {target} 的 DDI…")
        self._op_in_flight = True
        self._set_controls_enabled(False)
        self.runner.submit(
            lambda: api.ddi_unmount(target),
            on_done=self._on_unmounted,
            on_error=lambda e: self._after_mount(f"卸载失败: {e}"),
        )

    def _on_unmounted(self, result: dict) -> None:
        self._op_in_flight = False
        if not result.get("ok"):
            self._after_mount(result.get("error", {}).get("message", "卸载失败"))
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
        self.ddi_label.setText("DeveloperDiskImage：未挂载")
        self._set_status("DDI 已卸载")
        # On iOS 17+ with Xcode installed, macOS CoreDevice daemons auto-remount
        # the personalized DDI within seconds, so a later refresh may show it
        # mounted again — explain this once so it is not mistaken for a failure.
        if self._ios_major >= 17:
            QMessageBox.information(
                self, "DDI 已卸载",
                "DDI 已成功卸载。\n\n"
                "注意：iOS 17+ 上若 macOS 安装了 Xcode，其 CoreDevice 后台服务"
                "会在数秒内自动重新挂载开发者镜像，因此稍后点「刷新状态」可能再次"
                "显示为已挂载——这是系统行为，并非卸载失败。",
            )

    # -------------------------------------------------------------- tunnel

    def _set_tunnel_busy(self, busy: bool) -> None:
        """Disable all tunnel controls while a tunnel op is in flight."""
        for btn in (self.tunnel_btn, self.tunnel_stop_btn, self.tunnel_restart_btn):
            btn.setEnabled(not busy)

    def _on_start_tunnel(self) -> None:
        if tunnel.is_tunnel_running():
            self._set_status("XPC tunnel 已在运行")
            self._refresh_tunnel_panel()
            return
        self._set_status("正在启动 XPC tunnel（需管理员授权）…")
        self._set_tunnel_busy(True)
        self.runner.submit(
            tunnel.launch_tunneld,
            on_done=self._on_tunnel_started,
            on_error=lambda e: self._after_tunnel(f"启动失败: {e}"),
        )

    def _on_stop_tunnel(self) -> None:
        self._set_status("正在停止 XPC tunnel（需管理员授权）…")
        self._set_tunnel_busy(True)
        self.runner.submit(
            tunnel.stop_tunneld,
            on_done=lambda ok: self._after_tunnel(
                "XPC tunnel 已停止" if ok else "XPC tunnel 停止失败 / 已取消"
            ),
            on_error=lambda e: self._after_tunnel(f"停止失败: {e}"),
        )

    def _on_restart_tunnel(self) -> None:
        self._set_status("正在重启 XPC tunnel（需管理员授权，仅需一次密码）…")
        self._set_tunnel_busy(True)
        target = self._get_target()
        self.runner.submit(
            tunnel.restart_tunneld,
            on_done=lambda ok: self._on_tunnel_restarted(bool(ok), target),
            on_error=lambda e: self._on_tunnel_restarted(False, target),
        )

    def _on_tunnel_started(self, ok: bool) -> None:
        self._after_tunnel("XPC tunnel 已启动" if ok else "XPC tunnel 启动失败")
        # iOS 17+ DVT readiness needs the tunnel; if the DDI is already mounted
        # but not yet ready (e.g. mounted before the tunnel was up), re-probe now.
        if ok and self._mounted and not self._ready_probing:
            target = self._get_target()
            if target:
                self.ddi_label.setText("DeveloperDiskImage：已挂载（准备中…）")
                self._set_status("XPC tunnel 已启动，重新检测 DVT 就绪…")
                self._start_ready_probe(target)

    def _after_tunnel(self, message: str) -> None:
        self._set_tunnel_busy(False)
        self._refresh_tunnel_panel()
        self._refresh_features()
        self._set_status(message)

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

    def _open_syslog(self) -> None:
        target = self._get_target()
        if not target:
            self._set_status("未选择设备")
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
