"""
toolkit_api.py — iOS platform capability layer (Phase 3).

Public functions delegate to iOSDevicesManager and iOSDevice for device
discovery, persistent port-forwarding, WDA lifecycle management, and session
reuse.  All asyncio.run() / ephemeral-forward logic from Phase 1 has been
removed; operations are now fully synchronous and use device.local_port directly.

Shared helpers (_ok, _err, _xml_to_selectors, and the key-map tables) live here
because device.py imports them, keeping the envelope and key-translation logic
in one place.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unified return-value helpers
# ---------------------------------------------------------------------------

def _ok(data: dict) -> dict:
    return {"ok": True, "data": data}


def _err(
    kind: str,
    message: str,
    details: dict | None = None,
    code: str | None = None,
) -> dict:
    # Record every error in the log file for post-hoc diagnosis. Validation-style
    # errors stay at debug (file only) to keep the console clean; genuine
    # subprocess/timeout failures surface at warning.
    #
    # `kind` is the coarse category (backward-compatible); `code` is an optional
    # stable, fine-grained identifier consumers (the UI) map to localized text.
    # `message` is an English debug detail only — never a user-facing localized
    # string — and variable parts belong in `details`, not interpolated here.
    level = logging.DEBUG if kind in ("BAD_TARGET", "NOT_IMPLEMENTED") else logging.WARNING
    logger.log(level, "api error [%s/%s]: %s", kind, code or "-", message)
    error: dict = {"kind": kind, "message": message, "details": details or {}}
    if code:
        error["code"] = code
    return {"ok": False, "error": error}


def _not_implemented(op: str) -> dict:
    return _err("NOT_IMPLEMENTED", f"{op} is not supported on iOS")


# ---------------------------------------------------------------------------
# Manager import (deferred to avoid circular import at parse time)
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


def _prepare_device_basic(target: str):
    """
    Resolve target UDID to an iOSDevice WITHOUT starting WDA.

    App and file-management operations talk to lockdown services directly, so
    they neither need WDA nor an XPC tunnel. Returns (device, None) on success,
    or (None, error_dict) when the device is not found.
    """
    manager = _get_manager()
    device = manager.get_device(target)
    if device is None:
        return None, _err("BAD_TARGET", f"Device not found: {target}")
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
# prepare / window_size (used by the interactive web UI)
# ---------------------------------------------------------------------------

def prepare(target: str) -> dict:
    """Ensure WDA is running for target; returns ok once it is reachable."""
    device, err = _prepare_device(target)
    if err:
        return err
    return _ok({"prepared": True, "target": device.udid})


def stop_wda(target: str) -> dict:
    """Stop the WDA runner for target (no-op if the device is not registered).

    Used to free the device when mirroring/control is no longer needed (e.g.
    leaving the key/mouse tab). prepare() restarts WDA transparently later.
    """
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.stop_wda()


def window_size(target: str) -> dict:
    """Return the WDA logical window size (points) for coordinate mapping."""
    device, err = _prepare_device(target)
    if err:
        return err
    return device.window_size()


def orientation(target: str) -> dict:
    """Return the device's current screen orientation (enum + clockwise degrees).

    data = {"orientation": "PORTRAIT|PORTRAIT_UPSIDE_DOWN|LANDSCAPE_LEFT|"
            "LANDSCAPE_RIGHT", "degrees": 0|90|180|270}
    """
    device, err = _prepare_device(target)
    if err:
        return err
    return device.orientation()


def app_switcher(target: str) -> dict:
    """Open the iOS App Switcher (multitasking / background view)."""
    device, err = _prepare_device(target)
    if err:
        return err
    return device.app_switcher()


def configure_mjpeg(
    target: str,
    framerate: int = 20,
    scaling_factor: int = 60,
    quality: int = 70,
) -> dict:
    """Tune the WDA MJPEG broadcaster (framerate / scaling / quality)."""
    device, err = _prepare_device(target)
    if err:
        return err
    return device.configure_mjpeg(framerate, scaling_factor, quality)


_SEND_KEYS_MAX_BYTES = 4096


def send_keys(target: str, text: str) -> dict:
    """Type text into the device's currently focused field (mirrors a keyboard)."""
    if len(text.encode("utf-8")) > _SEND_KEYS_MAX_BYTES:
        return _err("BAD_TARGET", f"Text exceeds {_SEND_KEYS_MAX_BYTES} bytes")
    device, err = _prepare_device(target)
    if err:
        return err
    return device.send_keys(text)


