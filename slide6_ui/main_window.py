"""main_window.py — the slide6_ui main window and device lifecycle.

Owns the shared top bar (device picker / refresh / status), the sidebar tab
container, and the Settings menu. Device-tab content lives in dedicated tab
classes; the live mirror, gestures, keyboard, and device actions live in
KeymouseTab, which MainWindow drives through a small delegation surface
(select_device / on_enter / on_leave / set_overlay / shutdown).
"""

from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import logsys
from ios_toolkit import toolkit_api as api

from .album import DcimAlbumTab
from .app_manager import AppManagerTab
from .common import tunnel
from .common.file_dialogs import open_directory
from .common.focus import suppress_auto_focus
from .common.sidebar_tabs import SidebarTabs
from .common.workers import AsyncRunner
from .crash import CrashReportsTab
from .developer_tools import DeveloperToolsTab
from .device_info import DeviceInfoTab
from .file_system import FileSystemTab
from .keymouse import KeymouseTab
from .profiles import ProfilesTab
from .syslog import SyslogTab

_SETTINGS_ORG = "ios_ui_ta_proxy"
# Kept as the legacy package name on purpose: this is the QSettings storage key.
# Renaming it would orphan users' existing saved preferences.
_SETTINGS_APP = "slide6_console"
_ASK_CLEAN_TUNNEL_ON_EXIT_KEY = "settings/ask_clean_tunnel_on_exit"
_LOGGING_ENABLED_KEY = "settings/logging_enabled"
_LOGGING_DIR_KEY = "settings/logging_dir"

# DeveloperDiskImage (DDI) mount source settings. These are the persisted
# config surface; the actual mount-time consumption lives in the
# add-local-ddi-mount change. Defaults are computed lazily for display only.
_DDI_LOCAL_ENABLED_KEY = "settings/ddi_local_enabled"
_DDI_LEGACY_DIR_KEY = "settings/ddi_legacy_dir"
_DDI_MODERN_DIR_KEY = "settings/ddi_modern_dir"
_DDI_GITHUB_ENABLED_KEY = "settings/ddi_github_enabled"
_DDI_GITHUB_TOKEN_KEY = "settings/ddi_github_token"
_DDI_GITHUB_SAVE_DIR_KEY = "settings/ddi_github_save_dir"
_DDI_SOURCE_PRIORITY_KEY = "settings/ddi_source_priority"

# Image source identifiers used by the priority ordering.
_DDI_SOURCE_LOCAL = "local"
_DDI_SOURCE_GITHUB = "github"
_DDI_SOURCE_LABELS = {
    _DDI_SOURCE_LOCAL: "System Developer Image (本地)",
    _DDI_SOURCE_GITHUB: "GitHub Download Image",
}
_DDI_DEFAULT_PRIORITY = f"{_DDI_SOURCE_LOCAL},{_DDI_SOURCE_GITHUB}"

# Standard locations used as placeholder defaults when the user leaves a field
# blank. The legacy directory follows the active Xcode toolchain.
_DDI_MODERN_DEFAULT_DIR = "/Library/Developer/CoreDevice/CandidateDDIs"
_DDI_GITHUB_SAVE_DEFAULT_DIR = os.path.expanduser("~/Library/CablediOS/DDI")
_DDI_DORONZ88_REPO = "https://github.com/doronz88/DeveloperDiskImage"


