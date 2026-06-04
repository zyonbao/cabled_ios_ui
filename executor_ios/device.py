"""
device.py — Phase 3 multi-device manager.

Introduces iOSDevice and iOSDevicesManager, replacing the per-call ephemeral
port-forward model with a persistent background forwarding loop and session
caching.

Architecture:
  - One module-level asyncio event loop runs in a daemon thread (_bg_loop).
  - Each iOSDevice holds a persistent usbmux forward task on that loop.
  - iOSDevicesManager is a module-level singleton that owns all iOSDevice objects.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Background event loop (module-level singleton)
# ---------------------------------------------------------------------------

_bg_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
_bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True, name="ios-bg-loop")
_bg_thread.start()


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_DEFAULT_WDA_BUNDLE_ID = "com.facebook.WebDriverAgentRunner.xctrunner"
_CONFIG_PATH = Path.home() / ".executor_ios.json"

# WDA HTTP server and MJPEG broadcaster ports on the device.
_WDA_DEVICE_PORT = 8100
_WDA_MJPEG_DEVICE_PORT = 9100


def _load_config() -> dict:
    """Read ~/.executor_ios.json; return defaults for any missing field."""
    defaults = {"wda_bundle_id": _DEFAULT_WDA_BUNDLE_ID}
    try:
        with _CONFIG_PATH.open() as f:
            data = json.load(f)
        return {**defaults, **data}
    except FileNotFoundError:
        return defaults
    except Exception:
        return defaults


# ---------------------------------------------------------------------------
# Tunneld RSD query
# ---------------------------------------------------------------------------

TUNNELD_URL = "http://127.0.0.1:49151"


def _get_rsd_from_tunneld(udid: str) -> Optional[tuple[str, int]]:
    """
    Query the local tunneld HTTP API for the RSD address/port of a specific device.
    Returns (rsd_address, rsd_port) or None if tunneld is not running or device not found.
    """
    try:
        resp = requests.get(TUNNELD_URL, timeout=3.0)
        tunnels: dict[str, list[dict]] = resp.json()
        entries = tunnels.get(udid, [])
        if entries:
            return entries[0]["tunnel-address"], int(entries[0]["tunnel-port"])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Port helpers
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


# ---------------------------------------------------------------------------
# Persistent port forwarding
# ---------------------------------------------------------------------------

_RELAY_CHUNK = 65536


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(_RELAY_CHUNK)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _start_forward(udid: str, local_port: int, device_port: int = 8100) -> None:
    """
    Persistent asyncio server: forwards local_port → device:device_port via usbmux.
    Runs forever until cancelled.
    """
    from pymobiledevice3 import usbmux

    async def _handle_client(
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        try:
            mux_device = await usbmux.select_device(udid, connection_type="USB")
            if mux_device is None:
                client_writer.close()
                return
            raw_sock = await mux_device.connect(device_port)
            raw_sock.setblocking(False)
            device_reader, device_writer = await asyncio.open_connection(sock=raw_sock)
            await asyncio.gather(
                _pipe(client_reader, device_writer),
                _pipe(device_reader, client_writer),
                return_exceptions=True,
            )
        except Exception:
            pass
        finally:
            try:
                client_writer.close()
            except Exception:
                pass

    server = await asyncio.start_server(_handle_client, host="127.0.0.1", port=local_port)
    async with server:
        await server.serve_forever()


def _launch_forward(udid: str, local_port: int, device_port: int = 8100) -> "Future[None]":
    """Submit _start_forward to the background loop and return its Future."""
    return asyncio.run_coroutine_threadsafe(
        _start_forward(udid, local_port, device_port), _bg_loop
    )


# ---------------------------------------------------------------------------
# WDA session primitive (reused from Phase 1 logic)
# ---------------------------------------------------------------------------

# W3C WebDriver standard error code returned by WDA when the session id is
# unknown/expired (spec: https://w3c.github.io/webdriver/#errors). WDA returns
# it as HTTP 404 with body {"value": {"error": "invalid session id",
# "message": "Session does not exist", ...}}. The "error" code is stable across
# WDA versions; the "message" is human text and must NOT be relied upon.
_W3C_INVALID_SESSION = "invalid session id"


class _WdaHTTPError(RuntimeError):
    """A non-2xx WDA HTTP response, carrying the W3C error code and status."""

    def __init__(self, status_code: int, w3c_error: str, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.w3c_error = w3c_error


def _raise_for_wda(resp: "requests.Response") -> None:
    """Raise a _WdaHTTPError carrying the W3C error code from a WDA response."""
    detail: dict = {}
    try:
        body = resp.json()
        value = body.get("value", {})
        if isinstance(value, dict):
            detail = value
    except Exception:
        pass
    w3c_error = detail.get("error", "") or ""
    message = detail.get("message") or w3c_error or resp.text
    raise _WdaHTTPError(resp.status_code, w3c_error, message)


def _create_session_sync(local_port: int) -> str:
    """POST /session to WDA synchronously; raise RuntimeError on failure."""
    url = f"http://127.0.0.1:{local_port}/session"
    try:
        resp = requests.post(url, json={"capabilities": {"alwaysMatch": {}}}, timeout=15.0)
        data = resp.json()
        session_id = data.get("sessionId") or (data.get("value") or {}).get("sessionId")
        if not session_id:
            raise RuntimeError(f"No sessionId in WDA /session response: {data}")
        return session_id
    except requests.RequestException as exc:
        raise RuntimeError(f"WDA /session request failed: {exc}") from exc


# ---------------------------------------------------------------------------
# iOSDevice
# ---------------------------------------------------------------------------

class iOSDevice:
    """
    Represents a single USB-connected iOS physical device.

    Holds a persistent usbmux port-forward and a cached WDA session ID.
    All WDA operations are synchronous and use self.local_port directly.
    """

    def __init__(
        self,
        udid: str,
        local_port: int,
        name: str,
        model: str,
        os_version: str,
        forward_task: "Future[None]",
        wda_bundle_id: str,
        mjpeg_local_port: int = 0,
        mjpeg_forward_task: "Optional[Future[None]]" = None,
    ) -> None:
        self.udid = udid
        self.local_port = local_port
        # Local port forwarded to the device's WDA MJPEG broadcaster (9100).
        self.mjpeg_local_port = mjpeg_local_port
        self.name = name
        self.model = model
        self.os_version = os_version
        self._forward_task = forward_task
        self._mjpeg_forward_task = mjpeg_forward_task
        self._session_id: Optional[str] = None
        self._session_lock = threading.Lock()
        self._wda_bundle_id = wda_bundle_id
        # Long-lived XCUITest runner task that keeps the WDA test session alive.
        self._wda_task: Optional["Future[None]"] = None

    # ------------------------------------------------------------------
    # WDA lifecycle
    # ------------------------------------------------------------------

    def is_wda_installed(self) -> bool:
        """Check whether the WDA bundle is installed on this device."""
        future = asyncio.run_coroutine_threadsafe(
            self._check_wda_installed_async(), _bg_loop
        )
        try:
            return future.result(timeout=15)
        except Exception:
            return False

    async def _check_wda_installed_async(self) -> bool:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        try:
            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                async with InstallationProxyService(lockdown=lockdown) as iproxy:
                    apps = await iproxy.get_apps(application_type="User")
                    return self._wda_bundle_id in apps
        except Exception:
            return False

    def is_prepared(self) -> bool:
        """Return True if WDA HTTP server is responding on local_port."""
        url = f"http://127.0.0.1:{self.local_port}/status"
        try:
            resp = requests.get(url, timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def do_prepare(self) -> None:
        """
        Start WDA if it is not already running.

        WDA (WebDriverAgentRunner) is an XCUITest bundle, not a regular app, so
        it must be driven by a testmanagerd session rather than launched
        directly.  This starts the XCUITest runner as a persistent background
        task that keeps the session (and therefore WDA) alive.

        Raises RuntimeError if WDA is not installed or if RSD info is missing
        for iOS 17+ devices.  After this call returns, is_prepared() is True.
        """
        if not self.is_wda_installed():
            raise RuntimeError(
                f"WDA not installed on device {self.udid}. "
                f"Please install {self._wda_bundle_id} manually."
            )

        # If a runner is already alive and WDA responds, reuse it.
        if self.is_prepared() and self._wda_task is not None and not self._wda_task.done():
            with self._session_lock:
                self._session_id = None
            return

        major = self._ios_major_version()

        if major >= 17:
            rsd = _get_rsd_from_tunneld(self.udid)
            if rsd is None:
                raise RuntimeError(
                    f"iOS 17+ device {self.udid}: cannot get RSD info from tunneld. "
                    "Make sure ios_tunneld is running (it must run as root)."
                )
            rsd_address, rsd_port = rsd
            coro = self._run_wda_rsd_async(rsd_address, rsd_port)
            ctx = (
                f"iOS 17+ device {self.udid} (tunneld RSD: {rsd_address}:{rsd_port})"
            )
        else:
            coro = self._run_wda_lockdown_async()
            ctx = f"device {self.udid} (iOS {self.os_version})"

        # Submit the XCUITest runner; it blocks until the session ends, so we do
        # not wait for it to complete — instead poll the WDA HTTP endpoint.
        self._wda_task = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
        self._wait_for_wda(timeout=60, ctx=ctx)
        with self._session_lock:
            self._session_id = None
        # Tune the MJPEG broadcaster for smooth mirroring (best-effort).
        self.configure_mjpeg()

    async def _run_wda_lockdown_async(self) -> None:
        """Run the WDA XCUITest runner via lockdown/usbmux (iOS ≤ 16).

        Blocks until the test session ends; intended to run as a persistent
        background task so the WDA runner stays alive.
        """
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.dvt.testmanaged.xcuitest import (
            TestConfig,
            XCUITestService,
        )

        lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
        async with lockdown:
            cfg = await TestConfig.create_for(
                lockdown, runner_bundle_id=self._wda_bundle_id
            )
            await XCUITestService(lockdown).run(cfg)

    async def _run_wda_rsd_async(self, rsd_address: str, rsd_port: int) -> None:
        """Run the WDA XCUITest runner via RemoteServiceDiscovery (iOS 17+).

        Blocks until the test session ends; intended to run as a persistent
        background task so the WDA runner stays alive.
        """
        from pymobiledevice3.remote.remote_service_discovery import (
            RemoteServiceDiscoveryService,
        )
        from pymobiledevice3.services.dvt.testmanaged.xcuitest import (
            TestConfig,
            XCUITestService,
        )

        async with RemoteServiceDiscoveryService((rsd_address, rsd_port)) as rsd:
            cfg = await TestConfig.create_for(
                rsd, runner_bundle_id=self._wda_bundle_id
            )
            await XCUITestService(rsd).run(cfg)

    def _wait_for_wda(self, timeout: float = 60.0, ctx: Optional[str] = None) -> None:
        """Poll GET /status until WDA responds or timeout is reached.

        If the backing XCUITest runner task exits early (e.g. tunnel/test setup
        failure), surface its error immediately instead of waiting the full
        timeout.
        """
        ctx = ctx or f"device {self.udid}"
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.local_port}/status"
        while time.monotonic() < deadline:
            task = self._wda_task
            if task is not None and task.done():
                exc = task.exception()
                if exc is not None:
                    raise RuntimeError(
                        f"WDA XCUITest runner exited for {ctx}.\n"
                        f"Underlying error: {exc}"
                    ) from exc
                raise RuntimeError(
                    f"WDA XCUITest runner exited before becoming reachable for {ctx}"
                )
            try:
                resp = requests.get(url, timeout=2.0)
                if resp.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(1.0)
        raise RuntimeError(f"WDA failed to start within {timeout:.0f}s on {ctx}")

    def _ios_major_version(self) -> int:
        """Parse the major iOS version from os_version (e.g. '17.2.1' → 17)."""
        try:
            return int(self.os_version.split(".")[0])
        except (ValueError, IndexError):
            return 0

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _ensure_session(self) -> str:
        """Return a valid WDA session ID, creating one if necessary."""
        with self._session_lock:
            if self._session_id is not None:
                return self._session_id
            session_id = _create_session_sync(self.local_port)
            self._session_id = session_id
            return session_id

    def _invalidate_session(self) -> None:
        with self._session_lock:
            self._session_id = None

    def _is_invalid_session_error(self, resp: dict) -> bool:
        """Detect the W3C 'invalid session id' code in a 200-OK error body."""
        val = resp.get("value") or {}
        error = val.get("error", "") if isinstance(val, dict) else ""
        return error.lower() == _W3C_INVALID_SESSION

    # ------------------------------------------------------------------
    # WDA HTTP helpers (synchronous, use self.local_port)
    # ------------------------------------------------------------------

    def _get(self, path: str, timeout: float = 15.0) -> dict:
        url = f"http://127.0.0.1:{self.local_port}{path}"
        try:
            resp = requests.get(url, timeout=timeout)
            if not resp.ok:
                _raise_for_wda(resp)
            return resp.json()
        except RuntimeError:
            raise
        except requests.RequestException as exc:
            raise RuntimeError(str(exc)) from exc

    def _post(self, path: str, body: dict, timeout: float = 15.0) -> dict:
        url = f"http://127.0.0.1:{self.local_port}{path}"
        try:
            resp = requests.post(url, json=body, timeout=timeout)
            if not resp.ok:
                _raise_for_wda(resp)
            return resp.json()
        except RuntimeError:
            raise
        except requests.RequestException as exc:
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    def _is_stale_session_exc(exc: Exception) -> bool:
        """True if a WDA HTTP error is the W3C 'invalid session id' error.

        Matches on the spec-defined error *code* (value.error), not the
        human-readable message, so it is stable across WDA versions.
        """
        return isinstance(exc, _WdaHTTPError) and exc.w3c_error == _W3C_INVALID_SESSION

    def _post_with_session_retry(self, path_template: str, body: dict) -> dict:
        """
        POST to a session-scoped endpoint with automatic session rebuild on
        'invalid session id' errors.  path_template must contain '{sid}'.

        WDA reports a stale session either as a 200 body with an error value or
        as a 404 (which _post raises); both are handled here.
        """
        sid = self._ensure_session()
        try:
            resp = self._post(path_template.format(sid=sid), body)
        except RuntimeError as exc:
            if not self._is_stale_session_exc(exc):
                raise
            self._invalidate_session()
            sid = self._ensure_session()
            return self._post(path_template.format(sid=sid), body)
        if self._is_invalid_session_error(resp):
            self._invalidate_session()
            sid = self._ensure_session()
            resp = self._post(path_template.format(sid=sid), body)
        return resp

    def _get_with_session_retry(self, path_template: str, timeout: float = 15.0) -> dict:
        """
        GET a session-scoped endpoint, rebuilding the session once if WDA
        reports it as stale.  path_template must contain '{sid}'.
        """
        sid = self._ensure_session()
        try:
            return self._get(path_template.format(sid=sid), timeout=timeout)
        except RuntimeError as exc:
            if not self._is_stale_session_exc(exc):
                raise
            self._invalidate_session()
            sid = self._ensure_session()
            return self._get(path_template.format(sid=sid), timeout=timeout)

    def _pointer_gesture(self, actions: list[dict]) -> dict:
        """Send a single-finger W3C pointer gesture.

        Wraps the bare action list (pointerMove / pointerDown / pause /
        pointerUp …) in the touch-pointer envelope shared by tap, swipe and the
        App Switcher fallback.
        """
        return self._post_with_session_retry(
            "/session/{sid}/actions",
            {"actions": [{
                "type": "pointer",
                "id": "finger1",
                "parameters": {"pointerType": "touch"},
                "actions": actions,
            }]},
        )

    # ------------------------------------------------------------------
    # Platform operations
    # ------------------------------------------------------------------

    def screenshot(self) -> dict:
        from .toolkit_api import _ok, _err  # avoid circular import at module level
        try:
            resp = self._get("/screenshot")
            b64 = resp.get("value", "")
            return _ok({"mimeType": "image/png", "base64": b64})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def dump_ui(self) -> dict:
        import xml.etree.ElementTree as ET
        from .toolkit_api import _ok, _err, _xml_to_selectors

        try:
            resp = self._get("/source?format=xml")
            xml_str = resp.get("value", "")
            try:
                root = ET.fromstring(xml_str)
                selectors = _xml_to_selectors(root)
            except ET.ParseError:
                selectors = []
            return _ok({"rawMime": "application/xml", "raw": xml_str, "selectors": selectors})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def tap(self, x: int, y: int) -> dict:
        from .toolkit_api import _ok, _err

        try:
            self._pointer_gesture([
                {"type": "pointerMove", "duration": 0, "x": x, "y": y},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": 100},
                {"type": "pointerUp", "button": 0},
            ])
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"tapX": x, "tapY": y}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> dict:
        from .toolkit_api import _ok, _err

        try:
            self._pointer_gesture([
                {"type": "pointerMove", "duration": 0, "x": x1, "y": y1},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": duration_ms},
                {"type": "pointerMove", "duration": duration_ms, "x": x2, "y": y2},
                {"type": "pointerUp", "button": 0},
            ])
            return _ok({
                "exitCode": 0, "stdout": "", "stderr": "",
                "extra": {"fromX": x1, "fromY": y1, "toX": x2, "toY": y2, "durationMs": duration_ms},
            })
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def input_text(self, text: str) -> dict:
        from .toolkit_api import _ok, _err

        try:
            sid = self._ensure_session()
            used_fallback = False
            try:
                active_resp = self._get(f"/session/{sid}/element/active")
                val = active_resp.get("value") or {}
                elem_id = (val.get("ELEMENT") or
                           val.get("element-6066-11e4-a52e-4f735466cecf"))
                if elem_id:
                    self._post(
                        f"/session/{sid}/element/{elem_id}/value",
                        {"value": list(text), "text": text},
                    )
                else:
                    used_fallback = True
            except Exception:
                used_fallback = True

            if used_fallback:
                self._post_with_session_retry(
                    "/session/{sid}/actions",
                    {"actions": [{
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
                    }]},
                )
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"length": len(text)}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def send_keys(self, text: str) -> dict:
        """Type text into whatever field currently has focus on the device.

        Uses WDA's global ``/wda/keys`` (FBTypeText), which targets the focused
        element — ideal for mirroring a Mac keyboard. Accepts arbitrary
        characters (including IME-composed text); no shell is involved.
        """
        from .toolkit_api import _ok, _err

        try:
            self._post_with_session_retry(
                "/session/{sid}/wda/keys",
                {"value": list(text)},
            )
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"length": len(text)}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def key_chord(self, key: str, modifiers: list) -> dict:
        """Send a modifier-key chord (e.g. Command+C) to the focused field.

        Uses WDA's ``/wda/element/0/keyboardInput`` endpoint (WDA 5.12+, built
        with Xcode 15+), which calls XCUIElement ``typeKey:modifierFlags:`` —
        the only iOS API that honours real hardware-keyboard shortcuts such as
        ⌘A (select all) or ⇧→ (extend selection). Element id ``0`` targets the
        active application (Appium convention).
        """
        from .toolkit_api import (
            _ok, _err, _XCUI_MODIFIER_FLAGS, _XCUI_KEY_VALUE, _XCUI_KEY_NAME,
            _EDIT_KEYS, _W3C_KEY_MAP, _W3C_MODIFIER_MAP,
        )

        try:
            flags = 0
            for mod in modifiers:
                bit = _XCUI_MODIFIER_FLAGS.get(str(mod).upper())
                if bit is None:
                    return _err("BAD_TARGET", f"unknown modifier: {mod}")
                flags |= bit

            key_upper = key.upper()

            # Editing keys + modifiers need special handling: on iOS neither
            # channel applies modifiers to Backspace/Delete (typeKey is a no-op
            # for them; W3C ignores the modifier). So emulate the Mac behaviour
            # of ⌥⌫ (delete word) / ⌘⌫ (delete to line start) as a composite:
            # select in that direction with the same modifier(s) + Shift (this
            # works via the arrow keyboardInput path), then delete the selection
            # with a plain Backspace.
            if flags != 0 and key_upper in _EDIT_KEYS:
                if key_upper in ("BACKSPACE", "DEL", "DELETE"):
                    forward = key_upper in ("DEL", "DELETE")
                    sel_mods = [str(m) for m in modifiers]
                    if not any(str(m).upper() == "SHIFT" for m in sel_mods):
                        sel_mods.append("shift")
                    selected = self.key_chord("RIGHT" if forward else "LEFT", sel_mods)
                    if not selected.get("ok"):
                        return selected
                    result = self.key_event("DELETE" if forward else "BACKSPACE")
                    if result.get("ok"):
                        result.setdefault("data", {}).setdefault("extra", {})["channel"] = "select+delete"
                    return result

                # Other editing keys + modifier → W3C key chord (best effort).
                if key_upper in _W3C_KEY_MAP:
                    mod_vals = [_W3C_MODIFIER_MAP[str(m).upper()] for m in modifiers]
                    base = _W3C_KEY_MAP[key_upper]
                    actions = [{"type": "keyDown", "value": v} for v in mod_vals]
                    actions.append({"type": "keyDown", "value": base})
                    actions.append({"type": "keyUp", "value": base})
                    actions.extend({"type": "keyUp", "value": v} for v in reversed(mod_vals))
                    self._post_with_session_retry(
                        "/session/{sid}/actions",
                        {"actions": [{"type": "key", "id": "keyboard", "actions": actions}]},
                    )
                    return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"key": key, "modifiers": list(modifiers), "channel": "w3c"}})

            if flags == 0:
                # No modifiers → use the string form, which lets WDA resolve the
                # XCUIKeyboardKey constant name (the only form that works for
                # navigation/function keys like arrows on iOS).
                if key_upper in _XCUI_KEY_NAME:
                    entry: object = _XCUI_KEY_NAME[key_upper]
                elif len(key) == 1:
                    entry = key
                else:
                    return _err("BAD_TARGET", f"unsupported chord key: {key}")
            else:
                # Modifiers present → dict form. WDA's dict branch ignores name
                # resolution, so the key must be a literal value.
                if key_upper in _XCUI_KEY_VALUE:
                    base = _XCUI_KEY_VALUE[key_upper]
                elif len(key) == 1:
                    base = key
                else:
                    return _err("BAD_TARGET", f"unsupported chord key: {key}")
                entry = {"key": base, "modifierFlags": flags}

            self._post_with_session_retry(
                "/session/{sid}/wda/element/0/keyboardInput",
                {"keys": [entry]},
            )
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"key": key, "modifiers": list(modifiers), "flags": flags}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def key_event(self, key: str) -> dict:
        from .toolkit_api import (
            _ok, _err, _not_implemented,
            _W3C_KEY_MAP, _PRESS_BUTTON_MAP, _NOT_IMPLEMENTED_KEYS, _ARROW_KEYS,
        )

        key_upper = key.upper()
        if key_upper in _NOT_IMPLEMENTED_KEYS:
            return _not_implemented(f"key_event({key})")

        # Arrow keys only move the cursor via typeKey; reuse the chord path.
        if key_upper in _ARROW_KEYS:
            return self.key_chord(key, [])

        try:
            if key_upper in _PRESS_BUTTON_MAP:
                try:
                    self._post("/wda/pressButton", {"name": _PRESS_BUTTON_MAP[key_upper]})
                except _WdaHTTPError as exc:
                    # Older WDA builds lack /wda/pressButton; fall back to the
                    # dedicated home-screen endpoint when it 404s.
                    if exc.status_code == 404 and key_upper == "HOME":
                        self._post("/wda/homescreen", {})
                    else:
                        raise
                return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"key": key}})

            if key_upper in _W3C_KEY_MAP:
                key_value = _W3C_KEY_MAP[key_upper]
                self._post_with_session_retry(
                    "/session/{sid}/actions",
                    {"actions": [{
                        "type": "key",
                        "id": "keyboard",
                        "actions": [
                            {"type": "keyDown", "value": key_value},
                            {"type": "keyUp", "value": key_value},
                        ],
                    }]},
                )
                return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"key": key}})

            return _not_implemented(f"key_event({key})")
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def launch_app(self, package: str, activity: Optional[str] = None) -> dict:
        from .toolkit_api import _ok, _err

        try:
            self._post_with_session_retry(
                "/session/{sid}/wda/apps/launch",
                {"bundleId": package},
            )
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"package": package}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def kill_app(self, package: str) -> dict:
        from .toolkit_api import _ok, _err

        try:
            self._post_with_session_retry(
                "/session/{sid}/wda/apps/terminate",
                {"bundleId": package},
            )
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"package": package}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def window_size(self) -> dict:
        """Return the WDA logical window size (points), used to map UI clicks."""
        from .toolkit_api import _ok, _err

        try:
            resp = self._get_with_session_retry("/session/{sid}/window/size")
            val = resp.get("value") or {}
            width = val.get("width")
            height = val.get("height")
            if not width or not height:
                return _err("SUBPROCESS", f"invalid window size response: {resp}")
            return _ok({"width": int(width), "height": int(height)})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def _app_switcher_w3c(self, cx: float, h: int) -> None:
        """Fallback App Switcher gesture using synthetic W3C touch actions."""
        y_start = h - 2
        y_mid = int(h * 0.5)
        self._pointer_gesture([
            {"type": "pointerMove", "duration": 0, "x": int(cx), "y": y_start},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": 70},
            {"type": "pointerMove", "duration": 600, "x": int(cx), "y": y_mid},
            {"type": "pause", "duration": 1100},
            {"type": "pointerUp", "button": 0},
        ])

    def configure_mjpeg(
        self,
        framerate: int = 20,
        scaling_factor: int = 60,
        quality: int = 70,
    ) -> dict:
        """Tune WDA's MJPEG broadcaster for smooth, low-latency mirroring.

        - framerate: target frames per second (0 = max, capped at 60 by WDA)
        - scaling_factor: 1..100 (%) — downscaling shrinks JPEG size for speed
        - quality: 1..100 (%) — JPEG compression quality
        """
        from .toolkit_api import _ok, _err

        try:
            self._post_with_session_retry(
                "/session/{sid}/appium/settings",
                {"settings": {
                    "mjpegServerFramerate": int(framerate),
                    "mjpegScalingFactor": int(scaling_factor),
                    "mjpegServerScreenshotQuality": int(quality),
                }},
            )
            return _ok({"framerate": framerate, "scalingFactor": scaling_factor, "quality": quality})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def _is_app_switcher_open(self) -> bool:
        """True if the multitasking switcher is currently on screen.

        Both the Home screen and the switcher run under SpringBoard, so the
        discriminator is the app grid: the Home screen exposes
        XCUIElementTypeIcon elements, the switcher (app cards) does not.
        """
        try:
            sid = self._ensure_session()
            info = self._get(f"/session/{sid}/wda/activeAppInfo").get("value") or {}
            if info.get("bundleId") != "com.apple.springboard":
                return False
            source = self._get("/source?format=xml").get("value", "")
            return "XCUIElementTypeIcon" not in source
        except Exception:
            return False

    def app_switcher(self, max_attempts: int = 2) -> dict:
        """Open the iOS App Switcher via a bottom-edge swipe-up-and-hold.

        Short-circuits if the switcher is already open, then issues WDA's native
        press-drag gesture from the current screen and verifies the result. The
        gesture is reliable from any non-switcher state, so no Home reset is
        needed. Falls back to a synthetic-W3C swipe when the native endpoint is
        unavailable (older WDA builds).
        """
        from .toolkit_api import _ok, _err

        try:
            if self._is_app_switcher_open():
                return _ok({"exitCode": 0, "stdout": "", "stderr": "",
                            "extra": {"gesture": "app_switcher",
                                      "method": "already_open", "attempts": 0}})

            size = self.window_size()
            if not size.get("ok"):
                return size
            w = size["data"]["width"]
            h = size["data"]["height"]
            cx = w / 2.0
            from_y = float(h - 1)
            to_y = h * 0.6
            # Fast drag (~0.35s) + short end-hold, tuned on-device.
            velocity = (from_y - to_y) / 0.35

            for attempt in range(1, max_attempts + 1):
                try:
                    self._post_with_session_retry(
                        "/session/{sid}/wda/pressAndDragWithVelocity",
                        {
                            "fromX": cx, "fromY": from_y,
                            "toX": cx, "toY": to_y,
                            "pressDuration": 0.05,
                            "velocity": velocity,
                            "holdDuration": 0.6,
                        },
                    )
                except Exception:
                    self._app_switcher_w3c(cx, h)
                    return _ok({"exitCode": 0, "stdout": "", "stderr": "",
                                "extra": {"gesture": "app_switcher", "method": "w3c_fallback"}})

                time.sleep(0.8)
                if self._is_app_switcher_open():
                    return _ok({"exitCode": 0, "stdout": "", "stderr": "",
                                "extra": {"gesture": "app_switcher",
                                          "method": "pressAndDragWithVelocity",
                                          "attempts": attempt}})
                time.sleep(0.3)

            # Report unconfirmed so the caller can surface a retry hint.
            return _ok({"exitCode": 0, "stdout": "", "stderr": "",
                        "extra": {"gesture": "app_switcher",
                                  "method": "pressAndDragWithVelocity",
                                  "attempts": max_attempts, "confirmed": False}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))


# ---------------------------------------------------------------------------
# iOSDevicesManager
# ---------------------------------------------------------------------------

class iOSDevicesManager:
    """
    Singleton manager for all USB-connected iOS physical devices.

    Maintains a persistent iOSDevice entry per UDID across multiple calls.
    """

    def __init__(self) -> None:
        self._devices: dict[str, iOSDevice] = {}
        self._lock = threading.Lock()

    def _discover(self) -> None:
        """Synchronize the registry with currently connected USB devices."""
        future = asyncio.run_coroutine_threadsafe(self._discover_async(), _bg_loop)
        try:
            future.result(timeout=15)
        except Exception:
            pass

    async def _discover_async(self) -> None:
        from pymobiledevice3 import usbmux
        from pymobiledevice3.lockdown import create_using_usbmux

        config = _load_config()
        wda_bundle_id = config.get("wda_bundle_id", _DEFAULT_WDA_BUNDLE_ID)

        devices = await usbmux.list_devices()
        current_udids = {dev.serial for dev in devices if dev.is_usb}

        with self._lock:
            stale_udids = set(self._devices) - current_udids
            for udid in stale_udids:
                device = self._devices.pop(udid)
                device._forward_task.cancel()
                if device._mjpeg_forward_task is not None:
                    device._mjpeg_forward_task.cancel()
                # Tear down the WDA XCUITest session so the runner exits cleanly.
                if device._wda_task is not None:
                    device._wda_task.cancel()

            new_udids = current_udids - set(self._devices)

        for udid in new_udids:

            # Read lockdown metadata
            name = model = os_version = ""
            try:
                lockdown = await create_using_usbmux(serial=udid, autopair=False)
                async with lockdown:
                    name = getattr(lockdown, "display_name", None) or ""
                    model = getattr(lockdown, "product_type", None) or ""
                    os_version = getattr(lockdown, "product_version", None) or ""
            except Exception:
                pass

            local_port = _find_free_port()
            forward_task = _launch_forward(udid, local_port, _WDA_DEVICE_PORT)

            mjpeg_local_port = _find_free_port(local_port + 1)
            mjpeg_forward_task = _launch_forward(
                udid, mjpeg_local_port, _WDA_MJPEG_DEVICE_PORT
            )

            device = iOSDevice(
                udid=udid,
                local_port=local_port,
                name=name,
                model=model,
                os_version=os_version,
                forward_task=forward_task,
                wda_bundle_id=wda_bundle_id,
                mjpeg_local_port=mjpeg_local_port,
                mjpeg_forward_task=mjpeg_forward_task,
            )

            with self._lock:
                if udid not in self._devices:
                    self._devices[udid] = device

    def list_devices(self) -> list[iOSDevice]:
        """Trigger device discovery and return all registered devices."""
        self._discover()
        with self._lock:
            return list(self._devices.values())

    def get_device(self, udid: str) -> Optional[iOSDevice]:
        """Return the iOSDevice for the given UDID, or None if not registered."""
        with self._lock:
            device = self._devices.get(udid)
        if device is not None:
            return device
        # Try re-discovering in case the device was just connected
        self._discover()
        with self._lock:
            return self._devices.get(udid)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager = iOSDevicesManager()
