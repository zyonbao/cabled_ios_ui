"""main_window.py — the slide6_ui main window and device lifecycle.

Owns the shared top bar (device picker / refresh / status), the sidebar tab
container, and the Settings menu. Device-tab content lives in dedicated tab
classes; the live mirror, gestures, keyboard, and device actions live in
KeymouseTab, which MainWindow drives through a small delegation surface
(select_device / on_enter / on_leave / set_overlay / shutdown).
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .album import DcimAlbumTab
from .app_manager import AppManagerTab
from .common import tunnel
from .common.sidebar_tabs import SidebarTabs
from .common.workers import AsyncRunner
from .device_info import DeviceInfoTab
from .file_system import FileSystemTab
from .keymouse import KeymouseTab

_SETTINGS_ORG = "ios_ui_ta_proxy"
# Kept as the legacy package name on purpose: this is the QSettings storage key.
# Renaming it would orphan users' existing saved preferences.
_SETTINGS_APP = "slide6_console"
_ASK_CLEAN_TUNNEL_ON_EXIT_KEY = "settings/ask_clean_tunnel_on_exit"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CablediOS")
        self.resize(1100, 820)

        self.settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self.runner = AsyncRunner()
        self.devices: dict = {}
        self.target = ""

        self._build_ui()
        self._build_menu()
        self._wire()
        self.load_devices()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        # Top bar: device picker / refresh / status. The top bar is shared across
        # tabs; detailed device info now lives in the "设备信息" tab and the fps
        # control lives in the key/mouse tab.
        top = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(320)
        self.refresh_btn = QPushButton("刷新")
        self.status_label = QLabel("未连接")
        top.addWidget(QLabel("设备"))
        top.addWidget(self.device_combo)
        top.addWidget(self.refresh_btn)
        top.addStretch(1)
        top.addWidget(self.status_label)
        root.addLayout(top)

        # Tabbed body. Tabs run down the left side (vertical column, horizontal
        # labels) via SidebarTabs. Order: 设备信息 / 相册 / 文件系统 / App 列表 /
        # 键鼠操作 — info-first, with the WDA/tunnel-heavy key/mouse tab last.
        self.tabs = SidebarTabs()
        self.device_info_tab = DeviceInfoTab(self.runner, lambda: self.target)
        self.tabs.addTab(self.device_info_tab, "设备信息")
        self.album_tab = DcimAlbumTab(self.runner)
        self.tabs.addTab(self.album_tab, "相册")
        self.fs_tab = FileSystemTab(self.runner)
        self.tabs.addTab(self.fs_tab, "文件系统")
        self.app_tab = AppManagerTab(self.runner, lambda: self.target)
        self.tabs.addTab(self.app_tab, "App 列表")
        self.keymouse_tab = KeymouseTab(self.runner, self._set_status, self.on_select_device)
        self.tabs.addTab(self.keymouse_tab, "键鼠操作")
        root.addWidget(self.tabs, stretch=1)

        self.setCentralWidget(central)

    def _build_menu(self) -> None:
        settings_menu = self.menuBar().addMenu("Settings")
        self.preferences_action = QAction("Preferences...", self)
        settings_menu.addAction(self.preferences_action)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(self.load_devices)
        self.device_combo.activated.connect(self.on_select_device)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.preferences_action.triggered.connect(self._open_preferences)

    # -------------------------------------------------------------- status

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _ask_clean_tunnel_on_exit(self) -> bool:
        value = self.settings.value(_ASK_CLEAN_TUNNEL_ON_EXIT_KEY, True, type=bool)
        return bool(value)

    def _set_ask_clean_tunnel_on_exit(self, enabled: bool) -> None:
        self.settings.setValue(_ASK_CLEAN_TUNNEL_ON_EXIT_KEY, enabled)

    def _open_preferences(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Preferences")
        layout = QVBoxLayout(dlg)

        general_box = QWidget(dlg)
        general = QVBoxLayout(general_box)
        general.setContentsMargins(0, 0, 0, 0)
        general.addWidget(QLabel("General"))

        ask_clean_checkbox = QCheckBox("Ask to clean XPC tunnel on exit", general_box)
        ask_clean_checkbox.setChecked(self._ask_clean_tunnel_on_exit())
        ask_clean_checkbox.toggled.connect(self._set_ask_clean_tunnel_on_exit)
        general.addWidget(ask_clean_checkbox)
        layout.addWidget(general_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, dlg)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)

        dlg.resize(360, 140)
        dlg.exec()

    # --------------------------------------------------------- device list

    def load_devices(self) -> None:
        self._set_status("正在扫描设备…")
        self.runner.submit(api.list_targets, on_done=self._on_devices,
                           on_error=lambda e: self._set_status(f"设备列表加载失败: {e}"))

    def _on_devices(self, result: dict) -> None:
        if not result.get("ok"):
            self._set_status("设备列表加载失败")
            return
        targets = result["data"].get("targets", [])
        prev = self.target
        self.devices = {}
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("— 选择设备 —", "")
        for t in targets:
            self.devices[t["id"]] = t
            wda = "" if t.get("state") == "online" else "（未装 WDA）"
            model = (t.get("metadata") or {}).get("model", "")
            label = f"{t.get('name') or t['id']}  {model} {wda}".strip()
            self.device_combo.addItem(label, t["id"])
        if prev and prev in self.devices:
            idx = self.device_combo.findData(prev)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
        self.device_combo.blockSignals(False)
        self._set_status(f"发现 {len(targets)} 台设备")
        if not targets:
            self.keymouse_tab.set_overlay("未检测到 USB 设备\n请连接并信任后点击刷新")

    # ---------------------------------------------------- device selection

    def on_select_device(self) -> None:
        target = self.device_combo.currentData() or ""
        self.target = target
        dev = self.devices.get(target) if target else None
        # App management / device info work without WDA/tunnel, so refresh those
        # tabs for any selected device (they clear when no device is selected).
        self.app_tab.set_target(self.target)
        self.device_info_tab.set_target(self.target)
        self.fs_tab.set_target(self.target)
        self.album_tab.set_target(self.target)
        # The key/mouse tab owns the costly WDA/mirror flow; only start it when
        # that tab is the current one (otherwise it is deferred until entered).
        self.keymouse_tab.select_device(self.target, dev, active=self._on_keymouse_tab())

    def _on_keymouse_tab(self) -> bool:
        return self.tabs.currentWidget() is self.keymouse_tab

    def _on_tab_changed(self, _index: int) -> None:
        if self._on_keymouse_tab():
            self.keymouse_tab.on_enter()
        else:
            self.keymouse_tab.on_leave()

    # ------------------------------------------------------------- closing

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.keymouse_tab.shutdown()

        if self._ask_clean_tunnel_on_exit() and tunnel.is_tunnel_running():
            reply = QMessageBox.question(
                self,
                "停止 XPC tunnel",
                "检测到 XPC tunnel 仍在运行。\n是否停止它？（停止需要管理员授权）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                tunnel.stop_tunneld()
        event.accept()
