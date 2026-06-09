"""process_dialog.py — DVT process management dialog.

Lists the device's running processes (DVT DeviceInfo.proclist), supports
case-insensitive filtering by process name, launching an app by bundle id
(ProcessControl.launch), killing a selected process (ProcessControl.kill), and
viewing a read-only detail view of a selected process. Processes cannot be
modified — only created (launched), killed, or inspected.

Requires a mounted DDI (and, on iOS 17+, a running XPC tunnel); all blocking
calls go through the shared AsyncRunner.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ios_toolkit import toolkit_api as api

from ..common.workers import AsyncRunner


class ProcessDialog(QDialog):
    """Process management: list / filter / launch / kill / inspect."""

    def __init__(self, runner: AsyncRunner, target: str, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._target = target
        self._procs: list[dict] = []
        self._view: list[dict] = []
        self.setWindowTitle("进程管理")
        self.resize(720, 520)
        self._build_ui()
        self._wire()
        self.reload()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Launch row: create a process by bundle id.
        launch_row = QHBoxLayout()
        self.bundle_input = QLineEdit()
        self.bundle_input.setPlaceholderText("输入 bundle id 启动（如 com.apple.Preferences）")
        self.launch_btn = QPushButton("启动")
        launch_row.addWidget(QLabel("Bundle ID"))
        launch_row.addWidget(self.bundle_input, 1)
        launch_row.addWidget(self.launch_btn)
        root.addLayout(launch_row)

        # Filter / actions row.
        bar = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("按进程名过滤（大小写不敏感）")
        self.refresh_btn = QPushButton("刷新")
        self.info_btn = QPushButton("查看明细")
        self.kill_btn = QPushButton("结束进程")
        bar.addWidget(self.filter_input, 1)
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.info_btn)
        bar.addWidget(self.kill_btn)
        root.addLayout(bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["PID", "名称", "App", "启动时间"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        self.status = QLabel("正在加载进程列表…")
        root.addWidget(self.status)

    def _wire(self) -> None:
        self.launch_btn.clicked.connect(self._launch)
        self.bundle_input.returnPressed.connect(self._launch)
        self.refresh_btn.clicked.connect(self.reload)
        self.filter_input.textChanged.connect(self._render)
        self.info_btn.clicked.connect(self._show_info)
        self.kill_btn.clicked.connect(self._kill)
        self.table.itemDoubleClicked.connect(lambda *_: self._show_info())

    # ------------------------------------------------------------- loading

    def reload(self) -> None:
        if not self._target:
            self.status.setText("未选择设备")
            return
        self.status.setText("正在加载进程列表…")
        self.refresh_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.list_processes(self._target),
            on_done=self._on_procs,
            on_error=lambda e: self._fail(f"加载失败: {e}"),
        )

    def _on_procs(self, result: dict) -> None:
        self.refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self._fail(result.get("error", {}).get("message", "加载失败"))
            return
        self._procs = result["data"].get("processes", [])
        self._render()
        self.status.setText(f"共 {len(self._procs)} 个进程")

    def _fail(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.setText(message)

    def _filtered(self) -> list[dict]:
        kw = self.filter_input.text().strip().lower()
        if not kw:
            return list(self._procs)
        return [p for p in self._procs if kw in str(p.get("name", "")).lower()]

    def _render(self) -> None:
        self._view = self._filtered()
        self.table.setRowCount(len(self._view))
        for row, p in enumerate(self._view):
            self.table.setItem(row, 0, QTableWidgetItem(str(p.get("pid", ""))))
            self.table.setItem(row, 1, QTableWidgetItem(str(p.get("name", ""))))
            self.table.setItem(row, 2, QTableWidgetItem("是" if p.get("isApplication") else ""))
            self.table.setItem(row, 3, QTableWidgetItem(str(p.get("startDate", ""))))

    # ----------------------------------------------------------- selection

    def _selected(self) -> "dict | None":
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not rows or not (0 <= rows[0] < len(self._view)):
            return None
        return self._view[rows[0]]

    # -------------------------------------------------------------- launch

    def _launch(self) -> None:
        bundle_id = self.bundle_input.text().strip()
        if not bundle_id:
            self.status.setText("请输入要启动的 bundle id")
            return
        self.status.setText(f"正在启动 {bundle_id}…")
        self.launch_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.launch_app_dvt(self._target, bundle_id),
            on_done=self._on_launched,
            on_error=lambda e: self._after_launch(f"启动失败: {e}"),
        )

    def _on_launched(self, result: dict) -> None:
        if not result.get("ok"):
            self._after_launch(result.get("error", {}).get("message", "启动失败"))
            return
        pid = result["data"].get("pid")
        self._after_launch(f"已启动，PID={pid}")
        self.reload()

    def _after_launch(self, message: str) -> None:
        self.launch_btn.setEnabled(True)
        self.status.setText(message)

    # ---------------------------------------------------------------- kill

    def _kill(self) -> None:
        proc = self._selected()
        if proc is None:
            self.status.setText("请先选择要结束的进程")
            return
        pid = proc.get("pid")
        name = proc.get("name", "")
        reply = QMessageBox.question(
            self, "结束进程",
            f"确定结束进程 {name}（PID={pid}）？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.status.setText(f"正在结束 PID={pid}…")
        self.kill_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.kill_process(self._target, pid),
            on_done=self._on_killed,
            on_error=lambda e: self._after_kill(f"结束失败: {e}"),
        )

    def _on_killed(self, result: dict) -> None:
        if not result.get("ok"):
            self._after_kill(result.get("error", {}).get("message", "结束失败"))
            return
        self._after_kill(f"已结束 PID={result['data'].get('pid')}")
        self.reload()

    def _after_kill(self, message: str) -> None:
        self.kill_btn.setEnabled(True)
        self.status.setText(message)

    # ---------------------------------------------------------------- info

    def _show_info(self) -> None:
        proc = self._selected()
        if proc is None:
            self.status.setText("请先选择一个进程")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"进程明细 — {proc.get('name', '')}")
        dlg.resize(420, 300)
        layout = QVBoxLayout(dlg)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        lines = [f"{k}: {v}" for k, v in proc.items()]
        view.setPlainText("\n".join(lines))
        layout.addWidget(view)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
        dlg.exec()
