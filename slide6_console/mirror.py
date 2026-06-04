"""mirror.py — consume WDA's MJPEG broadcaster and render the live device screen.

A background QThread connects to the device's MJPEG port (forwarded by
executor_ios), performs the same handshake as web_console's proxy, extracts JPEG
frames from the multipart stream, decodes them off the main thread, and emits a
QImage for the main thread to paint. ScreenView draws the latest frame
letterboxed and turns mouse interaction into tap/swipe gestures.
"""

from __future__ import annotations

import socket

from PySide6.QtCore import QPoint, QRect, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from .gestures import clamp_swipe_duration, is_tap, to_device_point

# JPEG markers used to slice frames out of the multipart MJPEG stream.
_SOI = b"\xff\xd8"  # Start Of Image
_EOI = b"\xff\xd9"  # End Of Image
_MAX_BUFFER = 8 * 1024 * 1024  # guard against unbounded growth on a bad stream


class MjpegThread(QThread):
    """Reads the MJPEG stream and emits decoded frames."""

    frame_ready = Signal(QImage)
    stream_error = Signal(str)

    def __init__(self, host: str, port: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            sock = socket.create_connection((self._host, self._port), timeout=10)
        except OSError as exc:
            self.stream_error.emit(f"无法连接画面流: {exc}")
            return

        sock.settimeout(5.0)
        try:
            # WDA's broadcaster only starts streaming after the client writes.
            sock.sendall(b"GET / HTTP/1.0\r\n\r\n")
            buffer = b""
            # Consume the HTTP response headers first.
            while b"\r\n\r\n" not in buffer:
                if self._stop:
                    return
                chunk = sock.recv(65536)
                if not chunk:
                    self.stream_error.emit("画面流已中断")
                    return
                buffer += chunk
            buffer = buffer.split(b"\r\n\r\n", 1)[1]

            while not self._stop:
                # Extract any complete JPEG frames currently in the buffer.
                while True:
                    start = buffer.find(_SOI)
                    if start < 0:
                        break
                    end = buffer.find(_EOI, start + 2)
                    if end < 0:
                        break
                    jpeg = buffer[start:end + 2]
                    buffer = buffer[end + 2:]
                    image = QImage.fromData(jpeg, "JPG")
                    if not image.isNull():
                        self.frame_ready.emit(image)

                if len(buffer) > _MAX_BUFFER:
                    buffer = b""  # drop a corrupt/oversized accumulation

                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not self._stop:
                        self.stream_error.emit(f"画面流已中断: {exc}")
                    return
                if not chunk:
                    if not self._stop:
                        self.stream_error.emit("画面流已中断")
                    return
                buffer += chunk
        finally:
            try:
                sock.close()
            except OSError:
                pass


class ScreenView(QWidget):
    """Displays the latest device frame and emits tap/swipe gestures."""

    tap = Signal(int, int)
    swipe = Signal(int, int, int, int, int)
    gesture_finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._win_w = 0
        self._win_h = 0
        self._press_pos: QPoint | None = None
        self._press_ms = 0
        self._overlay_text = "请选择一个设备"
        self.setMinimumSize(240, 320)
        self.setMouseTracking(False)

    # -- state -------------------------------------------------------------

    def set_window_size(self, width: int, height: int) -> None:
        self._win_w = int(width)
        self._win_h = int(height)

    def set_overlay(self, text: str | None) -> None:
        self._overlay_text = text or ""
        self.update()

    def clear_frame(self) -> None:
        self._pixmap = None
        self.update()

    def on_frame(self, image: QImage) -> None:
        # Always render only the latest frame (implicit frame dropping).
        self._pixmap = QPixmap.fromImage(image)
        self._overlay_text = ""
        self.update()

    # -- geometry ----------------------------------------------------------

    def image_rect(self) -> QRect:
        """Letterboxed rectangle (widget coords) where the frame is drawn."""
        if self._pixmap is None or self._pixmap.isNull():
            return QRect()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if pw <= 0 or ph <= 0:
            return QRect()
        avail = self.rect()
        scale = min(avail.width() / pw, avail.height() / ph)
        w = int(pw * scale)
        h = int(ph * scale)
        x = avail.left() + (avail.width() - w) // 2
        y = avail.top() + (avail.height() - h) // 2
        return QRect(x, y, w, h)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: D401, N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if self._pixmap is not None and not self._pixmap.isNull():
            target = self.image_rect()
            painter.drawPixmap(target, self._pixmap)
        if self._overlay_text:
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter, self._overlay_text)

    # -- gestures ----------------------------------------------------------

    def _can_interact(self) -> bool:
        return self._pixmap is not None and self._win_w > 0 and self._win_h > 0

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if not self._can_interact():
            return
        self._press_pos = event.position().toPoint()
        self._press_ms = event.timestamp()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._press_pos is None or not self._can_interact():
            self._press_pos = None
            return
        start = self._press_pos
        self._press_pos = None
        end = event.position().toPoint()
        rect = self.image_rect()
        start_pt = to_device_point(start, rect, self._win_w, self._win_h)
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        if is_tap(dx, dy):
            self.tap.emit(start_pt.x, start_pt.y)
        else:
            end_pt = to_device_point(end, rect, self._win_w, self._win_h)
            hold = max(0, event.timestamp() - self._press_ms)
            dur = clamp_swipe_duration(hold)
            self.swipe.emit(start_pt.x, start_pt.y, end_pt.x, end_pt.y, dur)
        self.gesture_finished.emit()
