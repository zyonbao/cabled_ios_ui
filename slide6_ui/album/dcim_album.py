"""dcim_album.py — the album (DCIM) tab.

Browses the device DCIM folder (root="media", path "/DCIM") as a thumbnail grid
and supports double-click large-image viewing, multi-select export, and
multi-select delete with a single summary confirmation. There is deliberately no
"import to album": writing into /DCIM over AFC does not guarantee a Photos
library entry, so importing media is left to the file system tab.

Thumbnails are cached on disk per device (UDID). For each visible image item the
loader first tries to reuse the iOS-side small JPG under
PhotoData/Thumbnails/V2/DCIM/<album>/<file>/; if absent it falls back to reading
the original and generating a JPEG thumbnail (HEIC/HEIF via pillow-heif, other
formats via QImage). Thumbnail builds run off the GUI thread with limited
concurrency. This tab needs neither WDA nor the XPC tunnel.
"""

from __future__ import annotations

import hashlib
import io
import os
import posixpath
import re
from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.file_dialogs import open_directory
from ..common.gate_overlay import GatedTabMixin
from ..common.workers import AsyncRunner

# pillow-heif is a required dependency (see requirements.txt). Import it lazily
# and register the HEIF opener once; if it is somehow unavailable the album still
# works for non-HEIC media and HEIC items degrade to a placeholder icon.
try:
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    from PIL import Image  # noqa: F401  (used by the decode helpers)

    _HEIF_OK = True
except Exception:  # pragma: no cover - degrade gracefully if dep missing
    _HEIF_OK = False

_DCIM_ROOT = "/DCIM"
_THUMB_PX = 200
# Vertical band reserved under each thumbnail for its (single-line) file name.
_LABEL_BAND_PX = 20
# Gap between grid cells (both horizontal and vertical), per UX request.
_GRID_SPACING_PX = 16
# Reading an original just to build a thumbnail or to view it is bounded so a
# huge file (e.g. a multi-GB video mistaken for an image) is never pulled fully.
_THUMB_MAX_ORIG_BYTES = 40 * 1024 * 1024
_VIEW_MAX_ORIG_BYTES = 80 * 1024 * 1024
# iOS thumbnails are small; cap the read so an unexpected large file is skipped.
_IOS_THUMB_MAX_BYTES = 4 * 1024 * 1024
_MAX_INFLIGHT_THUMBS = 3

_HEIC_EXTS = {".heic", ".heif"}
_IMAGE_EXTS = _HEIC_EXTS | {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".dng",
}
_VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".3gp"}


def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def _is_image(name: str) -> bool:
    return _ext(name) in _IMAGE_EXTS


def _is_video(name: str) -> bool:
    return _ext(name) in _VIDEO_EXTS


