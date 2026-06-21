"""QSettings bridge for Key/Mouse runtime configuration."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QSettings
from keymouse_runtime_config import (
    DEFAULT_BOTTOM_EDGE_ROW,
    DEFAULT_ROW_DEVICE_ID,
    DEFAULT_WDA_BUNDLE_ID,
    DEFAULT_WDA_MJPEG_PORT,
    DEFAULT_WDA_PORT,
    SWIPE_UP_CONTROL_CENTER,
    SWIPE_UP_DISABLED,
    SWIPE_UP_HOLD_APP_SWITCHER,
    SWIPE_UP_HOLD_DISABLED,
    SWIPE_UP_BOTTOM,
    WDA_BUNDLE_ID_ENV,
    WDA_MJPEG_PORT_ENV,
    WDA_PORT_ENV,
    normalize_bottom_edge_row,
    normalize_bottom_edge_rows,
    normalize_swipe_up_action,
    normalize_swipe_up_hold_action,
    normalize_wda_bundle_id,
    normalize_wda_mjpeg_port,
    normalize_wda_port,
)

WDA_BUNDLE_ID_KEY = "settings/keymouse_wda_bundle_id"
WDA_PORT_KEY = "settings/keymouse_wda_port"
WDA_MJPEG_PORT_KEY = "settings/keymouse_wda_mjpeg_port"
BOTTOM_EDGE_GESTURES_KEY = "settings/keymouse_bottom_edge_gestures"


def _settings(settings: QSettings | None = None) -> QSettings:
    return settings or QSettings()


def get_wda_bundle_id(settings: QSettings | None = None) -> str:
    return normalize_wda_bundle_id(_settings(settings).value(WDA_BUNDLE_ID_KEY, DEFAULT_WDA_BUNDLE_ID))


def get_wda_port(settings: QSettings | None = None) -> int:
    return normalize_wda_port(_settings(settings).value(WDA_PORT_KEY, DEFAULT_WDA_PORT))


def get_wda_mjpeg_port(settings: QSettings | None = None) -> int:
    return normalize_wda_mjpeg_port(_settings(settings).value(WDA_MJPEG_PORT_KEY, DEFAULT_WDA_MJPEG_PORT))


def load_bottom_edge_gesture_rows(settings: QSettings | None = None) -> list[dict[str, str]]:
    raw = _settings(settings).value(BOTTOM_EDGE_GESTURES_KEY, "[]", type=str) or "[]"
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        data = []

    rows: list[dict[str, str]] = []
    default_row = DEFAULT_BOTTOM_EDGE_ROW.copy()
    seen: set[str] = {DEFAULT_ROW_DEVICE_ID}

    if isinstance(data, list):
        for item in data:
            normalized = normalize_bottom_edge_row(item)
            if normalized is None:
                continue
            if normalized["deviceId"] == DEFAULT_ROW_DEVICE_ID:
                default_row = normalized
                continue
            if normalized["deviceId"] in seen:
                continue
            rows.append(normalized)
            seen.add(normalized["deviceId"])

    rows.sort(key=lambda entry: entry["deviceId"].lower())
    return [default_row, *rows]


def save_bottom_edge_gesture_rows(
    rows: list[dict[str, str]],
    settings: QSettings | None = None,
) -> None:
    _settings(settings).setValue(
        BOTTOM_EDGE_GESTURES_KEY,
        json.dumps(normalize_bottom_edge_rows(rows), ensure_ascii=True),
    )


def load_normalized_bottom_edge_gesture_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return normalize_bottom_edge_rows(rows)


def resolve_bottom_edge_gesture_row(device_id: str, settings: QSettings | None = None) -> dict[str, str]:
    target = str(device_id or "").strip()
    rows = load_bottom_edge_gesture_rows(settings)
    if target:
        for item in rows[1:]:
            if item["deviceId"] == target:
                return item
    return rows[0]


def apply_wda_env(settings: QSettings | None = None) -> None:
    os.environ[WDA_BUNDLE_ID_ENV] = get_wda_bundle_id(settings)
    os.environ[WDA_PORT_ENV] = str(get_wda_port(settings))
    os.environ[WDA_MJPEG_PORT_ENV] = str(get_wda_mjpeg_port(settings))
