"""
toolkit_api.py — iOS platform capability layer (Phase 1).

Each public function is stateless: it spins up an ephemeral usbmux port-forward,
performs the WDA HTTP operation, then tears everything down.  No global state is
shared across broker invocations.

pymobiledevice3 API notes (v9.x):
  - usbmux.list_devices()                        -> async, List[MuxDevice]
  - usbmux.select_device(serial, connection_type) -> async, MuxDevice | None
  - MuxDevice.connect(port)                       -> async, socket.socket
  - create_using_usbmux(serial, autopair)         -> async, LockdownClient
  - LockdownClient.product_version / .product_type / .display_name -> sync properties
"""

from __future__ import annotations

import asyncio
import socket
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from typing import AsyncIterator

import requests


# ---------------------------------------------------------------------------
# Internal exception
# ---------------------------------------------------------------------------

class WdaError(Exception):
    """Raised when a WDA HTTP request fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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

def _wda_get(local_port: int, path: str, timeout: float = 15.0) -> dict:
    """Synchronous GET — only call from a thread, never directly inside an async function."""
    url = f"http://127.0.0.1:{local_port}{path}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise WdaError(str(exc)) from exc


def _wda_post(local_port: int, path: str, body: dict, timeout: float = 15.0) -> dict:
    """Synchronous POST — only call from a thread, never directly inside an async function."""
    url = f"http://127.0.0.1:{local_port}{path}"
    try:
        resp = requests.post(url, json=body, timeout=timeout)
        if not resp.ok:
            # Include WDA response body in the error message when available
            try:
                detail = resp.json().get("value", {})
                msg = detail.get("message") or detail.get("error") or resp.text
            except Exception:
                msg = resp.text
            raise WdaError(f"HTTP {resp.status_code}: {msg}")
        return resp.json()
    except WdaError:
        raise
    except Exception as exc:
        raise WdaError(str(exc)) from exc


def _raise_if_wda_error(resp: dict) -> None:
    """
    WebDriver protocol returns HTTP 200 even for errors, with the error
    nested in resp['value']['error'].  Raise WdaError when that field is set.
    """
    val = resp.get("value")
    if isinstance(val, dict) and val.get("error"):
        msg = val.get("message") or val["error"]
        raise WdaError(f"WDA error: {val['error']} — {msg}")


async def _aget(local_port: int, path: str, timeout: float = 15.0) -> dict:
    """Async wrapper: runs _wda_get in a thread so the event loop stays free for relay."""
    resp = await asyncio.to_thread(_wda_get, local_port, path, timeout)
    _raise_if_wda_error(resp)
    return resp


async def _apost(local_port: int, path: str, body: dict, timeout: float = 15.0) -> dict:
    """Async wrapper: runs _wda_post in a thread so the event loop stays free for relay."""
    resp = await asyncio.to_thread(_wda_post, local_port, path, body, timeout)
    _raise_if_wda_error(resp)
    return resp


# ---------------------------------------------------------------------------
# Ephemeral usbmux port-forward
# ---------------------------------------------------------------------------

def _find_free_port(start: int = 8200) -> int:
    """Return the first TCP port >= start that is currently unbound."""
    for port in range(start, start + 200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found in range 8200–8400")


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


@asynccontextmanager
async def _ephemeral_forward(
    udid: str, device_port: int = 8100
) -> AsyncIterator[int]:
    """
    Async context manager: selects the USB MuxDevice by UDID, starts a local
    TCP server, and relays each client connection to device_port via usbmux.

    Raises ValueError if the UDID is not found among connected USB devices.
    """
    from pymobiledevice3 import usbmux

    mux_device = await usbmux.select_device(udid, connection_type="USB")
    if mux_device is None:
        raise ValueError(f"UDID not found among USB devices: {udid}")

    local_port = _find_free_port()

    async def _handle_client(
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        try:
            # Open a usbmux channel to device_port; returns a blocking socket
            raw_sock = await mux_device.connect(device_port)
            raw_sock.setblocking(False)
            device_reader, device_writer = await asyncio.open_connection(sock=raw_sock)
            await asyncio.gather(
                _pipe(client_reader, device_writer),
                _pipe(device_reader, client_writer),
                return_exceptions=True,
            )
        finally:
            client_writer.close()

    server = await asyncio.start_server(
        _handle_client, host="127.0.0.1", port=local_port
    )
    async with server:
        yield local_port


# ---------------------------------------------------------------------------
# WDA session creation (Phase 1: always creates fresh, no caching)
# ---------------------------------------------------------------------------

async def _create_session(local_port: int) -> str:
    """
    POST /session to WDA and return the sessionId string.
    Raises WdaError on failure.
    """
    resp = await _apost(local_port, "/session", {"capabilities": {"alwaysMatch": {}}})
    session_id = (resp.get("sessionId") or
                  (resp.get("value") or {}).get("sessionId"))
    if not session_id:
        raise WdaError(f"No sessionId in WDA /session response: {resp}")
    return session_id


# ---------------------------------------------------------------------------
# 2.1  list_targets
# ---------------------------------------------------------------------------

async def _list_targets_async() -> dict:
    from pymobiledevice3 import usbmux
    from pymobiledevice3.lockdown import create_using_usbmux

    devices = await usbmux.list_devices()
    targets = []
    for dev in devices:
        if not dev.is_usb:
            continue
        udid = dev.serial
        name = model = os_version = ""
        try:
            lockdown = await create_using_usbmux(serial=udid, autopair=False)
            name = getattr(lockdown, "display_name", None) or ""
            model = getattr(lockdown, "product_type", None) or ""
            os_version = getattr(lockdown, "product_version", None) or ""
        except Exception:
            pass
        targets.append({
            "id": udid,
            "platform": "ios",
            "name": name,
            "state": "online",
            "metadata": {
                "model": model,
                "os_version": os_version,
            },
        })
    return _ok({"targets": targets})


def list_targets() -> dict:
    return asyncio.run(_list_targets_async())


# ---------------------------------------------------------------------------
# 3.1  screenshot
# ---------------------------------------------------------------------------

async def _screenshot_async(target: str) -> dict:
    try:
        async with _ephemeral_forward(target) as local_port:
            resp = await _aget(local_port, "/screenshot")
            b64 = resp.get("value", "")
            return _ok({"mimeType": "image/png", "base64": b64})
    except ValueError:
        return _err("BAD_TARGET", f"Device not found: {target}")
    except WdaError as exc:
        return _err("SUBPROCESS", exc.message)


def screenshot(target: str) -> dict:
    return asyncio.run(_screenshot_async(target))


# ---------------------------------------------------------------------------
# 3.2  dump_ui
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


async def _dump_ui_async(target: str) -> dict:
    try:
        async with _ephemeral_forward(target) as local_port:
            resp = await _aget(local_port, "/source?format=xml")
            xml_str = resp.get("value", "")
            try:
                root = ET.fromstring(xml_str)
                selectors = _xml_to_selectors(root)
            except ET.ParseError:
                selectors = []
            return _ok({
                "rawMime": "application/xml",
                "raw": xml_str,
                "selectors": selectors,
            })
    except ValueError:
        return _err("BAD_TARGET", f"Device not found: {target}")
    except WdaError as exc:
        return _err("SUBPROCESS", exc.message)


def dump_ui(target: str) -> dict:
    return asyncio.run(_dump_ui_async(target))


# ---------------------------------------------------------------------------
# 4.1  tap
# ---------------------------------------------------------------------------

async def _tap_async(target: str, x: int, y: int) -> dict:
    try:
        async with _ephemeral_forward(target) as local_port:
            session_id = await _create_session(local_port)
            await _apost(local_port, f"/session/{session_id}/actions", {
                "actions": [{
                    "type": "pointer",
                    "id": "finger1",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {"type": "pointerMove", "duration": 0, "x": x, "y": y},
                        {"type": "pointerDown", "button": 0},
                        {"type": "pause", "duration": 100},
                        {"type": "pointerUp", "button": 0},
                    ],
                }]
            })
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"tapX": x, "tapY": y}})
    except ValueError:
        return _err("BAD_TARGET", f"Device not found: {target}")
    except WdaError as exc:
        return _err("SUBPROCESS", exc.message)


def tap(target: str, x: int, y: int) -> dict:
    return asyncio.run(_tap_async(target, x, y))


# ---------------------------------------------------------------------------
# 4.2  swipe
# ---------------------------------------------------------------------------

async def _swipe_async(
    target: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int
) -> dict:
    try:
        async with _ephemeral_forward(target) as local_port:
            session_id = await _create_session(local_port)
            await _apost(local_port, f"/session/{session_id}/actions", {
                "actions": [{
                    "type": "pointer",
                    "id": "finger1",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {"type": "pointerMove", "duration": 0, "x": x1, "y": y1},
                        {"type": "pointerDown", "button": 0},
                        {"type": "pause", "duration": duration_ms},
                        {"type": "pointerMove", "duration": duration_ms, "x": x2, "y": y2},
                        {"type": "pointerUp", "button": 0},
                    ],
                }]
            })
            return _ok({
                "exitCode": 0, "stdout": "", "stderr": "",
                "extra": {"fromX": x1, "fromY": y1, "toX": x2, "toY": y2, "durationMs": duration_ms},
            })
    except ValueError:
        return _err("BAD_TARGET", f"Device not found: {target}")
    except WdaError as exc:
        return _err("SUBPROCESS", exc.message)


def swipe(
    target: str,
    x1: int, y1: int,
    x2: int, y2: int,
    duration_ms: int = 250,
) -> dict:
    return asyncio.run(_swipe_async(target, x1, y1, x2, y2, duration_ms))


# ---------------------------------------------------------------------------
# 4.3  input_text
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


async def _input_text_async(target: str, text: str) -> dict:
    err_msg = _validate_text(text)
    if err_msg:
        return _err("BAD_TARGET", err_msg)

    try:
        async with _ephemeral_forward(target) as local_port:
            session_id = await _create_session(local_port)

            # Primary path: active element value API
            used_fallback = False
            try:
                active_resp = await _aget(local_port, f"/session/{session_id}/element/active")
                val = active_resp.get("value") or {}
                elem_id = (val.get("ELEMENT") or
                           val.get("element-6066-11e4-a52e-4f735466cecf"))
                if elem_id:
                    await _apost(
                        local_port,
                        f"/session/{session_id}/element/{elem_id}/value",
                        {"value": list(text), "text": text},
                    )
                else:
                    used_fallback = True
            except WdaError:
                used_fallback = True

            # Fallback: W3C key actions character by character
            if used_fallback:
                await _apost(local_port, f"/session/{session_id}/actions", {
                    "actions": [{
                        "type": "key",
                        "id": "keyboard",
                        "actions": [
                            item
                            for ch in text
                            for item in (
                                {"type": "keyDown", "value": ch},
                                {"type": "keyUp", "value": ch},
                            )
                        ],
                    }]
                })

            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"length": len(text)}})
    except ValueError:
        return _err("BAD_TARGET", f"Device not found: {target}")
    except WdaError as exc:
        return _err("SUBPROCESS", exc.message)


def input_text(target: str, text: str) -> dict:
    return asyncio.run(_input_text_async(target, text))


# ---------------------------------------------------------------------------
# 4.4  key_event
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


async def _key_event_async(target: str, key: str) -> dict:
    key_upper = key.upper()

    if key_upper in _NOT_IMPLEMENTED_KEYS:
        return _not_implemented(f"key_event({key})")

    # HOME / POWER — try /wda/pressButton first; fall back to /wda/homescreen for HOME
    if key_upper in _PRESS_BUTTON_MAP:
        try:
            async with _ephemeral_forward(target) as local_port:
                try:
                    await _apost(local_port, "/wda/pressButton",
                                 {"name": _PRESS_BUTTON_MAP[key_upper]})
                except WdaError as exc:
                    if "404" in exc.message and key_upper == "HOME":
                        # fallback: some WDA builds expose /wda/homescreen instead
                        await _apost(local_port, "/wda/homescreen", {})
                    else:
                        raise
                return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"key": key}})
        except ValueError:
            return _err("BAD_TARGET", f"Device not found: {target}")
        except WdaError as exc:
            return _err("SUBPROCESS", exc.message)

    # W3C key events (ENTER, DEL, TAB, SPACE, ESCAPE)
    if key_upper in _W3C_KEY_MAP:
        key_value = _W3C_KEY_MAP[key_upper]
        try:
            async with _ephemeral_forward(target) as local_port:
                session_id = await _create_session(local_port)
                await _apost(local_port, f"/session/{session_id}/actions", {
                    "actions": [{
                        "type": "key",
                        "id": "keyboard",
                        "actions": [
                            {"type": "keyDown", "value": key_value},
                            {"type": "keyUp", "value": key_value},
                        ],
                    }]
                })
                return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"key": key}})
        except ValueError:
            return _err("BAD_TARGET", f"Device not found: {target}")
        except WdaError as exc:
            return _err("SUBPROCESS", exc.message)

    return _not_implemented(f"key_event({key})")


def key_event(target: str, key: str) -> dict:
    return asyncio.run(_key_event_async(target, key))


# ---------------------------------------------------------------------------
# 5.1  launch_app
# ---------------------------------------------------------------------------

async def _launch_app_async(target: str, package: str) -> dict:
    try:
        async with _ephemeral_forward(target) as local_port:
            session_id = await _create_session(local_port)
            await _apost(local_port, f"/session/{session_id}/wda/apps/launch",
                         {"bundleId": package})
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"package": package}})
    except ValueError:
        return _err("BAD_TARGET", f"Device not found: {target}")
    except WdaError as exc:
        return _err("SUBPROCESS", exc.message)
    except Exception as exc:
        return _err("SUBPROCESS", str(exc))


def launch_app(target: str, package: str, activity: str | None = None) -> dict:
    return asyncio.run(_launch_app_async(target, package))


# ---------------------------------------------------------------------------
# 5.2  kill_app
# ---------------------------------------------------------------------------

async def _kill_app_async(target: str, package: str) -> dict:
    try:
        async with _ephemeral_forward(target) as local_port:
            session_id = await _create_session(local_port)
            await _apost(local_port, f"/session/{session_id}/wda/apps/terminate",
                         {"bundleId": package})
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"package": package}})
    except ValueError:
        return _err("BAD_TARGET", f"Device not found: {target}")
    except WdaError as exc:
        return _err("SUBPROCESS", exc.message)
    except Exception as exc:
        return _err("SUBPROCESS", str(exc))


def kill_app(target: str, package: str) -> dict:
    return asyncio.run(_kill_app_async(target, package))


# ---------------------------------------------------------------------------
# 6.1  switch_app_env  (stub)
# ---------------------------------------------------------------------------

def switch_app_env(target: str, env: str) -> dict:
    return _not_implemented("switch_app_env")


# ---------------------------------------------------------------------------
# 6.2  type_credential  (stub)
# ---------------------------------------------------------------------------

def type_credential(
    target: str,
    env: str,
    role: str,
    field: str,
    skip_clear: bool = False,
) -> dict:
    return _not_implemented("type_credential")