def _mtime_epoch(mtime: str) -> float | None:
    """Parse an ISO mtime string (as produced by the executor) to epoch secs."""
    if not mtime:
        return None
    try:
        return datetime.fromisoformat(mtime).timestamp()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Off-thread decode / thumbnail helpers (QImage is safe off the GUI thread;
# QPixmap is not, so these return QImage / write JPEG files only).
# ---------------------------------------------------------------------------

def _decode_to_qimage(data: bytes, ext: str) -> QImage | None:
    """Decode raw image bytes to a QImage; HEIC/HEIF via pillow-heif."""
    if ext in _HEIC_EXTS:
        if not _HEIF_OK:
            return None
        try:
            from PIL import Image

            pil = Image.open(io.BytesIO(data)).convert("RGB")
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            img = QImage()
            img.loadFromData(buf.getvalue(), "PNG")
            return img if not img.isNull() else None
        except Exception:
            return None
    img = QImage()
    if img.loadFromData(data) and not img.isNull():
        return img
    return None


def _crop_square_qimage(img: QImage) -> QImage:
    """Center-crop ``img`` to a _THUMB_PX square (scale-to-cover then crop)."""
    side = _THUMB_PX
    # KeepAspectRatioByExpanding scales so the image fully covers the side x side
    # box (one dimension may overflow); then crop the centered square out.
    scaled = img.scaled(
        side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
    )
    x = max(0, (scaled.width() - side) // 2)
    y = max(0, (scaled.height() - side) // 2)
    return scaled.copy(x, y, side, side)


def _write_thumb_jpeg(data: bytes, ext: str, cache_path: str) -> bool:
    """Decode ``data`` and save a square center-cropped JPEG at cache_path."""
    if ext in _HEIC_EXTS:
        if not _HEIF_OK:
            return False
        try:
            from PIL import Image, ImageOps

            pil = Image.open(io.BytesIO(data)).convert("RGB")
            # ImageOps.fit = scale-to-cover + center-crop to the exact box.
            pil = ImageOps.fit(pil, (_THUMB_PX, _THUMB_PX))
            pil.save(cache_path, format="JPEG", quality=85)
            return True
        except Exception:
            return False
    img = _decode_to_qimage(data, ext)
    if img is None:
        return False
    return bool(_crop_square_qimage(img).save(cache_path, "JPG", 85))


def _write_square_jpeg_from_bytes(data: bytes, cache_path: str) -> bool:
    """Center-crop an already-small JPEG (e.g. an iOS thumbnail) to a square.

    The iOS-side thumbnails are JPEGs at the original aspect ratio; route them
    through the same crop pipeline so cached thumbnails look uniform regardless
    of source.
    """
    img = QImage()
    if not img.loadFromData(data) or img.isNull():
        return False
    return bool(_crop_square_qimage(img).save(cache_path, "JPG", 85))


# Bump this tag whenever the thumbnail rendering strategy changes so previously
# cached thumbnails (e.g. the old non-square ones) are treated as stale.
_THUMB_STRATEGY_TAG = "c1"


def _cache_filename(remote: str, size: int, mtime: str) -> str:
    """Cache file name keyed by remote path and invalidated by (size, mtime).

    The crop-strategy tag is part of the name so changing how thumbnails are
    rendered (e.g. switching to square center-crop) invalidates old cache files.
    """
    key = hashlib.sha1(remote.encode("utf-8")).hexdigest()
    stamp = re.sub(r"[^0-9A-Za-z]", "", f"{size}{mtime}")
    return f"{key}_{_THUMB_STRATEGY_TAG}_{stamp}.jpg"


def _build_thumb(
    target: str, album: str, name: str, remote: str, cache_path: str
) -> str | None:
    """Produce a JPEG thumbnail at ``cache_path`` and return it, or None.

    Strategy: reuse the iOS-side thumbnail first (cheap, never reads the
    original); otherwise read the original under a size cap and generate one.
    Runs on a worker thread (no Qt widget access).
    """
    # Drop stale variants for this remote path (different size/mtime).
    cache_dir = os.path.dirname(cache_path)
    prefix = os.path.basename(cache_path).split("_", 1)[0]
    try:
        for old in os.listdir(cache_dir):
            if old.startswith(prefix) and os.path.join(cache_dir, old) != cache_path:
                try:
                    os.remove(os.path.join(cache_dir, old))
                except OSError:
                    pass
    except OSError:
        pass

    # 1) iOS-side thumbnail: PhotoData/Thumbnails/V2/DCIM/<album>/<file>/<n>.JPG
    thumb_dir = f"/PhotoData/Thumbnails/V2/DCIM/{album}/{name}"
    listing = api.afc_list(target, "", "media", thumb_dir)
    if listing.get("ok"):
        jpgs = [
            e for e in listing["data"].get("entries", [])
            if not e.get("isDir") and _ext(e.get("name", "")) in (".jpg", ".jpeg")
        ]
        if jpgs:
            jpgs.sort(key=lambda e: e.get("size", 0), reverse=True)
            tname = jpgs[0]["name"]
            read = api.afc_read(
                target, "", "media", f"{thumb_dir}/{tname}",
                max_bytes=_IOS_THUMB_MAX_BYTES,
            )
            if read.get("ok") and _write_square_jpeg_from_bytes(
                read["data"]["data"], cache_path
            ):
                return cache_path

    # 2) Fallback: read the original (bounded) and generate a thumbnail.
    read = api.afc_read(
        target, "", "media", remote, max_bytes=_THUMB_MAX_ORIG_BYTES
    )
    if not read.get("ok"):
        return None
    if _write_thumb_jpeg(read["data"]["data"], _ext(name), cache_path):
        return cache_path
    return None


def _read_full_qimage(target: str, remote: str, ext: str) -> QImage | None:
    """Read an original (bounded) and decode it to a QImage for the viewer."""
    read = api.afc_read(target, "", "media", remote, max_bytes=_VIEW_MAX_ORIG_BYTES)
    if not read.get("ok"):
        return None
    return _decode_to_qimage(read["data"]["data"], ext)


class _ImageViewerDialog(QDialog):
    """A simple scrollable large-image viewer; the image is scaled to fit."""

    def __init__(self, parent: QWidget, title: str, image: QImage) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        screen = QApplication.primaryScreen().availableGeometry()
        max_w, max_h = int(screen.width() * 0.8), int(screen.height() * 0.8)
        pix = QPixmap.fromImage(image)
        if pix.width() > max_w or pix.height() > max_h:
            pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label = QLabel()
        label.setPixmap(pix)
        label.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        self.resize(min(pix.width() + 24, max_w), min(pix.height() + 24, max_h))


class DcimAlbumTab(GatedTabMixin, QWidget):
    """Thumbnail-grid browser for the device DCIM folder."""

    def __init__(self, runner: AsyncRunner) -> None:
        super().__init__()
        self.runner = runner
        self.target = ""
        self.cur_path = _DCIM_ROOT
        # _gen invalidates in-flight thumbnail callbacks across refresh / device
        # switch so they never touch a list item that has been cleared.
        self._gen = 0
        self._pending: list[tuple[int, QListWidgetItem, dict]] = []
        self._inflight = 0
        self._build_ui()
        self.init_gate()

    # --------------------------------------------------------------- cache dir

    def _cache_dir(self) -> str | None:
        """Per-device on-disk thumbnail cache directory (created on demand)."""
        if not self.target:
            return None
        from PySide6.QtCore import QStandardPaths

        # Fallback cache dir used only when AppDataLocation is unavailable; named
        # after the app identifier (the cache is regenerated on demand).
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        ) or os.path.expanduser("~/.cabled_ios")
        safe_udid = re.sub(r"[^0-9A-Za-z._-]", "_", self.target)
        path = os.path.join(base, "dcim_thumbs", safe_udid)
        os.makedirs(path, exist_ok=True)
        return path

    # ------------------------------------------------------------------- ui

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        # Unified toolbar order across all file browsers: 上一级 - 路径编辑框 - 刷新.
        # Editable path (Enter to jump to any path under the DCIM root).
        self.up_btn = QPushButton(i18n.t("common.up"))
        self.path_edit = QLineEdit(self._display_path())
        self.path_edit.setPlaceholderText(i18n.t("afc.path_placeholder"))
        self.refresh_btn = QPushButton(i18n.t("common.refresh"))
        self.export_btn = QPushButton(i18n.t("album.export_selected"))
        bar.addWidget(self.up_btn)
        bar.addWidget(self.path_edit, 1)
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.export_btn)
        layout.addLayout(bar)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(_THUMB_PX, _THUMB_PX))
        # Grid = thumbnail + a fixed band for the (one-line) file name. Inter-item
        # gap is controlled by spacing so cells sit close together (~16px apart).
        self.list.setGridSize(QSize(_THUMB_PX, _THUMB_PX + _LABEL_BAND_PX))
        self.list.setSpacing(_GRID_SPACING_PX)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setWordWrap(False)
        self.list.setTextElideMode(Qt.ElideMiddle)
        self.list.setUniformItemSizes(True)
        self.list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.list, 1)

        self.status = QLabel(i18n.t("common.select_device_first"))
        layout.addWidget(self.status)

        self.path_edit.returnPressed.connect(self._on_path_entered)
        self.up_btn.clicked.connect(self._go_up)
        self.refresh_btn.clicked.connect(self._refresh)
        self.export_btn.clicked.connect(self._export_selected)

    def set_target(self, target: str) -> None:
        self.target = target or ""
        self.cur_path = _DCIM_ROOT
        if self.target:
            self._refresh()
        else:
            self._gen += 1
            self._pending.clear()
            self.list.clear()
            self.path_edit.setText(self._display_path())
            self.up_btn.setEnabled(self.cur_path != _DCIM_ROOT)
            self.status.setText(i18n.t("common.select_device_first"))

    # -------------------------------------------------------------- listing

    def _display_path(self) -> str:
        """Render the real /DCIM-rooted path with the context root shown as '/'.

        '/DCIM' -> '/', '/DCIM/100APPLE' -> '/100APPLE'. Keeps the path bar
        consistent with the other browsers while navigation stays clamped to the
        real DCIM root underneath."""
        if self.cur_path == _DCIM_ROOT:
            return "/"
        return self.cur_path[len(_DCIM_ROOT):] or "/"

    def _to_real_path(self, display: str) -> str:
        """Map a '/'-rooted display path back to a real /DCIM-rooted path.

        The result is normalized and clamped within the DCIM root so the album
        tab never browses outside /DCIM."""
        text = display.strip()
        if not text.startswith("/"):
            text = "/" + text
        norm = posixpath.normpath(_DCIM_ROOT + text)
        if norm != _DCIM_ROOT and not norm.startswith(_DCIM_ROOT + "/"):
            norm = _DCIM_ROOT
        return norm

    def _go_up(self) -> None:
        if self.cur_path != _DCIM_ROOT:
            parent = posixpath.dirname(self.cur_path.rstrip("/")) or "/"
            # Never navigate above the DCIM root from the album tab.
            self.cur_path = parent if parent.startswith(_DCIM_ROOT) else _DCIM_ROOT
            self._refresh()

    def _on_path_entered(self) -> None:
        # The path bar shows the DCIM root as '/'; map it back to the real
        # /DCIM-rooted path (normalized and clamped) before navigating.
        self.cur_path = self._to_real_path(self.path_edit.text())
        self._refresh()

    def _refresh(self) -> None:
        # New generation: any pending/in-flight thumbnail callbacks become stale.
        self._gen += 1
        self._pending.clear()
        self.path_edit.setText(self._display_path())
        self.up_btn.setEnabled(self.cur_path != _DCIM_ROOT)
        self.list.clear()
        if not self.target:
            self.status.setText(i18n.t("common.select_device_first"))
            return
        self.status.setText(i18n.t("afc.loading"))
        gen = self._gen
        self.runner.submit(
            lambda: api.afc_list(self.target, "", "media", self.cur_path),
            on_done=lambda r: self._on_list(r, gen),
            on_error=lambda e: self.status.setText(i18n.t("afc.load_failed_detail", error=e)),
        )

    def _on_list(self, result: dict, gen: int) -> None:
        if gen != self._gen:
            return
        if not result.get("ok"):
            self.status.setText(i18n.t("afc.load_failed") + ": " + localize_error(result.get("error")))
            return
        # Hide dot-prefixed system entries (e.g. DCIM/.MISC). Real photos live in
        # DCF album folders (100APPLE, 101APPLE, …); keeping /DCIM as the root
        # rather than hard-coding 100APPLE preserves all album folders across
        # devices/iOS versions while still hiding the helper directory.
        entries = [
            e for e in result["data"].get("entries", [])
            if not e.get("name", "").startswith(".")
        ]
        album = posixpath.basename(self.cur_path.rstrip("/"))
        file_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        dir_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        media_icon = self.style().standardIcon(QStyle.SP_FileDialogContentsView)
        to_build: list[tuple[QListWidgetItem, dict]] = []
        for entry in entries:
            name = entry.get("name", "")
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, entry)
            item.setToolTip(name)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            # Pin the cell size so the name band is always shown (with
            # setUniformItemSizes the first hint would otherwise clip text).
            item.setSizeHint(QSize(_THUMB_PX, _THUMB_PX + _LABEL_BAND_PX))
            if entry.get("isDir"):
                item.setIcon(dir_icon)
            elif _is_image(name):
                item.setIcon(media_icon)  # placeholder until the thumb arrives
                to_build.append((item, entry))
            else:
                # Videos and other files: placeholder only (no first-frame).
                item.setIcon(media_icon if _is_video(name) else file_icon)
            self.list.addItem(item)
        self.status.setText(i18n.t("afc.item_count", count=len(entries)))
        # Queue thumbnail builds top-down (approximates visible-first).
        self._pending = [(self._gen, item, entry) for item, entry in to_build]
        self._pump()

    # ----------------------------------------------------------- thumbnails

    def _pump(self) -> None:
        """Start queued thumbnail builds up to the concurrency limit."""
        cache_dir = self._cache_dir()
        while self._inflight < _MAX_INFLIGHT_THUMBS and self._pending:
            gen, item, entry = self._pending.pop(0)
            if gen != self._gen:
                continue
            name = entry.get("name", "")
            remote = posixpath.join(self.cur_path, name)
            album = posixpath.basename(self.cur_path.rstrip("/"))
            cache_path = (
                os.path.join(
                    cache_dir,
                    _cache_filename(remote, entry.get("size", 0), entry.get("mtime", "")),
                )
                if cache_dir
                else None
            )
            if cache_path and os.path.exists(cache_path):
                item.setIcon(QIcon(cache_path))  # local cache hit
                continue
            if not cache_path:
                continue
            self._inflight += 1
            self.runner.submit(
                lambda t=self.target, a=album, n=name, r=remote, c=cache_path: _build_thumb(
                    t, a, n, r, c
                ),
                on_done=lambda path, g=gen, it=item: self._on_thumb(path, g, it),
                on_error=lambda _e, g=gen: self._on_thumb(None, g, None),
            )

    def _on_thumb(self, path: str | None, gen: int, item: QListWidgetItem | None) -> None:
        self._inflight -= 1
        if gen == self._gen and item is not None and path:
            item.setIcon(QIcon(path))
        self._pump()

    # ---------------------------------------------------------------- view

    def _on_double_click(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.UserRole)
        if not entry:
            return
        name = entry.get("name", "")
        if entry.get("isDir"):
            self.cur_path = posixpath.join(self.cur_path, name)
            self._refresh()
            return
        if not _is_image(name):
            QMessageBox.information(
                self, i18n.t("album.cannot_preview_title"), i18n.t("album.cannot_preview_body", name=name)
            )
            return
        remote = posixpath.join(self.cur_path, name)
        self.status.setText(i18n.t("album.opening", name=name))
        gen = self._gen
        self.runner.submit(
            lambda: _read_full_qimage(self.target, remote, _ext(name)),
            on_done=lambda img: self._show_image(img, name, gen),
            on_error=lambda e: self.status.setText(i18n.t("album.open_failed", error=e)),
        )

    def _show_image(self, image: QImage | None, name: str, gen: int) -> None:
        if gen != self._gen:
            return
        if image is None or image.isNull():
            QMessageBox.warning(self, i18n.t("album.cannot_show_title"), i18n.t("album.cannot_decode", name=name))
            self.status.setText("")
            return
        self.status.setText("")
        _ImageViewerDialog(self, name, image).exec()

    # -------------------------------------------------------- selection ops

    def _selected_files(self) -> list[dict]:
        out: list[dict] = []
        for item in self.list.selectedItems():
            entry = item.data(Qt.UserRole)
            if entry and not entry.get("isDir"):
                out.append(entry)
        return out

    def _export_selected(self) -> None:
        files = self._selected_files()
        if not files:
            self.status.setText(i18n.t("album.need_select_export"))
            return
        out_dir = open_directory(self, i18n.t("album.export_to"))
        if not out_dir:
            return
        self.status.setText(i18n.t("album.exporting", count=len(files)))
        names = [f.get("name", "") for f in files]
        mtimes = {f.get("name", ""): f.get("mtime", "") for f in files}

        def _do_export() -> dict:
            ok, failed = 0, []
            for name in names:
                remote = posixpath.join(self.cur_path, name)
                local = os.path.join(out_dir, name)
                res = api.afc_pull(self.target, "", "media", remote, local)
                if res.get("ok"):
                    ok += 1
                    epoch = _mtime_epoch(mtimes.get(name, ""))
                    if epoch is not None:
                        try:
                            os.utime(local, (epoch, epoch))
                        except OSError:
                            pass
                else:
                    failed.append(name)
            return {"ok": ok, "failed": failed}

        self.runner.submit(
            _do_export,
            on_done=self._on_export_done,
            on_error=lambda e: self.status.setText(i18n.t("album.export_failed", error=e)),
        )

    def _on_export_done(self, result: dict) -> None:
        failed = result.get("failed", [])
        if failed:
            self.status.setText(i18n.t("album.exported_partial", ok=result['ok'], failed=len(failed)))
        else:
            self.status.setText(i18n.t("album.exported_ok", ok=result['ok']))
