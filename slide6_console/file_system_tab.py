"""file_system_tab.py — the "文件系统" tab.

Browses the device media partition (com.apple.afc) via an embedded
AfcBrowserPanel configured with root="media" and an empty bundle_id. This is the
general iOS file system view (media partition: DCIM, Downloads, PhotoData, …);
it deliberately does not reach into any app sandbox — per-app browsing stays in
the "App 列表" tab.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .afc_browser import AfcBrowserPanel
from .workers import AsyncRunner


class FileSystemTab(QWidget):
    """Media-partition file browser tab. Forwards device selection to the panel."""

    def __init__(self, runner: AsyncRunner) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        caption = QLabel(
            "设备文件系统（媒体分区，不含 App 沙盒）：支持浏览、导入/导出、"
            "重命名、新建文件夹与删除；可多选后右键批量下载 / 删除。"
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)
        self.panel = AfcBrowserPanel(self, runner, "", "", "media", multi_select=True)
        layout.addWidget(self.panel, 1)

    def set_target(self, target: str) -> None:
        self.panel.set_target(target)
