"""gestures.py — map mouse positions to device coordinates and classify gestures.

The mapping mirrors web_console/app.js: positions are normalized against the
displayed image rectangle and multiplied by the WDA logical window size (points),
so it is independent of Retina/high-DPI pixels. Movement below a small threshold
counts as a tap; otherwise it is a swipe whose duration tracks the hold time.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect

# Movement (in widget pixels) below this counts as a tap rather than a swipe.
TAP_THRESHOLD_PX = 8
# Swipe duration clamp (ms), matching web_console.
SWIPE_MIN_MS = 120
SWIPE_MAX_MS = 1500
# In-place hold at/above this counts as a long press; clamp the reported time.
# 600ms sits comfortably above iOS's ~0.5s system long-press threshold, so the
# on-device press reliably triggers a menu while staying clear of normal taps.
LONG_PRESS_MIN_MS = 600
LONG_PRESS_MAX_MS = 3000


@dataclass(frozen=True)
class DevicePoint:
    x: int
    y: int


def to_device_point(
    pos: QPoint,
    image_rect: QRect,
    win_w: int,
    win_h: int,
) -> DevicePoint:
    """Convert a widget-space point to device logical coordinates.

    ``image_rect`` is the letterboxed rectangle (in widget coordinates) where the
    device frame is actually drawn. The point is normalized within that rect and
    clamped to [0, 1] before scaling to the device window size.
    """
    if image_rect.width() <= 0 or image_rect.height() <= 0:
        return DevicePoint(0, 0)
    fx = (pos.x() - image_rect.left()) / image_rect.width()
    fy = (pos.y() - image_rect.top()) / image_rect.height()
    fx = min(1.0, max(0.0, fx))
    fy = min(1.0, max(0.0, fy))
    return DevicePoint(round(fx * win_w), round(fy * win_h))


def is_tap(dx: float, dy: float) -> bool:
    """True if the pointer movement is small enough to count as a tap."""
    return (dx * dx + dy * dy) ** 0.5 < TAP_THRESHOLD_PX


def clamp_swipe_duration(hold_ms: float) -> int:
    """Clamp the measured hold time into the allowed swipe duration range."""
    return int(min(SWIPE_MAX_MS, max(SWIPE_MIN_MS, hold_ms)))


def is_long_press(hold_ms: float) -> bool:
    """True if an in-place hold lasted long enough to count as a long press."""
    return hold_ms >= LONG_PRESS_MIN_MS


def clamp_long_press_duration(hold_ms: float) -> int:
    """Clamp the measured hold time into the allowed long-press duration range."""
    return int(min(LONG_PRESS_MAX_MS, max(LONG_PRESS_MIN_MS, hold_ms)))
