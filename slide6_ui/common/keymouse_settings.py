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
# After a successful read, skip the display dialog and copy straight to the host
# clipboard. Both default off so the existing dialog behavior is preserved.
PASTEBOARD_AUTO_COPY_KEY = "settings/keymouse_pasteboard_auto_copy_host"
UI_XML_AUTO_COPY_KEY = "settings/keymouse_ui_xml_auto_copy_host"
# When on, the keyboard-input popup reopens at its last position. Only this
# on/off preference is persisted; the position itself is kept in memory and is
# intentionally dropped on device switch / app restart. Default off.
REMEMBER_KBD_POPUP_POS_KEY = "settings/keymouse_remember_kbd_popup_pos"
# When on, the keyboard-input popup fades to semi-transparent while keyboard
# focus is elsewhere and returns to opaque once it regains focus. Default off.
KBD_POPUP_TRANSLUCENT_KEY = "settings/keymouse_kbd_popup_translucent_unfocused"


def _settings(settings: QSettings | None = None) -> QSettings:
    return settings or QSettings()


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def get_pasteboard_auto_copy_host(settings: QSettings | None = None) -> bool:
    return _as_bool(_settings(settings).value(PASTEBOARD_AUTO_COPY_KEY, False))


def set_pasteboard_auto_copy_host(value: bool, settings: QSettings | None = None) -> None:
    _settings(settings).setValue(PASTEBOARD_AUTO_COPY_KEY, bool(value))


def get_ui_xml_auto_copy_host(settings: QSettings | None = None) -> bool:
    return _as_bool(_settings(settings).value(UI_XML_AUTO_COPY_KEY, False))


def set_ui_xml_auto_copy_host(value: bool, settings: QSettings | None = None) -> None:
    _settings(settings).setValue(UI_XML_AUTO_COPY_KEY, bool(value))


def get_remember_kbd_popup_pos(settings: QSettings | None = None) -> bool:
    return _as_bool(_settings(settings).value(REMEMBER_KBD_POPUP_POS_KEY, False))


def set_remember_kbd_popup_pos(value: bool, settings: QSettings | None = None) -> None:
    _settings(settings).setValue(REMEMBER_KBD_POPUP_POS_KEY, bool(value))


def get_kbd_popup_translucent_unfocused(settings: QSettings | None = None) -> bool:
    return _as_bool(_settings(settings).value(KBD_POPUP_TRANSLUCENT_KEY, False))


def set_kbd_popup_translucent_unfocused(value: bool, settings: QSettings | None = None) -> None:
    _settings(settings).setValue(KBD_POPUP_TRANSLUCENT_KEY, bool(value))


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
