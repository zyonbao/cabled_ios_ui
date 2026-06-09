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

from typing import Callable

from PySide6.QtCore import Qt
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

# Mount-method picker labels mapped to the platform-layer method keys.
_MOUNT_METHODS = [
    ("自动（按系统版本）", "auto"),
    ("个性化镜像（iOS 17+，联网下载）", "personalized"),
    ("开发者镜像（iOS < 17）", "developer"),
    ("手动选择本地镜像文件", "manual"),
]


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
        kwargs: dict[str, str] = {}
        if method == "manual":
            kwargs = self._collect_manual_files()
            if kwargs is None:
                return  # cancelled
        if method in ("auto", "personalized"):
            self.status.setText(
                "正在挂载 DDI…（自动 / 个性化会联网从 GitHub 下载镜像，首次可能较久）"
            )
        else:
            self.status.setText("正在挂载 DDI…")
        self._set_controls_enabled(False)
        self.runner.submit(
            lambda: api.ddi_mount(target, method, **kwargs),
            on_done=self._on_mounted,
            on_error=lambda e: self._after_mount(f"挂载失败: {e}"),
        )

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
        if not result.get("ok"):
            self._after_mount(result.get("error", {}).get("message", "挂载失败"))
            return
        self._after_mount("DDI 挂载成功")
        self.refresh_status()

    def _after_mount(self, message: str) -> None:
        self._set_controls_enabled(True)
        self.status.setText(message)

    # ------------------------------------------------------------- unmount

    def _on_unmount_clicked(self) -> None:
        target = self._get_target()
        if not target:
            return
        self.status.setText("正在卸载 DDI…")
        self._set_controls_enabled(False)
        self.runner.submit(
            lambda: api.ddi_unmount(target),
            on_done=self._on_unmounted,
            on_error=lambda e: self._after_mount(f"卸载失败: {e}"),
        )

    def _on_unmounted(self, result: dict) -> None:
        if not result.get("ok"):
            self._after_mount(result.get("error", {}).get("message", "卸载失败"))
            return
        self._after_mount("DDI 已卸载")
        # On iOS 17+ with Xcode installed, macOS CoreDevice daemons auto-remount
        # the personalized DDI within seconds, so a refresh may show it mounted
        # again — explain this once so it is not mistaken for an unmount failure.
        if self._ios_major >= 17:
            QMessageBox.information(
                self, "DDI 已卸载",
                "DDI 已成功卸载。\n\n"
                "注意：iOS 17+ 上若 macOS 安装了 Xcode，其 CoreDevice 后台服务"
                "会在数秒内自动重新挂载开发者镜像，因此点「刷新状态」可能再次"
                "显示为已挂载——这是系统行为，并非卸载失败。",
            )
        self.refresh_status()

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

    def _after_tunnel(self, message: str) -> None:
        self.tunnel_btn.setEnabled(True)
        self.status.setText(message)

    # ------------------------------------------------------------ features

    def _open_process(self) -> None:
        target = self._get_target()
        if not target:
            return
        ProcessDialog(self.runner, target, self).exec()

    def _open_location(self) -> None:
        target = self._get_target()
        if not target:
            return
        LocationDialog(self.runner, target, self).exec()