def key_chord(target: str, key: str, modifiers: list) -> dict:
    """Send a modifier-key chord (e.g. ⌘C) to the device's focused field."""
    if not key:
        return _err("BAD_TARGET", "Chord key is required")
    device, err = _prepare_device(target)
    if err:
        return err
    return device.key_chord(key, modifiers or [])


_PASTEBOARD_MAX_BYTES = 65536


def set_pasteboard(target: str, text: str) -> dict:
    """Write plaintext to the device's pasteboard."""
    if len(text.encode("utf-8")) > _PASTEBOARD_MAX_BYTES:
        return _err("BAD_TARGET", f"Text exceeds {_PASTEBOARD_MAX_BYTES} bytes")
    device, err = _prepare_device(target)
    if err:
        return err
    return device.set_pasteboard(text)


def get_pasteboard(target: str) -> dict:
    """Read the device's pasteboard as plaintext.

    data = {"text": <str>, "isText": <bool>}; isText is False for empty or
    non-text (e.g. image) pasteboard content.
    """
    device, err = _prepare_device(target)
    if err:
        return err
    return device.get_pasteboard()


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
# long_press
# ---------------------------------------------------------------------------

def long_press(target: str, x: int, y: int, duration_ms: int = 800) -> dict:
    """Press and hold at (x, y) for duration_ms before releasing."""
    device, err = _prepare_device(target)
    if err:
        return err
    return device.long_press(x, y, duration_ms)


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
    "ENTER":     "\uE007",
    "RETURN":    "\uE007",
    "DEL":       "\uE017",
    "DELETE":    "\uE017",
    "BACKSPACE": "\uE003",
    "TAB":       "\uE004",
    "SPACE":     "\uE00D",
    "ESCAPE":    "\uE00C",
    "ESC":       "\uE00C",
}

# Arrow keys move the text cursor only through the typeKey/keyboardInput
# channel; the synthetic W3C key channel is a no-op for them on iOS. So
# key_event delegates these to key_chord (which uses that channel). Arrows are
# NOT part of the contract key vocabulary — this is a convenience extension.
_ARROW_KEYS: frozenset = frozenset({"LEFT", "RIGHT", "UP", "DOWN"})

# W3C modifier key code points, for the synthetic /actions key channel. Editing
# keys (Enter/Backspace/…) only work through this channel on iOS, so their
# modifier chords (⌥⌫ delete-word, ⌘⌫ delete-to-start) are built here.
_W3C_MODIFIER_MAP: dict[str, str] = {
    "SHIFT":   "\uE008",
    "CONTROL": "\uE009",
    "CTRL":    "\uE009",
    "ALT":     "\uE00A",
    "OPTION":  "\uE00A",
    "META":    "\uE03D",
    "COMMAND": "\uE03D",
    "CMD":     "\uE03D",
}

# Editing keys that iOS handles only via the W3C key channel (typeKey is a
# no-op for them). Their modifier chords are routed through _W3C_KEY_MAP.
_EDIT_KEYS: frozenset = frozenset({
    "ENTER", "RETURN", "BACKSPACE", "DEL", "DELETE", "TAB", "ESCAPE", "ESC", "SPACE",
})

# XCUIKeyModifierFlags bit values (used by WDA's /keyboardInput → typeKey:
# modifierFlags:). This is the only iOS API that honours real hardware-keyboard
# shortcuts (⌘A select-all, ⇧→ extend-selection, …); W3C key actions are
# ignored by iOS for modifier semantics.
_XCUI_MODIFIER_FLAGS: dict[str, int] = {
    "CAPSLOCK": 1 << 0,
    "SHIFT":    1 << 1,
    "CONTROL":  1 << 2,
    "CTRL":     1 << 2,
    "ALT":      1 << 3,
    "OPTION":   1 << 3,
    "META":     1 << 4,
    "COMMAND":  1 << 4,
    "CMD":      1 << 4,
    "FN":       1 << 5,
    "FUNCTION": 1 << 5,
}

