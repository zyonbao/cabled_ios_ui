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
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from ..common import tunnel
from ..common.workers import AsyncRunner
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
        # While a mount/unmount RPC is in flight the device-side mounter is busy;
        # suppress concurrent ddi_status queries so they don't time out and get
        # mistaken for an operation failure.
        self._op_in_flight = False
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

        # Tunnel hint (shown only for iOS 17+ devices whose DVT features need it).
        tunnel_row = QHBoxLayout()
        self.tunnel_label = QLabel("iOS 17+ 的进程 / 定位能力依赖 XPC tunnel")
        self.tunnel_btn = QPushButton("启动 XPC tunnel")
        tunnel_row.addWidget(self.tunnel_label, 1)
        tunnel_row.addWidget(self.tunnel_btn)
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
        grid.setRowStretch(1, 1)
        root.addLayout(grid)

        self.status = QLabel("请选择一个设备")
        self.status.setWordWrap(True)
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
        self.process_tile.clicked.connect(self._open_process)
        self.location_tile.clicked.connect(self._open_location)

    # ------------------------------------------------------------- target

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        self._mounted = False
        # Invalidate any in-flight readiness probe from the previous device.
        self._ready_probing = False
        self._ready_token += 1
        self._ios_major = tunnel.ios_major(self._get_os_version())
        self.tunnel_widget.setVisible(tunnel.needs_tunnel(self._get_os_version()))
        self._set_features_enabled(False)
        if target:
            self.refresh_status()
        else:
            self.ddi_label.setText("DeveloperDiskImage：未知")
            self._set_controls_enabled(False)
            self.status.setText("未选择设备")

    def shutdown(self) -> None:
        """Release any background virtual-location session on app exit."""
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

    def _set_features_enabled(self, enabled: bool) -> None:
        for btn in self._feature_buttons:
            btn.setEnabled(enabled)

    def refresh_status(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText("未选择设备")
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
        self.status.setText("正在查询 DDI 状态…")
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
        self._set_features_enabled(self._mounted)
        if self._mounted:
            self.status.setText("DDI 已挂载，功能已解锁")
        else:
            self.status.setText("DDI 未挂载，请先挂载以解锁功能")

    def _fail(self, message: str) -> None:
        self._status_loading = False
        self.status.setText(message)

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
            self.status.setText(f"正在挂载 DDI 到设备 {target}…")
        else:  # auto: feed the source config from Settings
            kwargs = self._read_ddi_source_config()
            if not kwargs.get("sources"):
                self.status.setText(
                    "没有启用的 DDI 来源：请在 Settings → DDI Mount 启用本地或下载来源。"
                )
                return
            self.status.setText(
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
        self.mount_btn.setEnabled(False)
        self.unmount_btn.setEnabled(True)
        self._set_features_enabled(False)
        self.ddi_label.setText("DeveloperDiskImage：已挂载（准备中…）")
        self.status.setText(f"已成功挂载 DDI 到设备 {target}，等待 DVT 就绪…")
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
            self.status.setText(
                "已挂载；未重启 XPC tunnel——键鼠 / WDA 可能不可用，"
                "可稍后点「启动 XPC tunnel」手动重启重试"
            )
            self._start_ready_probe(target)
            return
        self.status.setText("正在重启 XPC tunnel（需管理员授权）…")
        self.tunnel_btn.setEnabled(False)
        self.runner.submit(
            lambda: tunnel.restart_tunneld(),
            on_done=lambda ok: self._on_tunnel_restarted(bool(ok), target),
            on_error=lambda e: self._on_tunnel_restarted(False, target),
        )

    def _on_tunnel_restarted(self, ok: bool, target: str) -> None:
        self.tunnel_btn.setEnabled(True)
        if ok:
            self.status.setText("XPC tunnel 已重启，开发者服务已刷新；等待 DVT 就绪…")
        else:
            self.status.setText(
                "XPC tunnel 重启失败 / 已取消；键鼠 / WDA 可能不可用，"
                "可稍后点「启动 XPC tunnel」手动重启重试"
            )
        self._start_ready_probe(target)

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
            self.ddi_label.setText("DeveloperDiskImage：已挂载")
            self._set_features_enabled(True)
            self.status.setText("DVT 已就绪，功能已解锁")
        else:
            # The image is mounted, but its developer services never came up in
            # time. Keep mounted state; surface the timeout and leave tiles off.
            self.ddi_label.setText("DeveloperDiskImage：已挂载（准备超时…）")
            self._set_features_enabled(False)
            self.status.setText("DVT 准备超时：可点「刷新状态」重试或重新挂载")

    def _after_mount(self, message: str) -> None:
        self._op_in_flight = False
        self._set_controls_enabled(True)
        self.status.setText(message)

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
        self._set_features_enabled(False)
        self.status.setText(f"正在卸载设备 {target} 的 DDI…")
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
        self._set_features_enabled(False)
        self.mount_btn.setEnabled(True)
        self.unmount_btn.setEnabled(False)
        self.ddi_label.setText("DeveloperDiskImage：未挂载")
        self.status.setText("DDI 已卸载")
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

    def _on_start_tunnel(self) -> None:
        if tunnel.is_tunnel_running():
            self.status.setText("XPC tunnel 已在运行")
            return
        self.status.setText("正在启动 XPC tunnel（需管理员授权）…")
        self.tunnel_btn.setEnabled(False)
        self.runner.submit(
            tunnel.launch_tunneld,
            on_done=self._on_tunnel_started,
            on_error=lambda e: self._after_tunnel(f"启动失败: {e}"),
        )

    def _on_tunnel_started(self, ok: bool) -> None:
        self._after_tunnel("XPC tunnel 已启动" if ok else "XPC tunnel 启动失败")
        # iOS 17+ DVT readiness needs the tunnel; if the DDI is already mounted
        # but not yet ready (e.g. mounted before the tunnel was up), re-probe now.
        if ok and self._mounted and not self._ready_probing:
            target = self._get_target()
            if target:
                self.ddi_label.setText("DeveloperDiskImage：已挂载（准备中…）")
                self.status.setText("XPC tunnel 已启动，重新检测 DVT 就绪…")
                self._start_ready_probe(target)

    def _after_tunnel(self, message: str) -> None:
        self.tunnel_btn.setEnabled(True)
        self.status.setText(message)

    # ------------------------------------------------------------ features

    def _open_process(self) -> None:
        target = self._get_target()
        if not target:
            return
        logger.info("open process manager: target=%s", target)
        ProcessDialog(self.runner, target, self).exec()

    def _open_location(self) -> None:
        target = self._get_target()
        if not target:
            return
        logger.info("open virtual location: target=%s", target)
        LocationDialog(self.runner, target, self).exec()
