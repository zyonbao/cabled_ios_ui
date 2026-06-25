"""device_info.py — the "设备信息" tab.

Shows the full lockdown property set for the selected device as a key/value
table (DeviceName, ProductType, ProductVersion, SerialNumber, hardware/region
fields, ...). Reads over lockdown/usbmux through the shared AsyncRunner; needs
neither WDA nor the XPC tunnel.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.context_copy import install_table_copy_menu
from ..common.errors import localize_error
from ..common.workers import AsyncRunner

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
        self.search_input.setPlaceholderText(i18n.t("device_info.filter_placeholder"))
        self.refresh_btn = QPushButton(i18n.t("common.refresh"))
        bar.addWidget(self.search_input, 1)
        bar.addWidget(self.refresh_btn)
        root.addLayout(bar)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([i18n.t("device_info.col.field"), i18n.t("device_info.col.value")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setTextElideMode(Qt.ElideNone)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        self.status = QLabel(i18n.t("device_info.hint"))
        root.addWidget(self.status)

        self.refresh_btn.clicked.connect(self.reload_info)
        self.search_input.textChanged.connect(self._render)
        # Double-click a cell copies it; right-click copies the cell under cursor.
        self.table.itemDoubleClicked.connect(self._copy_cell)
        install_table_copy_menu(self.table, on_copied=self._flash_copied)

    # ------------------------------------------------------------- loading

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        self._info = {}
        self._render()
        if target:
            self.reload_info()
        else:
            self.status.setText(i18n.t("dev_tools.no_device"))

    def reload_info(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        self.status.setText(i18n.t("device_info.reading"))
        self.refresh_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.device_info(target),
            on_done=self._on_info,
            on_error=lambda e: self._fail(i18n.t("device_info.read_failed_detail", error=e)),
        )

    def _on_info(self, result: dict) -> None:
        self.refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self._fail(localize_error(result.get("error")))
            return
        self._info = result["data"].get("info", {})
        self._render()
        self.status.setText(i18n.t("device_info.count", count=len(self._info)))

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

    def _flash_copied(self, text: str) -> None:
        self.status.setText(i18n.t("common.copied", text=text[:60]))

    def _copy_cell(self, item: QTableWidgetItem) -> None:
        QApplication.clipboard().setText(item.text())
        self._flash_copied(item.text())