# Named keys → their XCUIKeyboardKey constant NAME. WDA resolves these to the
# real key constant only for the *string* form of /keyboardInput (the dict form
# has a long-standing bug that ignores name resolution), so we use names for
# plain key presses (no modifiers).
_XCUI_KEY_NAME: dict[str, str] = {
    "ENTER":     "XCUIKeyboardKeyReturn",
    "RETURN":    "XCUIKeyboardKeyReturn",
    "TAB":       "XCUIKeyboardKeyTab",
    "SPACE":     "XCUIKeyboardKeySpace",
    "ESCAPE":    "XCUIKeyboardKeyEscape",
    "ESC":       "XCUIKeyboardKeyEscape",
    "BACKSPACE": "XCUIKeyboardKeyDelete",
    "DEL":       "XCUIKeyboardKeyDelete",
    "DELETE":    "XCUIKeyboardKeyForwardDelete",
    "UP":        "XCUIKeyboardKeyUpArrow",
    "DOWN":      "XCUIKeyboardKeyDownArrow",
    "LEFT":      "XCUIKeyboardKeyLeftArrow",
    "RIGHT":     "XCUIKeyboardKeyRightArrow",
    "HOME":      "XCUIKeyboardKeyHome",
    "END":       "XCUIKeyboardKeyEnd",
    "PAGEUP":    "XCUIKeyboardKeyPageUp",
    "PAGEDOWN":  "XCUIKeyboardKeyPageDown",
}

