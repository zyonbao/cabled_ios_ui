"""syslog_panel.py — the iOS <17 syslog view (raw text stream).

A single read-only text view with case-insensitive keyword filtering, pause,
clear and save-to-text. This preserves the original "系统日志" behavior; the
richer structured / filtered / exportable view lives in OslogPanel (iOS 17+).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from .log_panel import LogPanelBase, _VIEW_BLOCK_LIMIT


class SyslogPanel(LogPanelBase):
    """syslog (raw text) live view with keyword filter / pause / clear / save."""

    SOURCE = "syslog"

    def _build_controls(self, bar: QHBoxLayout) -> None:
        self.save_btn = QPushButton("另存…")
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("关键字过滤（大小写不敏感）")
        bar.addWidget(self.save_btn)
        bar.addWidget(self.filter_input, 1)
        self.save_btn.clicked.connect(self._save)
        self.filter_input.textChanged.connect(self._rebuild_view)

    def _build_view(self) -> QWidget:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setMaximumBlockCount(_VIEW_BLOCK_LIMIT)
        view.setLineWrapMode(QPlainTextEdit.NoWrap)
        return view

    # --------------------------------------------------------- rendering

    def _keyword(self) -> str:
        return self.filter_input.text().strip().lower()

    def _render_appended(self, payloads: list) -> None:
        kw = self._keyword()
        matched = [str(p) for p in payloads if not kw or kw in str(p).lower()]
        if matched:
            # One appendPlainText for the whole batch (maximumBlockCount trims).
            self.view.appendPlainText("\n".join(matched))

    def _clear_view(self) -> None:
        self.view.clear()

    def _rebuild_view(self) -> None:
        kw = self._keyword()
        self.view.clear()
        if kw:
            matched = [str(ln) for ln in self._buffer if kw in str(ln).lower()]
        else:
            matched = [str(ln) for ln in self._buffer]
        if matched:
            self.view.setPlainText("\n".join(matched))

    # ------------------------------------------------------------- save

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "另存日志", "device.log", "日志文件 (*.log *.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.view.toPlainText())
            self.status.setText(f"已保存到 {path}")
        except OSError as exc:
            self.status.setText(f"保存失败: {exc}")
