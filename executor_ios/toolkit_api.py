"""
toolkit_api.py — iOS platform capability layer (Phase 3).

Public functions delegate to iOSDevicesManager and iOSDevice for device
discovery, persistent port-forwarding, WDA lifecycle management, and session
reuse.  All asyncio.run() / ephemeral-forward logic from Phase 1 has been
removed; operations are now fully synchronous and use device.local_port directly.

Phase 1 internal helpers (_ok, _err, _wda_get, _xml_to_selectors, etc.) are
retained here because device.py imports them to avoid duplicating logic.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Unified return-value helpers
# ---------------------------------------------------------------------------

def _ok(data: dict) -> dict:
    return {"ok": True, "data": data}


def _err(kind: str, message: str, details: dict | None = None) -> dict:
    return {"ok": False, "error": {"kind": kind, "message": message, "details": details or {}}}


def _not_implemented(op: str) -> dict:
    return _err("NOT_IMPLEMENTED", f"{op} is not supported on iOS")


# ---------------------------------------------------------------------------
# WDA HTTP helpers
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Phase 3: manager import (deferred to avoid circular import at parse time)
# ---------------------------------------------------------------------------

def _get_manager():
    from .device import _manager
    return _manager


def _prepare_device(target: str):
    """
    Resolve target UDID to an iOSDevice, auto-starting WDA if needed.

    Returns (device, None) on success, or (None, error_dict) on failure.
    """
    manager = _get_manager()
    device = manager.get_device(target)
    if device is None:
        return None, _err("BAD_TARGET", f"Device not found: {target}")
    try:
        if not device.is_prepared():
            device.do_prepare()
    except Exception as exc:
        return None, _err("SUBPROCESS", str(exc))
    return device, None


# ---------------------------------------------------------------------------
# list_targets
# ---------------------------------------------------------------------------

def list_targets() -> dict:
    manager = _get_manager()
    devices = manager.list_devices()
    targets = []
    for device in devices:
        try:
            wda_installed = device.is_wda_installed()
        except Exception:
            wda_installed = False
        targets.append({
            "id": device.udid,
            "platform": "ios",
            "name": device.name,
            "state": "online" if wda_installed else "offline",
            "metadata": {
                "model": device.model,
                "os_version": device.os_version,
            },
        })
    return _ok({"targets": targets})


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------

def screenshot(target: str) -> dict:
    device, err = _prepare_device(target)
    if err:
        return err
    return device.screenshot()


# ---------------------------------------------------------------------------
# dump_ui
# ---------------------------------------------------------------------------

def _parse_bounds(elem: ET.Element) -> str:
    try:
        x = int(elem.get("x", "0"))
        y = int(elem.get("y", "0"))
        w = int(elem.get("width", "0"))
        h = int(elem.get("height", "0"))
        return f"[{x},{y}][{x + w},{y + h}]"
    except (ValueError, TypeError):
        return ""


def _xml_to_selectors(root: ET.Element) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    selectors: list[dict] = []

    for elem in root.iter():
        resource_id = elem.get("name", "")
        text = elem.get("label", "")
        content_desc = elem.get("value", "")
        cls = elem.get("type", "")
        bounds = _parse_bounds(elem)
        visible = elem.get("visible", "false").lower() == "true"
        enabled = elem.get("enabled", "false").lower() == "true"
        clickable = visible and bool(bounds)

        key = (resource_id, bounds)
        if key in seen:
            continue
        seen.add(key)

        selectors.append({
            "resourceId": resource_id,
            "text": text,
            "contentDesc": content_desc,
            "class": cls,
            "bounds": bounds,
            "clickable": clickable,
            "enabled": enabled,
            "visible": visible,
        })

        if len(selectors) >= 200:
            break

    return selectors


def dump_ui(target: str) -> dict:
    device, err = _prepare_device(target)
    if err:
        return err
    return device.dump_ui()


# ---------------------------------------------------------------------------
# tap
# ---------------------------------------------------------------------------

def tap(target: str, x: int, y: int) -> dict:
    device, err = _prepare_device(target)
    if err:
        return err
    return device.tap(x, y)


# ---------------------------------------------------------------------------
# swipe
# ---------------------------------------------------------------------------

def swipe(
    target: str,
    x1: int, y1: int,
    x2: int, y2: int,
    duration_ms: int = 250,
) -> dict:
    device, err = _prepare_device(target)
    if err:
        return err
    return device.swipe(x1, y1, x2, y2, duration_ms)


# ---------------------------------------------------------------------------
# input_text
# ---------------------------------------------------------------------------

_INPUT_TEXT_MAX_BYTES = 1024


def _validate_text(text: str) -> str | None:
    """Return an error message if text fails validation, else None."""
    if "\n" in text or "\r" in text:
        return "Text must not contain newline characters"
    if "'" in text:
        return "Text must not contain single quotes"
    if "`" in text:
        return "Text must not contain backtick characters"
    if len(text.encode("utf-8")) > _INPUT_TEXT_MAX_BYTES:
        return f"Text exceeds {_INPUT_TEXT_MAX_BYTES} bytes"
    return None


def input_text(target: str, text: str) -> dict:
    err_msg = _validate_text(text)
    if err_msg:
        return _err("BAD_TARGET", err_msg)
    device, err = _prepare_device(target)
    if err:
        return err
    return device.input_text(text)


# ---------------------------------------------------------------------------
# key_event
# ---------------------------------------------------------------------------

_W3C_KEY_MAP: dict[str, str] = {
    "ENTER":  "\uE007",
    "DEL":    "\uE017",
    "TAB":    "\uE004",
    "SPACE":  "\uE00D",
    "ESCAPE": "\uE00C",
}

_PRESS_BUTTON_MAP: dict[str, str] = {
    "HOME":  "home",
    "POWER": "power",
}

_NOT_IMPLEMENTED_KEYS = {"BACK", "MENU", "RECENTS"}


def key_event(target: str, key: str) -> dict:
    key_upper = key.upper()
    if key_upper in _NOT_IMPLEMENTED_KEYS:
        return _not_implemented(f"key_event({key})")
    device, err = _prepare_device(target)
    if err:
        return err
    return device.key_event(key)


# ---------------------------------------------------------------------------
# launch_app
# ---------------------------------------------------------------------------

def launch_app(target: str, package: str, activity: str | None = None) -> dict:
    device, err = _prepare_device(target)
    if err:
        return err
    return device.launch_app(package, activity)


# ---------------------------------------------------------------------------
# kill_app
# ---------------------------------------------------------------------------

def kill_app(target: str, package: str) -> dict:
    device, err = _prepare_device(target)
    if err:
        return err
    return device.kill_app(package)


# ---------------------------------------------------------------------------
# 6.1  switch_app_env  (stub)
# ---------------------------------------------------------------------------

def switch_app_env(target: str, env: str) -> dict:
    return _not_implemented("switch_app_env")


# ---------------------------------------------------------------------------
# 6.2  type_credential
# ---------------------------------------------------------------------------

def type_credential(
    target: str,
    env: str,
    role: str,
    field: str,
    skip_clear: bool = False,
) -> dict:
    from . import secrets  # local import to avoid circular dependency at module level

    value = secrets.get_credential(role, field)
    if value is None:
        key = secrets.credential_env_key(role, field)
        return _err("BAD_TARGET", f"credential not found: {key}")

    result = input_text(target, value)

    # Ensure the plaintext credential never leaks into the response.
    # input_text returns extra.length (the character count), which is safe.
    return result