# Named keys → their XCUIKeyboardKey unicode scalar, so chords like ⇧→ or
# ⌥⌫ target real keys rather than literal characters.
_XCUI_KEY_VALUE: dict[str, str] = {
    "ENTER":     "\r",
    "RETURN":    "\r",
    "TAB":       "\t",
    "SPACE":     " ",
    "ESCAPE":    "\u001b",
    "ESC":       "\u001b",
    "BACKSPACE": "\u0008",
    "DEL":       "\u0008",
    "DELETE":    "\u0008",
    # XCUIKeyboardKey arrow constants are the literal Unicode arrow glyphs
    # (verified on-device), NOT the AppKit NSEvent function-key codes.
    "UP":        "\u2191",
    "DOWN":      "\u2193",
    "LEFT":      "\u2190",
    "RIGHT":     "\u2192",
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
# App inventory (list / install / uninstall)
# ---------------------------------------------------------------------------

def list_apps(target: str) -> dict:
    """List installed apps with fileSharing / sandbox-access metadata.

    data = {"apps": [{"bundleId", "name", "appType", "fileSharing",
            "sandboxAccessible"}, ...]}
    """
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.list_apps()


def install_app(target: str, ipa_path: str) -> dict:
    """Install a local .ipa onto the device.

    The device validates the package signature; an improperly signed .ipa is
    rejected by the device, surfaced here as an error envelope.
    """
    if not ipa_path or not ipa_path.lower().endswith(".ipa"):
        return _err("BAD_TARGET", "ipa_path must point to a .ipa file")
    import os
    if not os.path.isfile(ipa_path):
        return _err("BAD_TARGET", f"file not found: {ipa_path}")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.install_app(ipa_path)


def uninstall_app(target: str, bundle_id: str) -> dict:
    """Uninstall an app by bundle id."""
    if not bundle_id:
        return _err("BAD_TARGET", "bundle_id is required")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.uninstall_app(bundle_id)


# ---------------------------------------------------------------------------
# App file transfer (house_arrest + AFC)
# ---------------------------------------------------------------------------

def _validate_root(root: str) -> str | None:
    if root not in ("documents", "container", "media"):
        return "root must be 'documents', 'container' or 'media'"
    return None


def afc_list(target: str, bundle_id: str, root: str, sub_path: str = "/") -> dict:
    """List a directory inside an app's Documents or sandbox container.

    data = {"root", "path", "entries": [{"name","isDir","size","mtime"}, ...]}
    """
    msg = _validate_root(root)
    if msg:
        return _err("BAD_TARGET", msg)
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.afc_list(bundle_id, root, sub_path)


def afc_pull(target: str, bundle_id: str, root: str, remote_path: str, local_path: str) -> dict:
    """Export (download) a single device file to a local path."""
    msg = _validate_root(root)
    if msg:
        return _err("BAD_TARGET", msg)
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.afc_pull(bundle_id, root, remote_path, local_path)


def afc_push(target: str, bundle_id: str, root: str, local_path: str, remote_dir: str) -> dict:
    """Import (upload) a single local file into a device directory."""
    msg = _validate_root(root)
    if msg:
        return _err("BAD_TARGET", msg)
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.afc_push(bundle_id, root, local_path, remote_dir)


def afc_rm(target: str, bundle_id: str, root: str, remote_path: str) -> dict:
    """Delete a file or directory inside the vended app area."""
    msg = _validate_root(root)
    if msg:
        return _err("BAD_TARGET", msg)
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.afc_rm(bundle_id, root, remote_path)


def afc_mkdir(target: str, bundle_id: str, root: str, remote_dir: str) -> dict:
    """Create a directory inside the vended app area."""
    msg = _validate_root(root)
    if msg:
        return _err("BAD_TARGET", msg)
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.afc_mkdir(bundle_id, root, remote_dir)


def afc_rename(target: str, bundle_id: str, root: str, remote_path: str, new_path: str) -> dict:
    """Rename (or move) a file/directory inside the vended app area."""
    msg = _validate_root(root)
    if msg:
        return _err("BAD_TARGET", msg)
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.afc_rename(bundle_id, root, remote_path, new_path)


def afc_read(
    target: str, bundle_id: str, root: str, remote_path: str, max_bytes: int | None = None
) -> dict:
    """Read raw bytes of a device file (e.g. for thumbnails).

    data = {"remote", "size", "data": <bytes>}. Intended for in-process callers
    (the desktop app); not exposed via the JSON CLI since it returns raw bytes.
    """
    msg = _validate_root(root)
    if msg:
        return _err("BAD_TARGET", msg)
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.afc_read(bundle_id, root, remote_path, max_bytes)


def device_info(target: str) -> dict:
    """Return the full lockdown property set for a device (no WDA/tunnel needed)."""
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.device_info()


# ---------------------------------------------------------------------------
# Configuration profiles (mobile_config)
# ---------------------------------------------------------------------------

def list_profiles(target: str) -> dict:
    """List installed configuration profiles.

    data = {"profiles": [{"identifier","name","type","organization",
            "payloadCount"}, ...]}
    """
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.list_profiles()


def install_profile(target: str, path: str) -> dict:
    """Deliver a local .mobileconfig to the device (usually needs on-device confirm)."""
    if not path or not path.lower().endswith(".mobileconfig"):
        return _err("BAD_TARGET", "path must point to a .mobileconfig file")
    import os
    if not os.path.isfile(path):
        return _err("BAD_TARGET", f"file not found: {path}")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.install_profile(path)


def remove_profile(target: str, identifier: str) -> dict:
    """Remove an installed configuration profile by identifier."""
    if not identifier:
        return _err("BAD_TARGET", "identifier is required")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.remove_profile(identifier)


def export_profile(target: str, identifier: str, local_path: str) -> dict:
    """Export an installed profile's raw bytes to a local .mobileconfig."""
    if not identifier:
        return _err("BAD_TARGET", "identifier is required")
    if not local_path:
        return _err("BAD_TARGET", "local_path is required")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.export_profile(identifier, local_path)


# ---------------------------------------------------------------------------
# Crash reports (crash_reports)
# ---------------------------------------------------------------------------

def list_crashes(target: str, sub_path: str = "/") -> dict:
    """List crash-report entries under ``sub_path`` (depth=1; defaults to root).

    data = {"entries": [{"name","path","isDir","size","mtime"}, ...]}
    """
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.list_crashes(sub_path)


def pull_crash(target: str, remote_path: str, local_dir: str, erase: bool = False) -> dict:
    """Export one crash entry into ``local_dir``; optionally erase the original."""
    if not remote_path:
        return _err("BAD_TARGET", "remote_path is required")
    if not local_dir:
        return _err("BAD_TARGET", "local_dir is required")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.pull_crash(remote_path, local_dir, erase)


def clear_crash(target: str, remote_path: str) -> dict:
    """Delete a single crash entry from the device."""
    if not remote_path:
        return _err("BAD_TARGET", "remote_path is required")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.clear_crash(remote_path)


# ---------------------------------------------------------------------------
# Developer tooling: DDI mount + DVT instruments (process / location)
# ---------------------------------------------------------------------------

def ddi_status(target: str) -> dict:
    """Report DeveloperDiskImage mount + developer-mode status.

    data = {"mounted": bool, "developerMode": bool, "imageType": str,
            "iosMajor": int}
    """
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.ddi_status()


def ddi_wait_ready(target: str, timeout: float = 500.0) -> dict:
    """Wait until the developer (DVT) services are reachable after a mount.

    Returns ``{ok, data:{ready:true}}`` once the DVT/DTX handshake succeeds, or a
    ``TIMEOUT`` error after ``timeout`` seconds. Probes the developer-services
    path (RSD/tunnel on iOS 17+, usbmux on iOS<17), not the mounter.
    """
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.ddi_wait_ready(timeout=timeout)


def rsd_service_available(
    target: str,
    service_name: str = "com.apple.dt.testmanagerd.remote",
    timeout: float = 12.0,
) -> dict:
    """Check whether an RSD developer service is exposed by the tunnel (iOS 17+).

    Lightweight probe (RSD XPC handshake only, no DVT) for the "WDA / keyboard-
    mouse fails after a late DDI mount" symptom, where a tunnel established before
    the DDI was mounted lacks ``com.apple.dt.testmanagerd.remote``. Returns
    ``{ok, data:{available: bool}}``; ``available=False`` also covers "tunnel has
    no RSD entry for this device".
    """
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.rsd_service_available(service_name, timeout=timeout)


def ddi_mount(
    target: str,
    method: str = "auto",
    *,
    sources: "Optional[list[str]]" = None,
    legacy_dir: "Optional[str]" = None,
    modern_dir: "Optional[str]" = None,
    github_token: "Optional[str]" = None,
    github_save_dir: "Optional[str]" = None,
    image: "Optional[str]" = None,
    signature: "Optional[str]" = None,
    build_manifest: "Optional[str]" = None,
    trustcache: "Optional[str]" = None,
) -> dict:
    """Mount the DDI via ``method`` (``auto`` or ``manual``).

    Orchestrates the two halves of DDI support: ``ddi_provider`` resolves the
    image files (offline index → local → GitHub download/fallback) and
    ``iOSDevice.ddi_mount`` performs the pure device-side mount.

    - ``auto``: resolve from the configured source priority (``sources`` + dirs +
      token + save dir, all from the UI's Settings), then mount the result.
    - ``manual``: mount the caller-provided files directly (image + signature for
      iOS<17, image + build_manifest + trustcache for iOS 17+).

    ``github_token`` is never logged in clear (only a bool).
    """
    if method not in ("auto", "manual"):
        return _err("BAD_TARGET", f"unknown mount method: {method}")
    device, err = _prepare_device_basic(target)
    if err:
        return err

    from . import ddi_provider

    major = device._ios_major_version()
    family = ddi_provider.ddi_family(major)
    logger.info(
        "api ddi_mount: target=%s method=%s family=%s sources=%s has_token=%s",
        target, method, family, sources, bool(github_token),
    )

    if method == "manual":
        return device.ddi_mount(
            family,
            image=image,
            signature=signature,
            build_manifest=build_manifest,
            trustcache=trustcache,
        )

    # auto: resolve the image files from the configured sources, then mount.
    mm = ddi_provider.parse_major_minor(device.os_version or "")
    minor = mm[1] if mm else 0
    resolved = ddi_provider.resolve_ddi_image(
        major,
        minor,
        sources=sources,
        legacy_dir=legacy_dir,
        modern_dir=modern_dir,
        github_token=github_token,
        github_save_dir=github_save_dir,
    )
    if resolved is None:
        return _err(
            "SUBPROCESS",
            "No usable DDI source available (check source settings / network)",
            code="DDI_NO_SOURCE",
        )
    try:
        result = device.ddi_mount(resolved.family, **resolved.mount_kwargs())
    finally:
        resolved.cleanup()
    # Annotate the successful result with which source/target was used.
    if result.get("ok") and isinstance(result.get("data"), dict):
        result["data"]["source"] = resolved.source
        result["data"]["target"] = resolved.target
    return result


def ddi_unmount(target: str) -> dict:
    """Unmount the DeveloperDiskImage."""
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.ddi_unmount()


def list_processes(target: str) -> dict:
    """List running processes via DVT.

    data = {"processes": [{"pid","name","realAppName","isApplication",
            "startDate"}, ...]}
    """
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.list_processes()


def launch_app_dvt(target: str, bundle_id: str) -> dict:
    """Launch an app by bundle id via DVT ProcessControl; returns its pid."""
    if not bundle_id:
        return _err("BAD_TARGET", "bundle_id is required")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.launch_app_dvt(bundle_id)


def kill_process(target: str, pid: int) -> dict:
    """Terminate a process by pid via DVT ProcessControl."""
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.kill_process(pid)


def set_location(target: str, latitude: float, longitude: float) -> dict:
    """Set a simulated GPS location (iOS 17+ keeps a background session alive)."""
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.set_location(latitude, longitude)


def clear_location(target: str) -> dict:
    """Clear the simulated GPS location and restore real GPS (stops any route)."""
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.clear_location()


def play_route_gpx(
    target: str,
    path: str,
    disable_sleep: bool = False,
    timing_randomness_range: int = 0,
) -> dict:
    """Play back a GPX trajectory as a moving simulated location.

    data = {"playing": True, "source": "gpx", "points": <int>}
    """
    import os

    if not path:
        return _err("BAD_TARGET", "gpx path is required")
    if not os.path.isfile(path):
        return _err("BAD_TARGET", "GPX file not found", details={"path": path}, code="GPX_FILE_NOT_FOUND")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.play_route_gpx(path, disable_sleep, timing_randomness_range)


def play_route_manual(
    target: str, waypoints: list, speed_mps: float, tick_s: float = 1.0
) -> dict:
    """Play a self-interpolated trajectory through waypoints at a given speed.

    waypoints = [[lat, lon], ...] (>=2). data = {"playing": True,
    "source": "manual", "points": <int>}.
    """
    if not waypoints or len(waypoints) < 2:
        return _err("BAD_TARGET", "trajectory needs at least 2 waypoints")
    try:
        speed = float(speed_mps)
    except (TypeError, ValueError):
        return _err("BAD_TARGET", "speed must be a number")
    if speed <= 0:
        return _err("BAD_TARGET", "speed must be positive")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.play_route_manual(waypoints, speed, tick_s)


# ---------------------------------------------------------------------------
# System log streaming (syslog / os_trace)
# ---------------------------------------------------------------------------

def open_log_stream(
    target: str,
    source: str = "syslog",
    pid: int = -1,
    message_filter: int = 65535,
    stream_flags: int = 60,
):
    """Open a live system-log stream and return a LogStreamHandle.

    Unlike other operations this returns a handle object (not a {ok, data}
    envelope) because the stream is long-lived and consumed off the GUI thread.
    ``source`` is "syslog" (raw syslog_relay) or "oslog" (structured os_trace).
    For ``oslog``, (pid / message_filter / stream_flags) are passed to
    ``OsTraceService.syslog(...)`` (source-side filtering; -1 / 65535 / 60 are the
    library defaults meaning "all"). Intended for in-process desktop callers; not
    exposed over the JSON CLI.
    """
    if source not in ("syslog", "oslog"):
        return _err("BAD_TARGET", "source must be 'syslog' or 'oslog'")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    return device.open_log_stream(
        source, pid=pid, message_filter=message_filter, stream_flags=stream_flags,
    )


def collect_logarchive(target: str, out_path: str):
    """Collect the device's system logs into a ``.logarchive`` at ``out_path``.

    One-shot (own lockdown connection), independent of any live log stream.
    Returns the standard {ok, data|error} envelope.
    """
    if not out_path:
        return _err("BAD_TARGET", "out_path is required")
    device, err = _prepare_device_basic(target)
    if err:
        return err
    try:
        return device.collect_logarchive(out_path)
    except Exception as exc:  # surface collection failure as a readable envelope
        return _err(
            "LOG_ARCHIVE_FAILED",
            "Failed to collect logarchive",
            details={"exc": str(exc)},
            code="LOG_ARCHIVE_FAILED",
        )


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
    # Imported lazily to avoid a circular dependency at module load time.
    from . import secrets

    value = secrets.get_credential(role, field)
    if value is None:
        key = secrets.credential_env_key(role, field)
        return _err("BAD_TARGET", f"credential not found: {key}")

    result = input_text(target, value)

    # Ensure the plaintext credential never leaks into the response.
    # input_text returns extra.length (the character count), which is safe.
    return result
