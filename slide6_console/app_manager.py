"""app_manager.py — the "App 列表" tab.

AppManagerTab lists / searches / filters installed apps and supports install
(click or drag .ipa) / uninstall, plus per-row entry points into the file
browser (see afc_browser.AfcBrowserDialog) for file-sharing or sandbox-capable
apps.

All blocking executor_ios calls go through the shared AsyncRunner so the Qt GUI
thread never blocks. App management talks to lockdown services directly and
needs neither WDA nor the XPC tunnel.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from executor_ios import toolkit_api as api

from .afc_browser import AfcBrowserDialog
from .workers import AsyncRunner


class AppManagerTab(QWidget):
    """The "App 列表" tab: app inventory with install / uninstall / browse."""

    def __init__(self, runner: AsyncRunner, get_target: Callable[[], str]) -> None:
        super().__init__()
        self.runner = runner
        self._get_target = get_target
        self._apps: list[dict] = []
        self.setAcceptDrops(True)
        self._build_ui()
        self._wire()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Toolbar: search + filters + actions.
        bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索 App（名称 / bundleId）")
        self.share_filter = QCheckBox("文件已共享")
        self.sandbox_filter = QCheckBox("沙盒可访问")
        self.refresh_btn = QPushButton("刷新列表")
        self.install_btn = QPushButton("安装 IPA…")
        bar.addWidget(self.search_input, 1)
        bar.addWidget(self.share_filter)
        bar.addWidget(self.sandbox_filter)
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.install_btn)
        root.addLayout(bar)

        # App table: name / bundle id / capability-driven action buttons.
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["名称", "Bundle ID", "操作"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        self.status = QLabel("拖拽 .ipa 到此处或点击“安装 IPA…”")
        root.addWidget(self.status)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(self.reload_apps)
        self.install_btn.clicked.connect(self.on_install_clicked)
        self.search_input.textChanged.connect(self._render)
        self.share_filter.toggled.connect(self._render)
        self.sandbox_filter.toggled.connect(self._render)

    # ------------------------------------------------------------- loading

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        self._apps = []
        self._render()
        if target:
            self.reload_apps()
        else:
            self.status.setText("未选择设备")

    def reload_apps(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText("未选择设备")
            return
        self.status.setText("正在加载 App 列表…")
        self.refresh_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.list_apps(target),
            on_done=self._on_apps,
            on_error=lambda e: self._fail(f"加载失败: {e}"),
        )

    def _on_apps(self, result: dict) -> None:
        self.refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self._fail(result.get("error", {}).get("message", "加载失败"))
            return
        self._apps = result["data"].get("apps", [])
        self._render()
        self.status.setText(f"共 {len(self._apps)} 个 App")

    def _fail(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.setText(message)

    # ----------------------------------------------------------- rendering

    def _filtered(self) -> list[dict]:
        kw = self.search_input.text().strip().lower()
        only_share = self.share_filter.isChecked()
        only_sandbox = self.sandbox_filter.isChecked()
        out = []
        for app in self._apps:
            if only_share and not app.get("fileSharing"):
                continue
            if only_sandbox and not app.get("sandboxAccessible"):
                continue
            if kw and kw not in app.get("name", "").lower() and kw not in app.get("bundleId", "").lower():
                continue
            out.append(app)
        return out

    def _render(self) -> None:
        apps = self._filtered()
        self.table.setRowCount(len(apps))
        for row, app in enumerate(apps):
            self.table.setItem(row, 0, QTableWidgetItem(app.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(app.get("bundleId", "")))
            self.table.setCellWidget(row, 2, self._action_cell(app))

    def _action_cell(self, app: dict) -> QWidget:
        """Build the per-row action column: Documents / Sandbox / 卸载,
        shown only when the app advertises the matching capability."""
        cell = QWidget()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(6)
        if app.get("fileSharing"):
            docs = QPushButton("Documents")
            docs.clicked.connect(lambda _=False, a=app: self._open_browser(a, "documents"))
            lay.addWidget(docs)
        if app.get("sandboxAccessible"):
            sandbox = QPushButton("Sandbox")
            sandbox.clicked.connect(lambda _=False, a=app: self._open_browser(a, "container"))
            lay.addWidget(sandbox)
        uninstall = QPushButton("卸载")
        uninstall.clicked.connect(lambda _=False, a=app: self.on_uninstall(a))
        lay.addWidget(uninstall)
        lay.addStretch(1)
        return cell

    # -------------------------------------------------------- install/uninstall

    def on_install_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 IPA", "", "iOS App (*.ipa)")
        if path:
            self._install(path)

    def _install(self, ipa_path: str) -> None:
        target = self._get_target()
        if not target:
            self.status.setText("未选择设备")
            return
        if not ipa_path.lower().endswith(".ipa"):
            self.status.setText("仅支持 .ipa 文件")
            return
        self.status.setText(f"正在安装 {os.path.basename(ipa_path)}…")
        self.install_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.install_app(target, ipa_path),
            on_done=self._on_installed,
            on_error=lambda e: self._after_install(f"安装失败: {e}"),
        )

    def _on_installed(self, result: dict) -> None:
        if result.get("ok"):
            self._after_install("安装成功")
            self.reload_apps()
        else:
            msg = result.get("error", {}).get("message", "安装失败")
            self._after_install(f"安装失败（需本设备可信任证书签名）: {msg}")

    def _after_install(self, message: str) -> None:
        self.install_btn.setEnabled(True)
        self.status.setText(message)

    def on_uninstall(self, app: dict) -> None:
        target = self._get_target()
        if not app or not target:
            return
        bundle_id = app.get("bundleId", "")
        reply = QMessageBox.question(
            self, "卸载 App",
            f"确定卸载 {app.get('name', bundle_id)}（{bundle_id}）？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.status.setText(f"正在卸载 {bundle_id}…")
        self.runner.submit(
            lambda: api.uninstall_app(target, bundle_id),
            on_done=lambda r: (self.status.setText("卸载成功"), self.reload_apps())
            if r.get("ok") else self.status.setText(
                "卸载失败: " + r.get("error", {}).get("message", "")),
            on_error=lambda e: self.status.setText(f"卸载失败: {e}"),
        )

    # -------------------------------------------------------------- browse

    def _open_browser(self, app: dict, root: str) -> None:
        target = self._get_target()
        if not app or not target:
            return
        dlg = AfcBrowserDialog(
            self, self.runner, target,
            bundle_id=app.get("bundleId", ""), root=root,
            app_name=app.get("name", ""),
        )
        dlg.exec()

    # ----------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._first_ipa(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        path = self._first_ipa(event)
        if path is None:
            self.status.setText("仅支持拖入 .ipa 文件")
            return
        event.acceptProposedAction()
        self._install(path)

    @staticmethod
    def _first_ipa(event) -> str | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".ipa"):
                return url.toLocalFile()
        return None
