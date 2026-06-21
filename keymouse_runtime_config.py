"""Shared runtime config helpers for WDA and bottom-edge gestures.

This module stays Qt-free so both slide6_ui and ios_toolkit can use the same
defaults and normalization logic.
"""

from __future__ import annotations

from typing import Any

DEFAULT_WDA_BUNDLE_ID = "com.facebook.WebDriverAgentRunner.xctrunner"
DEFAULT_WDA_PORT = 8100
DEFAULT_WDA_MJPEG_PORT = 9100

WDA_BUNDLE_ID_ENV = "IOS_WDA_BUNDLE_ID"
WDA_PORT_ENV = "IOS_WDA_PORT"
WDA_MJPEG_PORT_ENV = "IOS_WDA_MJPEG_PORT"

DEFAULT_ROW_DEVICE_ID = "default"
SWIPE_UP_HOLD_DISABLED = "disabled"
SWIPE_UP_HOLD_APP_SWITCHER = "app_switcher"
SWIPE_UP_DISABLED = "disabled"
SWIPE_UP_BOTTOM = "bottom_swipe_up"
SWIPE_UP_CONTROL_CENTER = "control_center"

SWIPE_UP_HOLD_OPTIONS = (
    SWIPE_UP_HOLD_DISABLED,
    SWIPE_UP_HOLD_APP_SWITCHER,
)
SWIPE_UP_OPTIONS = (
    SWIPE_UP_DISABLED,
    SWIPE_UP_BOTTOM,
    SWIPE_UP_CONTROL_CENTER,
)

DEFAULT_BOTTOM_EDGE_ROW = {
    "deviceId": DEFAULT_ROW_DEVICE_ID,
    "swipeUpHold": SWIPE_UP_HOLD_APP_SWITCHER,
    "swipeUp": SWIPE_UP_BOTTOM,
}


def normalize_wda_bundle_id(value: Any) -> str:
    bundle_id = str(value or "").strip()
    return bundle_id or DEFAULT_WDA_BUNDLE_ID


def normalize_wda_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WDA_PORT
    return port if 1 <= port <= 65535 else DEFAULT_WDA_PORT


def normalize_wda_mjpeg_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WDA_MJPEG_PORT
    return port if 1 <= port <= 65535 else DEFAULT_WDA_MJPEG_PORT


def normalize_swipe_up_hold_action(value: Any) -> str:
    action = str(value or "").strip()
    return action if action in SWIPE_UP_HOLD_OPTIONS else SWIPE_UP_HOLD_DISABLED


def normalize_swipe_up_action(value: Any) -> str:
    action = str(value or "").strip()
    return action if action in SWIPE_UP_OPTIONS else SWIPE_UP_DISABLED


def normalize_bottom_edge_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    default_row = DEFAULT_BOTTOM_EDGE_ROW.copy()
    device_rows: list[dict[str, str]] = []
    seen: set[str] = {DEFAULT_ROW_DEVICE_ID}

    for item in rows:
        normalized = normalize_bottom_edge_row(item)
        if normalized is None:
            continue
        if normalized["deviceId"] == DEFAULT_ROW_DEVICE_ID:
            default_row = normalized
            continue
        if normalized["deviceId"] in seen:
            continue
        device_rows.append(normalized)
        seen.add(normalized["deviceId"])

    device_rows.sort(key=lambda entry: entry["deviceId"].lower())
    return [default_row, *device_rows]


def normalize_bottom_edge_row(item: Any, *, default_row: bool = False) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    device_id = str(item.get("deviceId") or "").strip()
    if default_row:
        device_id = DEFAULT_ROW_DEVICE_ID
    if not device_id:
        return None
    return {
        "deviceId": device_id,
        "swipeUpHold": normalize_swipe_up_hold_action(item.get("swipeUpHold")),
        "swipeUp": normalize_swipe_up_action(item.get("swipeUp")),
    }
