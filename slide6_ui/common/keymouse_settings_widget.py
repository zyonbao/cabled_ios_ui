"""Dedicated settings widget for Key/Mouse runtime configuration."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from .table_perf import batch_table_fill
from .keymouse_settings import (
    DEFAULT_ROW_DEVICE_ID,
    SWIPE_UP_BOTTOM,
    SWIPE_UP_CONTROL_CENTER,
    SWIPE_UP_DISABLED,
    SWIPE_UP_HOLD_APP_SWITCHER,
    SWIPE_UP_HOLD_DISABLED,
    WDA_BUNDLE_ID_KEY,
    WDA_MJPEG_PORT_KEY,
    WDA_PORT_KEY,
    apply_wda_env,
    get_kbd_popup_translucent_unfocused,
    get_pasteboard_auto_copy_host,
    get_remember_kbd_popup_pos,
    get_ui_xml_auto_copy_host,
    get_wda_bundle_id,
    get_wda_mjpeg_port,
    get_wda_port,
    load_bottom_edge_gesture_rows,
    load_normalized_bottom_edge_gesture_rows,
    normalize_swipe_up_action,
    normalize_swipe_up_hold_action,
    normalize_wda_bundle_id,
    normalize_wda_mjpeg_port,
    normalize_wda_port,
    save_bottom_edge_gesture_rows,
    set_kbd_popup_translucent_unfocused,
    set_pasteboard_auto_copy_host,
    set_remember_kbd_popup_pos,
    set_ui_xml_auto_copy_host,
)


def _bottom_edge_hold_label(action: str) -> str:
    return i18n.t(f"settings.keymouse.bottom_edge.option.swipe_up_hold.{action}")


def _bottom_edge_swipe_label(action: str) -> str:
    return i18n.t(f"settings.keymouse.bottom_edge.option.swipe_up.{action}")


class _DeviceIdDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        device_id: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("settings.keymouse.bottom_edge.dialog.title"))

        layout = QVBoxLayout(self)

        id_row = QHBoxLayout()
        id_row.addWidget(QLabel(i18n.t("settings.keymouse.bottom_edge.device"), self))
        self.device_id_edit = QLineEdit(self)
        self.device_id_edit.setText(device_id)
        self.device_id_edit.setPlaceholderText(i18n.t("settings.keymouse.bottom_edge.device_placeholder"))
        id_row.addWidget(self.device_id_edit, 1)
        layout.addLayout(id_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            self,
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.device_id_edit.selectAll()
        self.device_id_edit.setFocus()

    def value(self) -> str:
        return self.device_id_edit.text().strip()

    def _accept_if_valid(self) -> None:
        if self.device_id_edit.text().strip():
            self.accept()
            return
        QMessageBox.warning(
            self,
            i18n.t("settings.keymouse.bottom_edge.dialog.invalid_title"),
            i18n.t("settings.keymouse.bottom_edge.dialog.need_device_id"),
        )


# Cap the gesture table to this many visible rows; beyond it the table keeps a
# fixed height and scrolls internally so the Preferences dialog never grows past
# the screen.
_MAX_VISIBLE_GESTURE_ROWS = 3


class KeyMouseSettingsWidget(QWidget):
    # Emitted whenever this page's natural height may have changed (e.g. the
    # gesture table grew/shrank), so the host (Preferences dialog) can resize.
    content_height_changed = Signal()

    def __init__(
        self,
        settings,
        *,
        on_runtime_config_changed: Callable[[], None],
        on_bottom_gestures_changed: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_runtime_config_changed = on_runtime_config_changed
        self.on_bottom_gestures_changed = on_bottom_gestures_changed
        self.state = {"rows": load_bottom_edge_gesture_rows(self.settings)}
        self._build_ui()
        self._wire()
        self._render_rows()

    def _build_ui(self) -> None:
        col = QVBoxLayout(self)

        wda_box = QGroupBox(i18n.t("settings.keymouse.wda.group"), self)
        wda_col = QVBoxLayout(wda_box)

        bundle_row = QHBoxLayout()
        bundle_row.addWidget(QLabel(i18n.t("settings.keymouse.wda.bundle_id"), wda_box))
        self.bundle_edit = QLineEdit(wda_box)
        self.bundle_edit.setText(get_wda_bundle_id(self.settings))
        self.bundle_edit.setCursorPosition(0)
        bundle_row.addWidget(self.bundle_edit, 1)
        wda_col.addLayout(bundle_row)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel(i18n.t("settings.keymouse.wda.port"), wda_box))
        self.port_spin = QSpinBox(wda_box)
        self.port_spin.setRange(1, 65535)
        self.port_spin.setGroupSeparatorShown(False)
        self.port_spin.setValue(get_wda_port(self.settings))
        port_row.addWidget(self.port_spin)
        port_row.addStretch(1)
        wda_col.addLayout(port_row)

        mjpeg_port_row = QHBoxLayout()
        mjpeg_port_row.addWidget(QLabel(i18n.t("settings.keymouse.wda.mjpeg_port"), wda_box))
        self.mjpeg_port_spin = QSpinBox(wda_box)
        self.mjpeg_port_spin.setRange(1, 65535)
        self.mjpeg_port_spin.setGroupSeparatorShown(False)
        self.mjpeg_port_spin.setValue(get_wda_mjpeg_port(self.settings))
        mjpeg_port_row.addWidget(self.mjpeg_port_spin)
        mjpeg_port_row.addStretch(1)
        wda_col.addLayout(mjpeg_port_row)

        hint = QLabel(i18n.t("settings.keymouse.wda.hint"), wda_box)
        hint.setWordWrap(True)
        wda_col.addWidget(hint)
        col.addWidget(wda_box)

        gesture_box = QGroupBox(i18n.t("settings.keymouse.bottom_edge.group"), self)
        gesture_col = QVBoxLayout(gesture_box)

        gesture_hint = QLabel(i18n.t("settings.keymouse.bottom_edge.hint"), gesture_box)
        gesture_hint.setWordWrap(True)
        gesture_col.addWidget(gesture_hint)

        self.table = QTableWidget(0, 3, gesture_box)
        self.table.setHorizontalHeaderLabels(
            [
                i18n.t("settings.keymouse.bottom_edge.device"),
                i18n.t("settings.keymouse.bottom_edge.swipe_up_hold"),
                i18n.t("settings.keymouse.bottom_edge.swipe_up"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        gesture_col.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton(i18n.t("settings.keymouse.bottom_edge.add"), gesture_box)
        self.edit_btn = QPushButton(i18n.t("settings.keymouse.bottom_edge.edit"), gesture_box)
        self.delete_btn = QPushButton(i18n.t("settings.keymouse.bottom_edge.delete"), gesture_box)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        gesture_col.addLayout(btn_row)
        col.addWidget(gesture_box)

        copy_box = QGroupBox(i18n.t("settings.keymouse.auto_copy.group"), self)
        copy_col = QVBoxLayout(copy_box)
        self.pasteboard_auto_copy_check = QCheckBox(
            i18n.t("settings.keymouse.auto_copy.pasteboard"), copy_box
        )
        self.pasteboard_auto_copy_check.setChecked(get_pasteboard_auto_copy_host(self.settings))
        self.ui_xml_auto_copy_check = QCheckBox(
            i18n.t("settings.keymouse.auto_copy.ui_xml"), copy_box
        )
        self.ui_xml_auto_copy_check.setChecked(get_ui_xml_auto_copy_host(self.settings))
        copy_col.addWidget(self.pasteboard_auto_copy_check)
        copy_col.addWidget(self.ui_xml_auto_copy_check)
        col.addWidget(copy_box)

        keyboard_box = QGroupBox(i18n.t("settings.keymouse.keyboard_input.group"), self)
        keyboard_col = QVBoxLayout(keyboard_box)
        self.remember_kbd_popup_pos_check = QCheckBox(
            i18n.t("settings.keymouse.keyboard_input.remember_popup_pos"), keyboard_box
        )
        self.remember_kbd_popup_pos_check.setChecked(get_remember_kbd_popup_pos(self.settings))
        keyboard_col.addWidget(self.remember_kbd_popup_pos_check)
        self.kbd_popup_translucent_check = QCheckBox(
            i18n.t("settings.keymouse.keyboard_input.translucent_unfocused"), keyboard_box
        )
        self.kbd_popup_translucent_check.setChecked(
            get_kbd_popup_translucent_unfocused(self.settings)
        )
        keyboard_col.addWidget(self.kbd_popup_translucent_check)
        col.addWidget(keyboard_box)

        col.addStretch(1)

    def _wire(self) -> None:
        self.bundle_edit.editingFinished.connect(self._save_bundle)
        self.port_spin.valueChanged.connect(self._save_port)
        self.mjpeg_port_spin.valueChanged.connect(self._save_mjpeg_port)
        self.pasteboard_auto_copy_check.toggled.connect(
            lambda on: set_pasteboard_auto_copy_host(on, self.settings)
        )
        self.ui_xml_auto_copy_check.toggled.connect(
            lambda on: set_ui_xml_auto_copy_host(on, self.settings)
        )
        self.remember_kbd_popup_pos_check.toggled.connect(
            lambda on: set_remember_kbd_popup_pos(on, self.settings)
        )
        self.kbd_popup_translucent_check.toggled.connect(
            lambda on: set_kbd_popup_translucent_unfocused(on, self.settings)
        )
        self.table.itemSelectionChanged.connect(self._refresh_override_buttons)
        self.add_btn.clicked.connect(self._add_row)
        self.edit_btn.clicked.connect(self._edit_row)
        self.delete_btn.clicked.connect(self._delete_row)

    def _publish_runtime_config(self) -> None:
        apply_wda_env(self.settings)
        self.on_runtime_config_changed()

    def _save_bundle(self) -> None:
        self.settings.setValue(
            WDA_BUNDLE_ID_KEY,
            normalize_wda_bundle_id(self.bundle_edit.text()),
        )
        self.bundle_edit.setText(get_wda_bundle_id(self.settings))
        self._publish_runtime_config()

    def _save_port(self, value: int) -> None:
        self.settings.setValue(WDA_PORT_KEY, normalize_wda_port(value))
        self.port_spin.setValue(get_wda_port(self.settings))
        self._publish_runtime_config()

    def _save_mjpeg_port(self, value: int) -> None:
        self.settings.setValue(WDA_MJPEG_PORT_KEY, normalize_wda_mjpeg_port(value))
        self.mjpeg_port_spin.setValue(get_wda_mjpeg_port(self.settings))
        self._publish_runtime_config()

    def _selected_index(self) -> int:
        row = self.table.currentRow()
        return row if 0 <= row < len(self.state["rows"]) else -1

    def _refresh_override_buttons(self) -> None:
        index = self._selected_index()
        self.edit_btn.setEnabled(index > 0)
        self.delete_btn.setEnabled(index > 0)

    def _make_hold_combo(self, row_index: int, value: str) -> QComboBox:
        combo = QComboBox(self.table)
        for action in (SWIPE_UP_HOLD_DISABLED, SWIPE_UP_HOLD_APP_SWITCHER):
            combo.addItem(_bottom_edge_hold_label(action), action)
        combo.setCurrentIndex(max(0, combo.findData(normalize_swipe_up_hold_action(value))))
        combo.currentIndexChanged.connect(
            lambda _index, idx=row_index, widget=combo: self._update_row_action(
                idx, "swipeUpHold", widget.currentData()
            )
        )
        return combo

    def _make_swipe_combo(self, row_index: int, value: str) -> QComboBox:
        combo = QComboBox(self.table)
        for action in (SWIPE_UP_DISABLED, SWIPE_UP_BOTTOM, SWIPE_UP_CONTROL_CENTER):
            combo.addItem(_bottom_edge_swipe_label(action), action)
        combo.setCurrentIndex(max(0, combo.findData(normalize_swipe_up_action(value))))
        combo.currentIndexChanged.connect(
            lambda _index, idx=row_index, widget=combo: self._update_row_action(
                idx, "swipeUp", widget.currentData()
            )
        )
        return combo

    def _device_label(self, device_id: str) -> str:
        if device_id == DEFAULT_ROW_DEVICE_ID:
            return i18n.t("common.default")
        return device_id

    def _update_row_action(self, row_index: int, key: str, value: str) -> None:
        if not (0 <= row_index < len(self.state["rows"])):
            return
        self.state["rows"][row_index][key] = value
        save_bottom_edge_gesture_rows(self.state["rows"], self.settings)
        self.state["rows"] = load_bottom_edge_gesture_rows(self.settings)
        self.on_bottom_gestures_changed()

    def _render_rows(self, *, select_device_id: str | None = None) -> None:
        self.state["rows"] = load_normalized_bottom_edge_gesture_rows(self.state["rows"])
        with batch_table_fill(self.table, auto_cols=(1, 2)):
            self.table.setRowCount(len(self.state["rows"]))
            for row, item in enumerate(self.state["rows"]):
                device_item = QTableWidgetItem(self._device_label(item["deviceId"]))
                device_item.setData(Qt.ItemDataRole.UserRole, item["deviceId"])
                self.table.setItem(row, 0, device_item)
                self.table.setCellWidget(row, 1, self._make_hold_combo(row, item["swipeUpHold"]))
                self.table.setCellWidget(row, 2, self._make_swipe_combo(row, item["swipeUp"]))
        if select_device_id:
            for row, item in enumerate(self.state["rows"]):
                if item["deviceId"] == select_device_id:
                    self.table.selectRow(row)
                    break
        if self.state["rows"] and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._refresh_override_buttons()
        self._fit_table_height()

    def _fit_table_height(self) -> None:
        """Pin the table to the height of up to ``_MAX_VISIBLE_GESTURE_ROWS`` rows.

        The default QTableWidget sizeHint is a fixed ~192px regardless of row
        count, which makes the Preferences dialog (sized to the tallest tab)
        either waste space or clip rows. Size to content — header + per-row
        heights + frame — so the dialog "just fits"; cap at a few rows so a long
        list scrolls internally instead of growing the window past the screen.
        Emits ``content_height_changed`` so the host can re-fit its height.
        """
        table = self.table
        rows = table.rowCount()
        visible = min(rows, _MAX_VISIBLE_GESTURE_ROWS) if rows else 1
        total = table.horizontalHeader().sizeHint().height() + 2 * table.frameWidth()
        default_row = table.verticalHeader().defaultSectionSize()
        for row in range(visible):
            total += (table.rowHeight(row) or default_row) if rows else default_row
        if table.horizontalScrollBar().isVisible():
            total += table.horizontalScrollBar().sizeHint().height()
        table.setFixedHeight(total)
        self.content_height_changed.emit()

    def _persist_rows(self, *, select_device_id: str | None = None) -> None:
        save_bottom_edge_gesture_rows(self.state["rows"], self.settings)
        self.state["rows"] = load_bottom_edge_gesture_rows(self.settings)
        self._render_rows(select_device_id=select_device_id)
        self.on_bottom_gestures_changed()

    def _open_device_dialog(self, *, device_id: str = "") -> str | None:
        dialog = _DeviceIdDialog(self, device_id=device_id)
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.value()

    def _upsert_device(self, device_id: str, *, replace_index: int | None = None) -> bool:
        for idx, item in enumerate(self.state["rows"]):
            if idx == replace_index:
                continue
            if item["deviceId"] == device_id:
                QMessageBox.warning(
                    self,
                    i18n.t("settings.keymouse.bottom_edge.dialog.invalid_title"),
                    i18n.t("settings.keymouse.bottom_edge.dialog.duplicate_device_id"),
                )
                return False

        default_row = self.state["rows"][0]
        new_row = {
            "deviceId": device_id,
            "swipeUpHold": default_row["swipeUpHold"],
            "swipeUp": default_row["swipeUp"],
        }
        if replace_index is None:
            self.state["rows"].append(new_row)
        else:
            self.state["rows"][replace_index]["deviceId"] = device_id
        self._persist_rows(select_device_id=device_id)
        return True

    def _add_row(self) -> None:
        device_id = self._open_device_dialog()
        if device_id:
            self._upsert_device(device_id)

    def _edit_row(self) -> None:
        index = self._selected_index()
        if index <= 0:
            return
        device_id = self._open_device_dialog(device_id=self.state["rows"][index]["deviceId"])
        if device_id:
            self._upsert_device(device_id, replace_index=index)

    def _delete_row(self) -> None:
        index = self._selected_index()
        if index <= 0:
            return
        device_id = self.state["rows"][index]["deviceId"]
        answer = QMessageBox.question(
            self,
            i18n.t("settings.keymouse.bottom_edge.delete_title"),
            i18n.t("settings.keymouse.bottom_edge.delete_body", device_id=device_id),
        )
        if answer != QMessageBox.Yes:
            return
        del self.state["rows"][index]
        self._persist_rows()
