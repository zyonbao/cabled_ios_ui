"""profiles_dialog.py — configuration-profile management dialog.

Opened from the "App 列表" tab (button "描述文件…"). Lists the configuration
profiles installed on the selected device and supports install (click or drag a
.mobileconfig) and multi-select removal. Profiles talk to the lockdown MCInstall
service directly and need neither WDA nor the XPC tunnel.

Installing a profile usually still requires the user to confirm it in the device
Settings app (system behaviour), so the UI surfaces that hint after delivery.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ios_toolkit import toolkit_api as api

from ..common.workers import AsyncRunner


class ProfilesDialog(QDialog):
    """Modal dialog: list / install / multi-remove configuration profiles."""

    def __init__(self, parent, runner: AsyncRunner, get_target: Callable[[], str]) -> None:
        super().__init__(parent)
        self.runner = runner
        self._get_target = get_target
        self._profiles: list[dict] = []
        self.setWindowTitle("描述文件管理")
        self.resize(680, 440)
        self.setAcceptDrops(True)
        self._build_ui()
        self._wire()
        self.reload()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.install_btn = QPushButton("安装 .mobileconfig…")
        self.remove_btn = QPushButton("移除选中")
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.install_btn)
        bar.addStretch(1)
        bar.addWidget(self.remove_btn)
        root.addLayout(bar)

        # Columns: name / identifier / type / organization.
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["名称", "标识符", "类型", "组织"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        self.status = QLabel("拖入 .mobileconfig 或点击“安装 .mobileconfig…”")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(self.reload)
        self.install_btn.clicked.connect(self._on_install_clicked)
        self.remove_btn.clicked.connect(self._on_remove_clicked)

    # ------------------------------------------------------------- loading

    def reload(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText("未选择设备")
            return
        self.status.setText("正在加载描述文件…")
        self.refresh_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.list_profiles(target),
            on_done=self._on_profiles,
            on_error=lambda e: self._fail(f"加载失败: {e}"),
        )

    def _on_profiles(self, result: dict) -> None:
        self.refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self._fail(result.get("error", {}).get("message", "加载失败"))
            return
        self._profiles = result["data"].get("profiles", [])
        self._render()
        self.status.setText(f"共 {len(self._profiles)} 个描述文件")

    def _fail(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.setText(message)

    def _render(self) -> None:
        self.table.setRowCount(len(self._profiles))
        for row, p in enumerate(self._profiles):
            self.table.setItem(row, 0, QTableWidgetItem(p.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(p.get("identifier", "")))
            self.table.setItem(row, 2, QTableWidgetItem(p.get("type", "")))
            self.table.setItem(row, 3, QTableWidgetItem(p.get("organization", "")))

    # --------------------------------------------------------------- install

    def _on_install_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择描述文件", "", "配置描述文件 (*.mobileconfig)"
        )
        if path:
            self._install(path)

    def _install(self, path: str) -> None:
        target = self._get_target()
        if not target:
            self.status.setText("未选择设备")
            return
        if not path.lower().endswith(".mobileconfig"):
            self.status.setText("仅支持 .mobileconfig 文件")
            return
        self.status.setText(f"正在下发 {os.path.basename(path)}…")
        self.install_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.install_profile(target, path),
            on_done=self._on_installed,
            on_error=lambda e: self._after_install(f"安装失败: {e}"),
        )

    def _on_installed(self, result: dict) -> None:
        if result.get("ok"):
            self._after_install("已下发，请在设备「设置」中确认安装")
            self.reload()
        else:
            msg = result.get("error", {}).get("message", "安装失败")
            self._after_install(f"安装失败: {msg}")

    def _after_install(self, message: str) -> None:
        self.install_btn.setEnabled(True)
        self.status.setText(message)

    # ---------------------------------------------------------------- remove

    def _selected_profiles(self) -> list[dict]:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        return [self._profiles[r] for r in rows if 0 <= r < len(self._profiles)]

    def _on_remove_clicked(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText("未选择设备")
            return
        profiles = self._selected_profiles()
        if not profiles:
            self.status.setText("请先选择要移除的描述文件")
            return
        reply = QMessageBox.question(
            self, "移除描述文件",
            f"确定移除选中的 {len(profiles)} 个描述文件？\n受监管 / MDM 描述文件可能拒绝移除。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        identifiers = [p.get("identifier", "") for p in profiles if p.get("identifier")]
        self.status.setText(f"正在移除 {len(identifiers)} 个…")
        self.remove_btn.setEnabled(False)

        def _do_remove() -> dict:
            ok, failed = 0, []
            for identifier in identifiers:
                res = api.remove_profile(target, identifier)
                if res.get("ok"):
                    ok += 1
                else:
                    failed.append(identifier)
            return {"ok": ok, "failed": failed}

        self.runner.submit(
            _do_remove,
            on_done=self._on_removed,
            on_error=lambda e: self._after_remove(f"移除失败: {e}"),
        )

    def _on_removed(self, result: dict) -> None:
        failed = result.get("failed", [])
        if failed:
            self._after_remove(f"已移除 {result['ok']} 个，{len(failed)} 个失败")
        else:
            self._after_remove(f"已移除 {result['ok']} 个")
        self.reload()

    def _after_remove(self, message: str) -> None:
        self.remove_btn.setEnabled(True)
        self.status.setText(message)

    # ----------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._first_profile(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        path = self._first_profile(event)
        if path is None:
            self.status.setText("仅支持拖入 .mobileconfig 文件")
            return
        event.acceptProposedAction()
        self._install(path)

    @staticmethod
    def _first_profile(event) -> str | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".mobileconfig"):
                return url.toLocalFile()
        return None
