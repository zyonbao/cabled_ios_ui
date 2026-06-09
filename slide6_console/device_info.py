"""device_info.py — the "设备信息" tab.

Shows the full lockdown property set for the selected device as a key/value
table (DeviceName, ProductType, ProductVersion, SerialNumber, hardware/region
fields, ...). Reads over lockdown/usbmux through the shared AsyncRunner; needs
neither WDA nor the XPC tunnel.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from executor_ios import toolkit_api as api

from .workers import AsyncRunner

# Surface the most-asked-for identifiers first; everything else follows sorted.
_PRIORITY_KEYS = [
    "DeviceName",
    "DeviceClass",
    "ProductName",
    "ProductType",
    "ModelNumber",
    "HardwareModel",
    "ProductVersion",
    "BuildVersion",
    "SerialNumber",
    "UniqueDeviceID",
    "UniqueChipID",
    "CPUArchitecture",
    "RegionInfo",
    "TimeZone",
    "WiFiAddress",
    "BluetoothAddress",
    "PhoneNumber",
    "ActivationState",
]


class DeviceInfoTab(QWidget):
    """The "设备信息" tab: a key/value dump of lockdown device properties."""

    def __init__(self, runner: AsyncRunner, get_target: Callable[[], str]) -> None:
        super().__init__()
        self.runner = runner
        self._get_target = get_target
        self._info: dict[str, object] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("筛选字段 / 值")
        self.refresh_btn = QPushButton("刷新")
        bar.addWidget(self.search_input, 1)
        bar.addWidget(self.refresh_btn)
        root.addLayout(bar)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["字段", "值"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setTextElideMode(Qt.ElideNone)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        self.status = QLabel("选择设备后展示设备信息")
        root.addWidget(self.status)

        self.refresh_btn.clicked.connect(self.reload_info)
        self.search_input.textChanged.connect(self._render)
        # Double-click a cell copies it; right-click offers key/value copy.
        self.table.itemDoubleClicked.connect(self._copy_cell)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

    # ------------------------------------------------------------- loading

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        self._info = {}
        self._render()
        if target:
            self.reload_info()
        else:
            self.status.setText("未选择设备")

    def reload_info(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText("未选择设备")
            return
        self.status.setText("正在读取设备信息…")
        self.refresh_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.device_info(target),
            on_done=self._on_info,
            on_error=lambda e: self._fail(f"读取失败: {e}"),
        )

    def _on_info(self, result: dict) -> None:
        self.refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self._fail(result.get("error", {}).get("message", "读取失败"))
            return
        self._info = result["data"].get("info", {})
        self._render()
        self.status.setText(f"共 {len(self._info)} 项")

    def _fail(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.setText(message)

    # ----------------------------------------------------------- rendering

    def _ordered_items(self) -> list[tuple[str, str]]:
        remaining = dict(self._info)
        ordered: list[tuple[str, str]] = []
        for key in _PRIORITY_KEYS:
            if key in remaining:
                ordered.append((key, str(remaining.pop(key))))
        for key in sorted(remaining, key=str.lower):
            ordered.append((key, str(remaining[key])))
        return ordered

    def _render(self) -> None:
        kw = self.search_input.text().strip().lower()
        items = [
            (k, v) for k, v in self._ordered_items()
            if not kw or kw in k.lower() or kw in v.lower()
        ]
        self.table.setRowCount(len(items))
        for row, (key, value) in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(key))
            self.table.setItem(row, 1, QTableWidgetItem(value))

    # ------------------------------------------------------------- copying

    def _to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.status.setText(f"已复制: {text[:60]}")

    def _copy_cell(self, item: QTableWidgetItem) -> None:
        self._to_clipboard(item.text())

    def _show_context_menu(self, _pos) -> None:
        vp_pos = self.table.viewport().mapFromGlobal(QCursor.pos())
        item = self.table.itemAt(vp_pos)
        if item is None:
            return
        row = item.row()
        key = self.table.item(row, 0).text()
        value = self.table.item(row, 1).text()
        menu = QMenu(self)
        menu.addAction("复制字段名", lambda: self._to_clipboard(key))
        menu.addAction("复制值", lambda: self._to_clipboard(value))
        menu.addAction("复制 字段=值", lambda: self._to_clipboard(f"{key} = {value}"))
        menu.exec(QCursor.pos())
