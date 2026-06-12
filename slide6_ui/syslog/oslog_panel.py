"""oslog_panel.py — the iOS 17+ oslog view (structured, multi-column).

Renders structured ``SyslogEntry`` rows in a multi-column ``QTableView`` backed
by a custom model (data stored once as dicts, cells rendered on demand) so a
high-throughput oslog stream stays responsive: hidden columns cost nothing,
batches insert in bulk, and auto-scroll only happens when already at the bottom.

Controls:
- eye button → popup of column checkboxes (confirm to apply visible columns);
- a filter (read-only condition text + filter button → field popup). ``pid`` is
  pushed to the source (``OsTraceService.syslog(pid=...)``, re-subscribe); the
  other fields filter the structured rows consumer-side. Active conditions show
  as ``key=value&key=value``;
- an export button → popup offering text or ``.logarchive`` export;
- double-click a row to inspect its full structured fields.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.file_dialogs import open_directory, save_file
from .log_panel import LogPanelBase

# (field-key, i18n-header-key, default-width). The field key matches the dict
# produced by the platform layer's _oslog_entry_to_dict; order is the table
# column order. subsystem sits before the wide, stretching message column.
_COLUMNS: list[tuple[str, str, int]] = [
    ("pid", "oslog.col.pid", 64),
    ("timestamp", "oslog.col.timestamp", 180),
    ("level", "oslog.col.level", 72),
    ("filename", "oslog.col.filename", 150),
    ("image_name", "oslog.col.image_name", 150),
    ("subsystem", "oslog.col.subsystem", 170),
    ("category", "oslog.col.category", 120),
    ("message", "oslog.col.message", 320),
]
# Columns shown by default; the rest start hidden (toggle via the eye button).
_DEFAULT_VISIBLE = {"message"}

# Filter fields whose values come from a fixed set, rendered as a dropdown in the
# filter dialog instead of a free-text input. ``level`` mirrors pymobiledevice3's
# SyslogLogLevel names emitted by the platform layer (_oslog_entry_to_dict stores
# ``level.name``). Listed here (rather than imported) to keep the UI decoupled
# from the device library; unknown device levels still pass through as free text.
_FILTER_CHOICES: dict[str, list[str]] = {
    "level": ["NOTICE", "INFO", "DEBUG", "USER_ACTION", "ERROR", "FAULT"],
}


def _col_label(header_key: str) -> str:
    """Resolve a column header i18n key to its localized label at runtime."""
    return i18n.t(header_key)


class _OslogModel(QAbstractTableModel):
    """Table model over a list of structured oslog dicts (rendered on demand)."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(_COLUMNS)

    def data(self, index, role=Qt.DisplayRole):  # noqa: N802 - Qt override
        if role != Qt.DisplayRole or not index.isValid():
            return None
        value = self._rows[index.row()].get(_COLUMNS[index.column()][0])
        return "" if value is None else str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _col_label(_COLUMNS[section][1])
        return None

    def append(self, entries: list[dict]) -> None:
        if not entries:
            return
        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(entries) - 1)
        self._rows.extend(entries)
        self.endInsertRows()

    def remove_front(self, count: int) -> None:
        count = min(count, len(self._rows))
        if count <= 0:
            return
        self.beginRemoveRows(QModelIndex(), 0, count - 1)
        del self._rows[:count]
        self.endRemoveRows()

    def reset(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def entry_at(self, row: int) -> "dict | None":
        return self._rows[row] if 0 <= row < len(self._rows) else None


class _FilterButton(QPushButton):
    """Left-aligned, click-to-edit filter field that tail-elides long text.

    Mirrors syslog's inline filter field visually, but clicking opens the oslog
    field popup instead of typing inline; the full condition string is kept in
    the tooltip while the label shows a tail-elided ("…") version that fits.
    """

    def __init__(self, placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full = ""
        self._placeholder = placeholder
        # Look like a (clickable) text input rather than a short push button:
        # match a QLineEdit's height and give it an input-style border/background.
        self.setMinimumHeight(QLineEdit().sizeHint().height())
        self.setCursor(Qt.IBeamCursor)
        self.setStyleSheet(
            "QPushButton {"
            " text-align: left; padding: 3px 6px;"
            " border: 1px solid palette(mid); border-radius: 3px;"
            " background: palette(base); color: palette(text);"
            "}"
            "QPushButton:hover { border-color: palette(highlight); }"
        )
        self._refresh()

    def set_conditions_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def _refresh(self) -> None:
        shown = self._full or self._placeholder
        avail = max(10, self.width() - 16)
        elided = self.fontMetrics().elidedText(shown, Qt.ElideRight, avail)
        # QPushButton treats '&' as a mnemonic marker (the '&' in the joined
        # "key=value&key=value" condition would otherwise be swallowed); escape
        # it to '&&' so the separator renders literally. Elide first so the
        # width budget is measured against the real text, not the escaped one.
        super().setText(elided.replace("&", "&&"))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._refresh()


class OslogPanel(LogPanelBase):
    """oslog (structured) live table with columns / filter / export / detail."""

    SOURCE = "oslog"

    def __init__(self, *args, **kwargs) -> None:
        # Consumer-side field filter conditions (applied to the in-memory buffer
        # only — like syslog's keyword filter — so history is never lost).
        self._conditions: dict[str, str] = {}
        # Cached (field, lowered-needle) predicates so the per-line match in a
        # high-rate batch doesn't rebuild a dict for every payload.
        self._predicates: list[tuple[str, str]] = []
        super().__init__(*args, **kwargs)

    # ------------------------------------------------------------ controls

    def _build_controls(self, bar: QHBoxLayout) -> None:
        self.eye_btn = QPushButton(i18n.t("oslog.columns"))
        self.eye_btn.setToolTip(i18n.t("oslog.columns_tooltip"))
        # Clicking the field opens the multi-field popup (vs syslog typing inline).
        self.filter_btn = _FilterButton(i18n.t("oslog.filter_placeholder"))
        self.export_btn = QPushButton(i18n.t("oslog.export"))
        bar.addWidget(self.eye_btn)
        bar.addWidget(self.filter_btn, 1)
        bar.addWidget(self.export_btn)
        self.eye_btn.clicked.connect(self._show_column_menu)
        self.filter_btn.clicked.connect(self._show_filter_dialog)
        self.export_btn.clicked.connect(self._show_export_menu)

    def _build_view(self) -> QWidget:
        self.model = _OslogModel()
        view = QTableView()
        view.setModel(self.model)
        view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        view.setSelectionBehavior(QAbstractItemView.SelectRows)
        view.setSelectionMode(QAbstractItemView.SingleSelection)
        view.verticalHeader().setVisible(False)
        # Uniform, fixed row heights avoid per-row geometry work on insert.
        view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        view.verticalHeader().setDefaultSectionSize(20)
        view.setWordWrap(False)
        header = view.horizontalHeader()
        # Interactive fixed-ish widths (NOT ResizeToContents, which recomputes on
        # every insert and is the main cause of the streaming-table freeze); the
        # message column stretches to fill remaining space.
        for col, (key, _, width) in enumerate(_COLUMNS):
            if key == "message":
                header.setSectionResizeMode(col, QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.Interactive)
                view.setColumnWidth(col, width)
            view.setColumnHidden(col, key not in _DEFAULT_VISIBLE)
        view.doubleClicked.connect(self._show_row_detail)
        self.table = view
        return view

    # --------------------------------------------------------- column menu

    def _show_column_menu(self) -> None:
        menu = QMenu(self)
        holder = QWidget(menu)
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(8, 6, 8, 6)
        checks: dict[int, QCheckBox] = {}
        for col, (_, header_key, _w) in enumerate(_COLUMNS):
            cb = QCheckBox(_col_label(header_key), holder)
            cb.setChecked(not self.table.isColumnHidden(col))
            lay.addWidget(cb)
            checks[col] = cb
        apply_btn = QPushButton(i18n.t("common.apply"), holder)
        lay.addWidget(apply_btn)
        action = QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)
        apply_btn.clicked.connect(lambda: self._apply_columns(checks, menu))
        menu.exec(self.eye_btn.mapToGlobal(self.eye_btn.rect().bottomLeft()))

    def _apply_columns(self, checks: dict[int, QCheckBox], menu: QMenu) -> None:
        # Keep at least one column visible to avoid an empty, unusable table.
        if not any(cb.isChecked() for cb in checks.values()):
            checks[next(iter(checks))].setChecked(True)
        for col, cb in checks.items():
            self.table.setColumnHidden(col, not cb.isChecked())
        menu.close()

    # --------------------------------------------------------- filter popup

    def _show_filter_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(i18n.t("oslog.filter_title"))
        form = QFormLayout(dlg)
        edits: dict[str, QWidget] = {}
        for key, header_key, _w in _COLUMNS:
            current = self._conditions.get(key, "")
            choices = _FILTER_CHOICES.get(key)
            if choices:
                # Enumerable field (e.g. level): pick from a dropdown. The first
                # empty-data entry means "no filter"; an unknown current value
                # (e.g. a device LEVEL_n) is added so it stays selectable.
                combo = QComboBox(dlg)
                combo.addItem(i18n.t("oslog.filter_any"), "")
                for opt in choices:
                    combo.addItem(opt, opt)
                if current and combo.findData(current) < 0:
                    combo.addItem(current, current)
                combo.setCurrentIndex(max(0, combo.findData(current)))
                form.addRow(_col_label(header_key), combo)
                edits[key] = combo
            else:
                edit = QLineEdit(current, dlg)
                edit.setPlaceholderText(i18n.t("oslog.filter_field_placeholder"))
                form.addRow(_col_label(header_key), edit)
                edits[key] = edit
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg
        )
        form.addRow(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        dlg.move(self.filter_btn.mapToGlobal(self.filter_btn.rect().bottomLeft()))
        if dlg.exec() != QDialog.Accepted:
            return
        conditions: dict[str, str] = {}
        for key, _, _w in _COLUMNS:
            widget = edits[key]
            if isinstance(widget, QComboBox):
                value = (widget.currentData() or "").strip()
            else:
                value = widget.text().strip()
            if value:
                conditions[key] = value
        self._apply_conditions(conditions)

    def _apply_conditions(self, conditions: dict[str, str]) -> None:
        # Consumer-side only (like syslog's keyword filter): filter the in-memory
        # buffer for display — never re-subscribe the stream, so history (and the
        # live stream) are untouched when conditions change.
        self._conditions = conditions
        # Every field (including pid) is a case-insensitive substring predicate;
        # cache them lowered for the hot per-line match path.
        self._predicates = [(k, v.lower()) for k, v in conditions.items()]
        self.filter_btn.set_conditions_text(
            "&".join(f"{k}={conditions[k]}" for k, _, _w in _COLUMNS if k in conditions)
        )
        self._rebuild_view()

    def _matches(self, entry: dict) -> bool:
        for key, needle in self._predicates:
            if needle not in str(entry.get(key, "")).lower():
                return False
        return True

    # ------------------------------------------------------------ rendering

    def _at_bottom(self) -> bool:
        sb = self.table.verticalScrollBar()
        return sb.value() >= sb.maximum() - 4

    def _render_appended(self, payloads: list) -> None:
        rows = [p for p in payloads if isinstance(p, dict) and self._matches(p)]
        if not rows:
            return
        at_bottom = self._at_bottom()
        self.model.append(rows)
        if at_bottom:
            self.table.scrollToBottom()

    def _render_evicted(self, payloads: list) -> None:
        # The model rows are the filtered projection of the buffer and stay in
        # order, so the oldest evicted matches are at the model's front. Drop as
        # many front rows as evicted payloads currently pass the filter — this
        # releases the shared dicts so the byte budget actually frees memory.
        count = sum(1 for p in payloads if isinstance(p, dict) and self._matches(p))
        if count:
            self.model.remove_front(count)

    def _clear_view(self) -> None:
        self.model.reset([])

    def _rebuild_view(self) -> None:
        self.model.reset(
            [e for e in self._buffer if isinstance(e, dict) and self._matches(e)]
        )
        self.table.scrollToBottom()

    # --------------------------------------------------------- row detail

    def _show_row_detail(self, index) -> None:
        entry = self.model.entry_at(index.row()) if index is not None else None
        if not isinstance(entry, dict):
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(i18n.t("oslog.detail_title"))
        dlg.resize(560, 360)
        lay = QVBoxLayout(dlg)
        text = QPlainTextEdit(dlg)
        text.setReadOnly(True)
        lines = [
            f"{_col_label(header_key)}: {'' if entry.get(key) is None else entry.get(key)}"
            for key, header_key, _w in _COLUMNS
        ]
        text.setPlainText("\n".join(lines))
        lay.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        lay.addWidget(buttons)
        dlg.exec()

    # ------------------------------------------------------------- export

    def _show_export_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(i18n.t("oslog.export_text"), self._export_text)
        menu.addAction(i18n.t("oslog.export_logarchive"), self._export_logarchive)
        menu.exec(self.export_btn.mapToGlobal(self.export_btn.rect().bottomLeft()))

    def _visible_rows_text(self) -> str:
        lines = []
        for row in range(self.model.rowCount()):
            entry = self.model.entry_at(row)
            if isinstance(entry, dict):
                lines.append(entry.get("display") or "")
        return "\n".join(lines)

    def _export_text(self) -> None:
        path = save_file(
            self, i18n.t("oslog.export_text"), "oslog.log", [i18n.t("syslog.log_filter")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._visible_rows_text())
            self.status.setText(i18n.t("oslog.exported_text_to", path=path))
        except OSError as exc:
            self.status.setText(i18n.t("oslog.export_failed", error=exc))

    def _export_logarchive(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        path = open_directory(self, i18n.t("oslog.select_logarchive_dir"))
        if not path:
            return
        out_path = path if path.endswith(".logarchive") else f"{path}/device.logarchive"
        self.status.setText(i18n.t("oslog.collecting"))
        self.export_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.collect_logarchive(target, out_path),
            on_done=self._on_logarchive_done,
            on_error=lambda e: self._on_logarchive_done(
                {"ok": False, "error": {"message": str(e)}}
            ),
        )

    def _on_logarchive_done(self, result: dict) -> None:
        self.export_btn.setEnabled(True)
        if result.get("ok"):
            self.status.setText(
                i18n.t("oslog.logarchive_exported_to", path=result.get('data', {}).get('path', ''))
            )
        else:
            self.status.setText(
                i18n.t("oslog.logarchive_failed") + ": " + localize_error(result.get("error"))
            )