def _xcode_developer_dir() -> str:
    """Resolve the active Xcode developer dir via xcode-select, with fallback."""
    xcode_select = shutil.which("xcode-select")
    if xcode_select:
        try:
            out = subprocess.run(
                [xcode_select, "-p"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            path = (out.stdout or "").strip()
            if out.returncode == 0 and path:
                return path
        except (OSError, subprocess.SubprocessError):
            pass
    return "/Applications/Xcode.app/Contents/Developer"


def _ddi_legacy_default_dir() -> str:
    """Standard Xcode DeviceSupport folder holding per-version (iOS<17) images."""
    return os.path.join(
        _xcode_developer_dir(),
        "Platforms/iPhoneOS.platform/DeviceSupport",
    )


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
        # 描述文件 / 键鼠操作 / Crash 报告 / 系统日志 / 开发者工具 — info-first,
        # with diagnostics and the advanced DDI/DVT developer tooling last;
        # profile management sits with the other non-WDA device-management tabs.
        self.tabs = SidebarTabs()
        self.device_info_tab = DeviceInfoTab(self.runner, lambda: self.target)
        self.tabs.addTab(self.device_info_tab, "设备信息")
        self.album_tab = DcimAlbumTab(self.runner)
        self.tabs.addTab(self.album_tab, "相册")
        self.fs_tab = FileSystemTab(self.runner)
        self.tabs.addTab(self.fs_tab, "文件系统")
        self.app_tab = AppManagerTab(self.runner, lambda: self.target)
        self.tabs.addTab(self.app_tab, "App 列表")
        self.profiles_tab = ProfilesTab(self.runner, lambda: self.target)
        self.tabs.addTab(self.profiles_tab, "描述文件")
        self.keymouse_tab = KeymouseTab(self.runner, self._set_status, self.on_select_device)
        self.tabs.addTab(self.keymouse_tab, "键鼠操作")
        self.crash_tab = CrashReportsTab(self.runner, lambda: self.target)
        self.tabs.addTab(self.crash_tab, "Crash 报告")
        self.syslog_tab = SyslogTab(self.runner, lambda: self.target)
        self.tabs.addTab(self.syslog_tab, "系统日志")
        self.developer_tools_tab = DeveloperToolsTab(
            self.runner, lambda: self.target, self._current_os_version
        )
        self.tabs.addTab(self.developer_tools_tab, "开发者工具")
        root.addWidget(self.tabs, stretch=1)

        # Don't let filter / path / search fields steal focus when a tab is
        # shown. The key/mouse tab is exempt: its keyboard-capture field is
        # meant to auto-focus when the on-screen keyboard is opened.
        for tab in (
            self.device_info_tab, self.album_tab, self.fs_tab, self.app_tab,
            self.profiles_tab, self.crash_tab, self.syslog_tab,
            self.developer_tools_tab,
        ):
            suppress_auto_focus(tab)

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

    # ---------------------------------------------------------- logging prefs

    def _logging_enabled(self) -> bool:
        return bool(self.settings.value(_LOGGING_ENABLED_KEY, True, type=bool))

    def _logging_dir(self) -> str:
        return self.settings.value(_LOGGING_DIR_KEY, "", type=str) or ""

    def _apply_logging(self) -> None:
        """Re-initialize logging from the current saved preferences (live)."""
        logsys.setup_logging(
            enabled=self._logging_enabled(),
            log_dir=self._logging_dir() or None,
        )

    # ------------------------------------------------------ DDI mount prefs

    def _ddi_local_enabled(self) -> bool:
        return bool(self.settings.value(_DDI_LOCAL_ENABLED_KEY, True, type=bool))

    def _ddi_github_enabled(self) -> bool:
        return bool(self.settings.value(_DDI_GITHUB_ENABLED_KEY, True, type=bool))

    def _ddi_source_priority(self) -> list[str]:
        """Return the ordered source list, sanitized against known sources."""
        raw = self.settings.value(_DDI_SOURCE_PRIORITY_KEY, _DDI_DEFAULT_PRIORITY, type=str)
        order = [s.strip() for s in (raw or "").split(",") if s.strip()]
        # Keep only known sources, then append any missing ones in default order.
        known = [s for s in order if s in _DDI_SOURCE_LABELS]
        for src in (_DDI_SOURCE_LOCAL, _DDI_SOURCE_GITHUB):
            if src not in known:
                known.append(src)
        return known

    def _open_preferences(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        layout = QVBoxLayout(dlg)

        tabs = QTabWidget(dlg)
        tabs.addTab(self._build_general_tab(dlg), "General")
        tabs.addTab(self._build_logging_tab(dlg), "Logging")
        tabs.addTab(self._build_ddi_tab(dlg), "DeveloperDiskImage")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, dlg)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)

        suppress_auto_focus(dlg)
        dlg.resize(560, 460)
        dlg.exec()

    def _build_general_tab(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        col = QVBoxLayout(page)

        ask_clean_checkbox = QCheckBox("Ask to clean XPC tunnel on exit", page)
        ask_clean_checkbox.setChecked(self._ask_clean_tunnel_on_exit())
        ask_clean_checkbox.toggled.connect(self._set_ask_clean_tunnel_on_exit)
        col.addWidget(ask_clean_checkbox)

        col.addStretch(1)
        return page

    def _build_logging_tab(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        col = QVBoxLayout(page)

        log_enabled_checkbox = QCheckBox("启用文件日志", page)
        log_enabled_checkbox.setChecked(self._logging_enabled())
        col.addWidget(log_enabled_checkbox)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("目录"))
        log_dir_edit = QLineEdit(page)
        log_dir_edit.setPlaceholderText(f"默认:{logsys.DEFAULT_LOG_DIR}")
        log_dir_edit.setText(self._logging_dir())
        browse_btn = QPushButton("浏览…", page)
        dir_row.addWidget(log_dir_edit, 1)
        dir_row.addWidget(browse_btn)
        col.addLayout(dir_row)

        def _save_logging() -> None:
            self.settings.setValue(_LOGGING_ENABLED_KEY, log_enabled_checkbox.isChecked())
            self.settings.setValue(_LOGGING_DIR_KEY, log_dir_edit.text().strip())
            self._apply_logging()

        def _browse_dir() -> None:
            start = log_dir_edit.text().strip() or logsys.DEFAULT_LOG_DIR
            chosen = open_directory(page, "选择日志目录", start)
            if chosen:
                log_dir_edit.setText(chosen)
                _save_logging()

        log_enabled_checkbox.toggled.connect(lambda _=False: _save_logging())
        log_dir_edit.editingFinished.connect(_save_logging)
        browse_btn.clicked.connect(_browse_dir)

        col.addStretch(1)
        return page

    def _ddi_dir_row(
        self,
        parent: QWidget,
        label: str,
        key: str,
        default_dir: str,
    ) -> tuple[QHBoxLayout, list[QWidget]]:
        """Build a labeled directory row (edit + browse) bound to a settings key."""
        row = QHBoxLayout()
        lbl = QLabel(label, parent)
        edit = QLineEdit(parent)
        edit.setPlaceholderText(f"默认:{default_dir}")
        edit.setText(self.settings.value(key, "", type=str) or "")
        # Pin to natural height so sibling layout pressure can't clip the text.
        edit.setMinimumHeight(edit.sizeHint().height())
        browse = QPushButton("浏览…", parent)
        row.addWidget(lbl)
        row.addWidget(edit, 1)
        row.addWidget(browse)

        def _save() -> None:
            self.settings.setValue(key, edit.text().strip())

        def _browse() -> None:
            start = edit.text().strip() or default_dir
            chosen = open_directory(parent, label, start)
            if chosen:
                edit.setText(chosen)
                _save()

        edit.editingFinished.connect(_save)
        browse.clicked.connect(_browse)
        return row, [lbl, edit, browse]

    def _build_ddi_tab(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        col = QVBoxLayout(page)

        # --- Section: System Developer Image (local) ---------------------
        local_box = QGroupBox("System Developer Image", page)
        local_col = QVBoxLayout(local_box)
        local_enabled = QCheckBox("启用本地镜像来源", local_box)
        local_enabled.setChecked(self._ddi_local_enabled())
        local_col.addWidget(local_enabled)

        legacy_row, legacy_widgets = self._ddi_dir_row(
            local_box,
            "Legacy (iOS<17) 目录",
            _DDI_LEGACY_DIR_KEY,
            _ddi_legacy_default_dir(),
        )
        modern_row, modern_widgets = self._ddi_dir_row(
            local_box,
            "Modern (iOS17+) 目录",
            _DDI_MODERN_DIR_KEY,
            _DDI_MODERN_DEFAULT_DIR,
        )
        local_col.addLayout(legacy_row)
        local_col.addLayout(modern_row)
        col.addWidget(local_box)

        # --- Section: GitHub Download Image ------------------------------
        github_box = QGroupBox("GitHub Download Image", page)
        github_col = QVBoxLayout(github_box)
        github_enabled = QCheckBox("启用 GitHub 下载来源", github_box)
        github_enabled.setChecked(self._ddi_github_enabled())
        github_col.addWidget(github_enabled)

        token_row = QHBoxLayout()
        token_lbl = QLabel("GitHub Token", github_box)
        token_edit = QLineEdit(github_box)
        token_edit.setEchoMode(QLineEdit.Password)
        token_edit.setPlaceholderText("可选")
        token_edit.setText(self.settings.value(_DDI_GITHUB_TOKEN_KEY, "", type=str) or "")
        token_row.addWidget(token_lbl)
        token_row.addWidget(token_edit, 1)
        github_col.addLayout(token_row)

        token_hint = QLabel(
            f"默认从 {_DDI_DORONZ88_REPO} 的 raw CDN 直下（不受限额、无需 token）；"
            "token 仅在回退到 GitHub API 下载时生效（无 token 60 次/小时，"
            "配置后 5000 次/小时）。",
            github_box,
        )
        token_hint.setWordWrap(True)
        token_hint.setStyleSheet("color: gray; font-size: 11px;")
        github_col.addWidget(token_hint)

        save_row, save_widgets = self._ddi_dir_row(
            github_box,
            "镜像保存目录",
            _DDI_GITHUB_SAVE_DIR_KEY,
            _DDI_GITHUB_SAVE_DEFAULT_DIR,
        )
        github_col.addLayout(save_row)
        col.addWidget(github_box)

        # --- Section: source priority ------------------------------------
        priority_box = QGroupBox("来源优先级", page)
        priority_col = QVBoxLayout(priority_box)
        priority_hint = QLabel("挂载时按从上到下的顺序尝试可用来源。", priority_box)
        priority_hint.setStyleSheet("color: gray; font-size: 11px;")
        priority_col.addWidget(priority_hint)

        prio_row = QHBoxLayout()
        prio_list = QListWidget(priority_box)
        for src in self._ddi_source_priority():
            item = QListWidgetItem(_DDI_SOURCE_LABELS[src])
            item.setData(Qt.ItemDataRole.UserRole, src)
            prio_list.addItem(item)
        prio_list.setCurrentRow(0)
        # Only ever a couple of rows: pin to content height so the list does not
        # greedily expand and squeeze the other sections' inputs.
        _row_h = prio_list.sizeHintForRow(0)
        prio_list.setFixedHeight(_row_h * prio_list.count() + 2 * prio_list.frameWidth())
        prio_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        prio_row.addWidget(prio_list, 1)

        prio_btns = QVBoxLayout()
        up_btn = QPushButton("上移", priority_box)
        down_btn = QPushButton("下移", priority_box)
        prio_btns.addWidget(up_btn)
        prio_btns.addWidget(down_btn)
        prio_btns.addStretch(1)
        prio_row.addLayout(prio_btns)
        priority_col.addLayout(prio_row)
        col.addWidget(priority_box)

        # --- persistence + enable/disable linkage ------------------------
        def _save_priority() -> None:
            order = [
                prio_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(prio_list.count())
            ]
            self.settings.setValue(_DDI_SOURCE_PRIORITY_KEY, ",".join(order))

        def _move(delta: int) -> None:
            row = prio_list.currentRow()
            target = row + delta
            if row < 0 or target < 0 or target >= prio_list.count():
                return
            item = prio_list.takeItem(row)
            prio_list.insertItem(target, item)
            prio_list.setCurrentRow(target)
            _save_priority()

        def _refresh_priority_enabled() -> None:
            local_on = local_enabled.isChecked()
            github_on = github_enabled.isChecked()
            # Disable each source's item when its section is off.
            for i in range(prio_list.count()):
                it = prio_list.item(i)
                src = it.data(Qt.ItemDataRole.UserRole)
                on = local_on if src == _DDI_SOURCE_LOCAL else github_on
                flags = it.flags()
                if on:
                    it.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
                else:
                    it.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
            # If both sources disabled, disable the whole priority section.
            both_off = not local_on and not github_on
            priority_box.setEnabled(not both_off)
            if both_off:
                priority_hint.setText("至少启用一个来源后才能配置优先级。")
            else:
                priority_hint.setText("挂载时按从上到下的顺序尝试可用来源。")

        def _set_local_enabled(on: bool) -> None:
            self.settings.setValue(_DDI_LOCAL_ENABLED_KEY, on)
            for w in legacy_widgets + modern_widgets:
                w.setEnabled(on)
            _refresh_priority_enabled()

        def _set_github_enabled(on: bool) -> None:
            self.settings.setValue(_DDI_GITHUB_ENABLED_KEY, on)
            for w in [token_lbl, token_edit, token_hint] + save_widgets:
                w.setEnabled(on)
            _refresh_priority_enabled()

        def _save_token() -> None:
            # Token is a credential: persist locally only, never log it.
            self.settings.setValue(_DDI_GITHUB_TOKEN_KEY, token_edit.text())

        up_btn.clicked.connect(lambda: _move(-1))
        down_btn.clicked.connect(lambda: _move(1))
        local_enabled.toggled.connect(_set_local_enabled)
        github_enabled.toggled.connect(_set_github_enabled)
        token_edit.editingFinished.connect(_save_token)

        # Apply initial enable state.
        _set_local_enabled(local_enabled.isChecked())
        _set_github_enabled(github_enabled.isChecked())

        col.addStretch(1)
        return page

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
        self.profiles_tab.set_target(self.target)
        self.crash_tab.set_target(self.target)
        self.syslog_tab.set_target(self.target)
        self.developer_tools_tab.set_target(self.target)
        # The key/mouse tab owns the costly WDA/mirror flow; only start it when
        # that tab is the current one (otherwise it is deferred until entered).
        self.keymouse_tab.select_device(self.target, dev, active=self._on_keymouse_tab())

    def _current_os_version(self) -> str:
        """Return the os_version of the selected device (or '' if none)."""
        dev = self.devices.get(self.target) if self.target else None
        return (dev or {}).get("metadata", {}).get("os_version", "")

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
        # Stop the live log-stream thread (and its toolkit stream) on exit.
        self.syslog_tab.shutdown()
        # Release any background virtual-location session (iOS 17+) on exit.
        self.developer_tools_tab.shutdown()

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
