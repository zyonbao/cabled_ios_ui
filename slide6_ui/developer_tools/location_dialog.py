"""location_dialog.py — virtual GPS location dialog.

Sets a single simulated coordinate, plays back a GPX trajectory, or walks a
self-interpolated multi-waypoint route at a chosen speed. On iOS < 17 the
simulation is applied over the lockdown DtSimulateLocation service; on iOS 17+
the platform layer keeps a background DVT session alive so the simulation (and
ongoing route playback) persists. All blocking calls go through the shared
AsyncRunner; clearing stops any in-flight route playback.
"""

from __future__ import annotations

import os

from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.file_dialogs import open_existing_file
from ..common.focus import suppress_auto_focus
from ..common.workers import AsyncRunner


class LocationDialog(QDialog):
    """Set a single point, or play back a GPX / manual trajectory."""

    def __init__(self, runner: AsyncRunner, target: str, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._target = target
        self.setWindowTitle(i18n.t("location.title"))
        self.resize(460, 460)
        self._build_ui()
        self._wire()
        # Don't auto-focus the coordinate / path fields when the dialog opens.
        suppress_auto_focus(self)

    # -- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_point_tab(), i18n.t("location.tab.point"))
        self.tabs.addTab(self._build_gpx_tab(), i18n.t("location.tab.gpx"))
        self.tabs.addTab(self._build_manual_tab(), i18n.t("location.tab.manual"))
        root.addWidget(self.tabs)

        # Shared clear control + status (clearing also stops route playback).
        self.clear_btn = QPushButton(i18n.t("location.clear"))
        root.addWidget(self.clear_btn)

        self.status = QLabel(i18n.t("location.status_hint"))
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def _build_point_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.lat_input = QLineEdit()
        self.lat_input.setPlaceholderText(i18n.t("location.lat_placeholder"))
        self.lat_input.setValidator(QDoubleValidator(-90.0, 90.0, 8, self))
        self.lon_input = QLineEdit()
        self.lon_input.setPlaceholderText(i18n.t("location.lon_placeholder"))
        self.lon_input.setValidator(QDoubleValidator(-180.0, 180.0, 8, self))
        form.addRow(i18n.t("location.lat"), self.lat_input)
        form.addRow(i18n.t("location.lon"), self.lon_input)
        layout.addLayout(form)
        self.set_btn = QPushButton(i18n.t("location.set"))
        layout.addWidget(self.set_btn)
        layout.addStretch(1)
        return w

    def _build_gpx_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        pick_row = QHBoxLayout()
        self.gpx_path_input = QLineEdit()
        self.gpx_path_input.setPlaceholderText(i18n.t("location.gpx_placeholder"))
        self.gpx_pick_btn = QPushButton(i18n.t("common.browse"))
        pick_row.addWidget(self.gpx_path_input, 1)
        pick_row.addWidget(self.gpx_pick_btn)
        layout.addLayout(pick_row)

        self.gpx_disable_sleep = QCheckBox(i18n.t("location.gpx_ignore_ts"))
        layout.addWidget(self.gpx_disable_sleep)

        jitter_row = QHBoxLayout()
        jitter_row.addWidget(QLabel(i18n.t("location.jitter")))
        self.gpx_jitter = QSpinBox()
        self.gpx_jitter.setRange(0, 60000)
        self.gpx_jitter.setSingleStep(100)
        jitter_row.addWidget(self.gpx_jitter)
        jitter_row.addStretch(1)
        layout.addLayout(jitter_row)

        self.gpx_play_btn = QPushButton(i18n.t("location.play"))
        layout.addWidget(self.gpx_play_btn)

        hint = QLabel(i18n.t("location.gpx_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return w

    def _build_manual_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self.wp_table = QTableWidget(0, 2)
        self.wp_table.setHorizontalHeaderLabels([i18n.t("location.lat"), i18n.t("location.lon")])
        self.wp_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.wp_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        layout.addWidget(self.wp_table, 1)

        wp_btn_row = QHBoxLayout()
        self.wp_add_btn = QPushButton(i18n.t("location.add_waypoint"))
        self.wp_del_btn = QPushButton(i18n.t("location.del_waypoint"))
        wp_btn_row.addWidget(self.wp_add_btn)
        wp_btn_row.addWidget(self.wp_del_btn)
        wp_btn_row.addStretch(1)
        layout.addLayout(wp_btn_row)

        speed_form = QFormLayout()
        self.speed_input = QDoubleSpinBox()
        self.speed_input.setRange(0.1, 1000.0)
        self.speed_input.setValue(5.0)
        self.speed_input.setSuffix(" km/h")
        self.speed_input.setDecimals(1)
        speed_form.addRow(i18n.t("location.speed"), self.speed_input)
        layout.addLayout(speed_form)

        self.manual_play_btn = QPushButton(i18n.t("location.play"))
        layout.addWidget(self.manual_play_btn)
        return w

    # -- Wiring ------------------------------------------------------------

    def _wire(self) -> None:
        self.set_btn.clicked.connect(self._set)
        self.clear_btn.clicked.connect(self._clear)
        self.gpx_pick_btn.clicked.connect(self._pick_gpx)
        self.gpx_play_btn.clicked.connect(self._play_gpx)
        self.gpx_path_input.returnPressed.connect(self._play_gpx)
        self.wp_add_btn.clicked.connect(self._add_waypoint)
        self.wp_del_btn.clicked.connect(self._del_waypoint)
        self.manual_play_btn.clicked.connect(self._play_manual)

    # -- Single point ------------------------------------------------------

    def _set(self) -> None:
        try:
            lat = float(self.lat_input.text().strip())
            lon = float(self.lon_input.text().strip())
        except ValueError:
            self.status.setText(i18n.t("location.invalid_coord"))
            return
        self.status.setText(i18n.t("location.setting"))
        self.set_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.set_location(self._target, lat, lon),
            on_done=self._on_set,
            on_error=lambda e: self._after(self.set_btn, i18n.t("location.set_failed_detail", error=e)),
        )

    def _on_set(self, result: dict) -> None:
        if not result.get("ok"):
            self._after(self.set_btn, localize_error(result.get("error")))
            return
        data = result["data"]
        self._after(
            self.set_btn,
            i18n.t("location.set_ok", lat=data.get('latitude'), lon=data.get('longitude')),
        )

    # -- GPX trajectory ----------------------------------------------------

    def _pick_gpx(self) -> None:
        # Route through the shared picker; native vs non-native is governed by
        # file_dialogs.USE_NATIVE_FILE_DIALOG (native stays off until the app is
        # code-signed). Either way the result fills the editable path field.
        current = self.gpx_path_input.text().strip()
        start_dir = os.path.dirname(current) if current else None
        path = open_existing_file(
            self, i18n.t("location.pick_gpx"),
            [i18n.t("location.gpx_filter"), i18n.t("dev_tools.mount.all_files")], start_dir
        )
        if path:
            self.gpx_path_input.setText(path)

    def _play_gpx(self) -> None:
        path = os.path.expanduser(self.gpx_path_input.text().strip())
        if not path:
            self.status.setText(i18n.t("location.need_gpx_path"))
            return
        if not os.path.isfile(path):
            self.status.setText(i18n.t("location.path_not_file", path=path))
            return
        disable_sleep = self.gpx_disable_sleep.isChecked()
        jitter = self.gpx_jitter.value()
        self.status.setText(i18n.t("location.gpx_starting"))
        self.gpx_play_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.play_route_gpx(self._target, path, disable_sleep, jitter),
            on_done=lambda r: self._on_play(r, self.gpx_play_btn),
            on_error=lambda e: self._after(self.gpx_play_btn, i18n.t("location.play_failed_detail", error=e)),
        )

    # -- Manual trajectory -------------------------------------------------

    def _add_waypoint(self) -> None:
        row = self.wp_table.rowCount()
        self.wp_table.insertRow(row)
        self.wp_table.setItem(row, 0, QTableWidgetItem(""))
        self.wp_table.setItem(row, 1, QTableWidgetItem(""))

    def _del_waypoint(self) -> None:
        rows = sorted(
            {idx.row() for idx in self.wp_table.selectedIndexes()}, reverse=True
        )
        for row in rows:
            self.wp_table.removeRow(row)

    def _collect_waypoints(self) -> "list | None":
        waypoints: list = []
        for row in range(self.wp_table.rowCount()):
            lat_item = self.wp_table.item(row, 0)
            lon_item = self.wp_table.item(row, 1)
            lat_text = lat_item.text().strip() if lat_item else ""
            lon_text = lon_item.text().strip() if lon_item else ""
            if not lat_text and not lon_text:
                continue  # skip blank rows
            try:
                lat = float(lat_text)
                lon = float(lon_text)
            except ValueError:
                self.status.setText(i18n.t("location.row_invalid", row=row + 1))
                return None
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                self.status.setText(i18n.t("location.row_out_of_range", row=row + 1))
                return None
            waypoints.append([lat, lon])
        return waypoints

    def _play_manual(self) -> None:
        waypoints = self._collect_waypoints()
        if waypoints is None:
            return
        if len(waypoints) < 2:
            self.status.setText(i18n.t("location.need_two_waypoints"))
            return
        speed_mps = self.speed_input.value() / 3.6  # km/h -> m/s
        self.status.setText(i18n.t("location.manual_starting"))
        self.manual_play_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.play_route_manual(self._target, waypoints, speed_mps),
            on_done=lambda r: self._on_play(r, self.manual_play_btn),
            on_error=lambda e: self._after(self.manual_play_btn, i18n.t("location.play_failed_detail", error=e)),
        )

    def _on_play(self, result: dict, btn: QPushButton) -> None:
        if not result.get("ok"):
            self._after(btn, localize_error(result.get("error")))
            return
        points = result["data"].get("points", 0)
        self._after(btn, i18n.t("location.playing", points=points))

    # -- Clear / restore ---------------------------------------------------

    def _clear(self) -> None:
        self.status.setText(i18n.t("location.clearing"))
        self.clear_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.clear_location(self._target),
            on_done=self._on_clear,
            on_error=lambda e: self._after(self.clear_btn, i18n.t("location.clear_failed_detail", error=e)),
        )

    def _on_clear(self, result: dict) -> None:
        if not result.get("ok"):
            self._after(self.clear_btn, localize_error(result.get("error")))
            return
        self._after(self.clear_btn, i18n.t("location.cleared"))

    # -- Helpers -----------------------------------------------------------

    def _after(self, btn: QPushButton, message: str) -> None:
        btn.setEnabled(True)
        self.status.setText(message)
