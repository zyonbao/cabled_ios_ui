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
import posixpath
import socket
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Awaitable, Callable, Optional

import requests

# ---------------------------------------------------------------------------
# Static-analysis hints for Nuitka (never executed)
# ---------------------------------------------------------------------------
# Every pymobiledevice3 dependency below is imported lazily inside functions to
# avoid circular imports and slow startup. Nuitka's static import follower can
# miss those in-function imports, so this `if False:` block (eliminated at
# runtime) lists them explicitly to guarantee they are bundled. Keep it in sync
# with the lazy imports throughout this module.
if False:  # noqa: SIM223 - Nuitka static-include hint, not runtime code
    from pymobiledevice3 import usbmux  # noqa: F401
    from pymobiledevice3.lockdown import create_using_usbmux  # noqa: F401
    from pymobiledevice3.services.installation_proxy import (  # noqa: F401
        InstallationProxyService,
    )
    from pymobiledevice3.services.afc import AfcService  # noqa: F401
    from pymobiledevice3.services.house_arrest import (  # noqa: F401
        HouseArrestService,
        VEND_CONTAINER,
        VEND_DOCUMENTS,
    )
    from pymobiledevice3.services.mobile_config import (  # noqa: F401
        MobileConfigService,
    )
    from pymobiledevice3.services.crash_reports import (  # noqa: F401
        CrashReportsManager,
    )
    from pymobiledevice3.services.syslog import SyslogService  # noqa: F401
    from pymobiledevice3.services.os_trace import OsTraceService  # noqa: F401
    from pymobiledevice3.remote.remote_service_discovery import (  # noqa: F401
        RemoteServiceDiscoveryService,
    )
    from pymobiledevice3.services.dvt.testmanaged.xcuitest import (  # noqa: F401
        TestConfig,
        XCUITestService,
    )


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
# Kept as the legacy filename on purpose so existing user config keeps loading
# after the package rename (executor_ios -> ios_toolkit).
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
# Device-path safety (AFC file management)
# ---------------------------------------------------------------------------

def _safe_remote_path(sub_path: str) -> str:
    """Normalize a user-supplied, root-relative device path.

    The returned path is always absolute and rooted at the vended app area
    ('/'). posixpath.normpath collapses any '..' segments and clamps them at
    '/', so the result can never escape the vended root regardless of input.
    """
    raw = (sub_path or "").strip().replace("\\", "/").lstrip("/")
    return posixpath.normpath("/" + raw)


# Logical user paths are rooted at the area the UI shows ('/'). The actual AFC
# device path differs by vend mode: VendDocuments still roots AFC at the app
# container, with the documents living under '/Documents' (listing the bare
# container root is denied), whereas VendContainer roots AFC at the container.
# root="media" targets the device media partition (com.apple.afc) whose logical
# root maps directly to the AFC root '/'.
_AFC_BASE = {"documents": "/Documents", "container": "/", "media": "/"}


def _afc_device_path(root: str, safe_path: str) -> str:
    """Map a root-relative logical path to the real on-device AFC path."""
    base = _AFC_BASE.get(root, "/")
    if safe_path == "/":
        return base
    return posixpath.normpath(base + safe_path)


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

    def stop_wda(self) -> dict:
        """Stop the WDA XCUITest runner and drop the cached session.

        Cancels the long-lived runner task (which ends the test session and
        terminates WDA on the device) so the device is freed when mirroring is
        no longer needed. do_prepare() will transparently restart it later.
        """
        from .toolkit_api import _ok, _err

        try:
            task = self._wda_task
            if task is not None:
                task.cancel()
            self._wda_task = None
            with self._session_lock:
                self._session_id = None
            return _ok({"stopped": True})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

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

    def long_press(self, x: int, y: int, duration_ms: int) -> dict:
        from .toolkit_api import _ok, _err

        try:
            # Press and hold in place: same primitive as tap/swipe, just a
            # longer pause with no pointerMove between down and up.
            self._pointer_gesture([
                {"type": "pointerMove", "duration": 0, "x": x, "y": y},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": duration_ms},
                {"type": "pointerUp", "button": 0},
            ])
            return _ok({
                "exitCode": 0, "stdout": "", "stderr": "",
                "extra": {"x": x, "y": y, "durationMs": duration_ms},
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

    def _active_bundle_id(self) -> Optional[str]:
        """Return the bundle id of the currently foreground app, or None."""
        try:
            sid = self._ensure_session()
            info = self._get(f"/session/{sid}/wda/activeAppInfo").get("value") or {}
            bundle = info.get("bundleId")
            return bundle if isinstance(bundle, str) and bundle else None
        except Exception:
            return None

    def _foreground_wda(self, timeout: float = 3.0) -> bool:
        """Bring the WDA runner to the foreground and wait until it is active.

        Pasteboard access on real devices only works while WDA is foreground
        (an Apple security restriction), so get/set must wrap their call with
        this. Returns True once WDA reports as the active app.
        """
        self._post_with_session_retry(
            "/session/{sid}/wda/apps/launch",
            {"bundleId": self._wda_bundle_id},
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._active_bundle_id() == self._wda_bundle_id:
                return True
            time.sleep(0.15)
        return False

    def _restore_app(self, bundle_id: Optional[str]) -> None:
        """Re-foreground the app that was active before WDA was brought up."""
        if not bundle_id or bundle_id == self._wda_bundle_id:
            return
        try:
            self._post_with_session_retry(
                "/session/{sid}/wda/apps/launch",
                {"bundleId": bundle_id},
            )
        except Exception:
            pass  # best-effort restore; never fail the pasteboard op over this

    def set_pasteboard(self, text: str) -> dict:
        """Write plaintext to the device pasteboard via WDA.

        WDA's ``/wda/setPasteboard`` expects the content Base64-encoded and a
        ``contentType`` of ``plaintext``. Apple only allows pasteboard access
        while WDA is foreground, so this momentarily activates WDA, writes, then
        restores the previously foreground app.
        """
        import base64

        from .toolkit_api import _ok, _err

        try:
            content = base64.b64encode(text.encode("utf-8")).decode("ascii")
            prev = self._active_bundle_id()
            self._foreground_wda()
            try:
                self._post_with_session_retry(
                    "/session/{sid}/wda/setPasteboard",
                    {"content": content, "contentType": "plaintext"},
                )
            finally:
                self._restore_app(prev)
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"length": len(text)}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def get_pasteboard(self) -> dict:
        """Read the device pasteboard as plaintext via WDA.

        Returns ``data = {"text": <str>, "isText": <bool>}``. ``isText`` is
        False when the pasteboard is empty or holds non-text (e.g. image)
        content that cannot be decoded as a non-empty UTF-8 string. Apple only
        allows pasteboard access while WDA is foreground, so this momentarily
        activates WDA, reads once, then restores the previously foreground app
        (the system pasteboard persists across the app switch).

        Note: iOS 16+ shows a "Allow Paste" prompt the first time WDA reads
        another app's pasteboard, and the read returns empty until the user
        taps it. This does a single read and reports empty in that case — the
        user dismisses the prompt and reads again.
        """
        import base64
        import binascii

        from .toolkit_api import _ok, _err

        try:
            prev = self._active_bundle_id()
            self._foreground_wda()
            try:
                resp = self._post_with_session_retry(
                    "/session/{sid}/wda/getPasteboard",
                    {"contentType": "plaintext"},
                )
            finally:
                self._restore_app(prev)
            b64 = resp.get("value") or ""
            text = ""
            is_text = False
            if isinstance(b64, str) and b64:
                try:
                    decoded = base64.b64decode(b64).decode("utf-8")
                except (binascii.Error, ValueError, UnicodeDecodeError):
                    decoded = ""
                if decoded:
                    text = decoded
                    is_text = True
            return _ok({"text": text, "isText": is_text})
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

    def orientation(self) -> dict:
        """Return the device's current screen orientation.

        WDA's `GET /session/{sid}/orientation` only reports the coarse
        PORTRAIT/LANDSCAPE pair, so it cannot distinguish the two landscape sides
        or upside-down. `GET /session/{sid}/rotation` exposes the full 4-way via
        its `z` angle (0/90/180/270), which we prefer and map to a stable enum
        plus the clockwise degrees needed to rotate a portrait frame upright.
        The coarse endpoint is used only as a fallback. Anything unexpected falls
        back to PORTRAIT so callers never crash on an unusual WDA build.
        """
        from .toolkit_api import _ok, _err

        # WDA/Appium rotation z convention; the z angle itself is the clockwise
        # "degrees" needed to bring a portrait frame upright.
        z_map = {
            0: "PORTRAIT",
            90: "LANDSCAPE_LEFT",
            180: "PORTRAIT_UPSIDE_DOWN",
            270: "LANDSCAPE_RIGHT",
        }
        # Fallback for the coarse /orientation string.
        normalize = {
            "PORTRAIT": ("PORTRAIT", 0),
            "UIA_DEVICE_ORIENTATION_PORTRAIT": ("PORTRAIT", 0),
            "PORTRAITUPSIDEDOWN": ("PORTRAIT_UPSIDE_DOWN", 180),
            "UPSIDE_DOWN": ("PORTRAIT_UPSIDE_DOWN", 180),
            "UIA_DEVICE_ORIENTATION_PORTRAIT_UPSIDEDOWN": ("PORTRAIT_UPSIDE_DOWN", 180),
            "LANDSCAPELEFT": ("LANDSCAPE_LEFT", 90),
            "LANDSCAPE": ("LANDSCAPE_LEFT", 90),
            "UIA_DEVICE_ORIENTATION_LANDSCAPELEFT": ("LANDSCAPE_LEFT", 90),
            "LANDSCAPERIGHT": ("LANDSCAPE_RIGHT", 270),
            "UIA_DEVICE_ORIENTATION_LANDSCAPERIGHT": ("LANDSCAPE_RIGHT", 270),
        }

        try:
            # Preferred: full 4-way from /rotation's z angle.
            try:
                resp = self._get_with_session_retry("/session/{sid}/rotation")
                val = resp.get("value") or {}
                z = (round(float(val.get("z", 0)) / 90) * 90) % 360
                if z in z_map:
                    return _ok({"orientation": z_map[z], "degrees": z})
            except Exception:
                pass  # fall back to the coarse orientation endpoint

            resp = self._get_with_session_retry("/session/{sid}/orientation")
            raw = resp.get("value")
            key = str(raw).upper().replace("-", "").replace(" ", "") if raw else ""
            orientation, degrees = normalize.get(key, ("PORTRAIT", 0))
            return _ok({"orientation": orientation, "degrees": degrees})
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

    # ------------------------------------------------------------------
    # App management (installation_proxy)
    # ------------------------------------------------------------------
    #
    # These operate over lockdown/usbmux and do NOT require WDA or an XPC
    # tunnel, so they work regardless of WDA install state or iOS version.

    def list_apps(self) -> dict:
        """List installed apps with fileSharing / sandbox-access metadata."""
        from .toolkit_api import _ok, _err

        future = asyncio.run_coroutine_threadsafe(self._list_apps_async(), _bg_loop)
        try:
            return _ok({"apps": future.result(timeout=30)})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    async def _list_apps_async(self) -> list[dict]:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
        async with lockdown:
            async with InstallationProxyService(lockdown=lockdown) as iproxy:
                raw = await iproxy.get_apps(application_type="Any")

        apps: list[dict] = []
        for bundle_id, info in raw.items():
            entitlements = info.get("Entitlements") or {}
            # Sandbox (VendContainer) access is granted to debuggable apps. The
            # ideal signal is the get-task-allow entitlement, but installation_
            # proxy returns a trimmed Entitlements dict that usually omits it.
            # A reliable fallback is SignerIdentity: present for development /
            # ad-hoc / enterprise-signed apps (whose containers are vendable)
            # and absent for App Store and system apps.
            sandbox_accessible = bool(
                entitlements.get("com.apple.security.get-task-allow", False)
            ) or ("SignerIdentity" in info)
            apps.append({
                "bundleId": bundle_id,
                "name": (info.get("CFBundleDisplayName")
                         or info.get("CFBundleName") or bundle_id),
                "appType": info.get("ApplicationType", ""),
                "fileSharing": bool(info.get("UIFileSharingEnabled", False)),
                "sandboxAccessible": sandbox_accessible,
            })
        apps.sort(key=lambda a: a["name"].lower())
        return apps

    def install_app(self, ipa_path: str) -> dict:
        """Install a local .ipa onto the device (device validates signature)."""
        from .toolkit_api import _ok, _err

        future = asyncio.run_coroutine_threadsafe(
            self._install_app_async(ipa_path), _bg_loop
        )
        try:
            future.result(timeout=300)
            return _ok({"installed": True, "path": ipa_path})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    async def _install_app_async(self, ipa_path: str) -> None:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
        async with lockdown:
            async with InstallationProxyService(lockdown=lockdown) as iproxy:
                await iproxy.install_from_local(ipa_path)

    def uninstall_app(self, bundle_id: str) -> dict:
        """Uninstall an app by bundle id."""
        from .toolkit_api import _ok, _err

        future = asyncio.run_coroutine_threadsafe(
            self._uninstall_app_async(bundle_id), _bg_loop
        )
        try:
            future.result(timeout=120)
            return _ok({"uninstalled": True, "bundleId": bundle_id})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    async def _uninstall_app_async(self, bundle_id: str) -> None:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
        async with lockdown:
            async with InstallationProxyService(lockdown=lockdown) as iproxy:
                await iproxy.uninstall(bundle_id)

    # ------------------------------------------------------------------
    # App file transfer (house_arrest + AFC)
    # ------------------------------------------------------------------
    #
    # root="documents" vends the app's Documents dir (works for any app with
    # UIFileSharingEnabled); root="container" vends the whole sandbox container
    # (only for apps carrying get-task-allow). For both, the vended area is the
    # AFC root ('/'), so all paths are normalized relative to '/'.

    async def _with_afc(
        self,
        root: str,
        bundle_id: str,
        op: "Callable[[object], Awaitable]",
    ):
        """Open an AFC session for one request and run ``op`` on it.

        Uses a short-lived connection (opened and closed per request) to avoid
        cross-request connection-state management. For root="media" the session
        is a plain ``AfcService`` over the device media partition (no app
        sandbox, no bundle_id); otherwise it is a house-arrest vended session
        for one app. Both expose the same AFC method surface, so ``op`` can await
        listdir/stat/pull/push/rm/makedirs/rename/get_file_contents uniformly.
        """
        from pymobiledevice3.lockdown import create_using_usbmux

        lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
        async with lockdown:
            if root == "media":
                from pymobiledevice3.services.afc import AfcService

                # async-with so the AfcService reader-loop task is cancelled and
                # the session closed after each request (no orphaned tasks).
                async with AfcService(lockdown) as afc:
                    return await op(afc)

            from pymobiledevice3.services.house_arrest import (
                HouseArrestService, VEND_CONTAINER, VEND_DOCUMENTS,
            )

            documents = root == "documents"
            cmd = VEND_DOCUMENTS if documents else VEND_CONTAINER
            async with HouseArrestService(lockdown, documents_only=documents) as house:
                await house.send_command(bundle_id, cmd)
                return await op(house)

    def afc_list(self, bundle_id: str, root: str, sub_path: str) -> dict:
        """List a directory inside an app's Documents or sandbox container."""
        from .toolkit_api import _ok, _err

        if root != "media" and not bundle_id:
            return _err("BAD_TARGET", "bundle_id is required")
        path = _safe_remote_path(sub_path)
        device_path = _afc_device_path(root, path)

        async def _op(house) -> list[dict]:
            names = await house.listdir(device_path)
            entries: list[dict] = []
            for name in names:
                if name in (".", ".."):
                    continue
                child = posixpath.join(device_path, name)
                is_dir, size, mtime = False, 0, ""
                try:
                    st = await house.stat(child)
                    is_dir = st.get("st_ifmt") == "S_IFDIR"
                    size = int(st.get("st_size", 0))
                    mt = st.get("st_mtime")
                    mtime = mt.isoformat() if hasattr(mt, "isoformat") else str(mt or "")
                except Exception:
                    pass  # unreadable entry: surface name with default metadata
                entries.append({"name": name, "isDir": is_dir, "size": size, "mtime": mtime})
            entries.sort(key=lambda e: (not e["isDir"], e["name"].lower()))
            return entries

        future = asyncio.run_coroutine_threadsafe(
            self._with_afc(root, bundle_id, _op), _bg_loop
        )
        try:
            return _ok({"root": root, "path": path, "entries": future.result(timeout=30)})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def afc_pull(self, bundle_id: str, root: str, remote_path: str, local_path: str) -> dict:
        """Export (download) a device file to a local path."""
        from .toolkit_api import _ok, _err

        if root != "media" and not bundle_id:
            return _err("BAD_TARGET", "bundle_id is required")
        if not local_path:
            return _err("BAD_TARGET", "local_path is required")
        rpath = _safe_remote_path(remote_path)
        device_path = _afc_device_path(root, rpath)

        async def _op(house) -> None:
            # pull reads in chunks and writes to the local destination file.
            await house.pull(device_path, local_path, progress_bar=False)

        future = asyncio.run_coroutine_threadsafe(
            self._with_afc(root, bundle_id, _op), _bg_loop
        )
        try:
            future.result(timeout=600)
            return _ok({"pulled": True, "remote": rpath, "local": local_path})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def afc_push(self, bundle_id: str, root: str, local_path: str, remote_dir: str) -> dict:
        """Import (upload) a local file or directory into a device directory."""
        import os

        from .toolkit_api import _ok, _err

        if root != "media" and not bundle_id:
            return _err("BAD_TARGET", "bundle_id is required")
        if not local_path or not os.path.exists(local_path):
            return _err("BAD_TARGET", f"local path not found: {local_path}")
        rdir = _safe_remote_path(remote_dir)
        device_dir = _afc_device_path(root, rdir)

        async def _op(house) -> None:
            # push targets the destination directory: a file is written under it
            # as dir/basename, a directory is copied recursively into it. Both
            # are chunked internally by pymobiledevice3.
            await house.push(local_path, device_dir)

        future = asyncio.run_coroutine_threadsafe(
            self._with_afc(root, bundle_id, _op), _bg_loop
        )
        try:
            future.result(timeout=600)
            return _ok({"pushed": True, "local": local_path, "remote": device_dir})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def afc_rm(self, bundle_id: str, root: str, remote_path: str) -> dict:
        """Delete a file or directory inside the vended app area."""
        from .toolkit_api import _ok, _err

        if root != "media" and not bundle_id:
            return _err("BAD_TARGET", "bundle_id is required")
        rpath = _safe_remote_path(remote_path)
        if rpath == "/":
            return _err("BAD_TARGET", "refusing to delete the vended root")
        device_path = _afc_device_path(root, rpath)

        async def _op(house) -> None:
            await house.rm(device_path, force=True)

        future = asyncio.run_coroutine_threadsafe(
            self._with_afc(root, bundle_id, _op), _bg_loop
        )
        try:
            future.result(timeout=120)
            return _ok({"removed": True, "remote": rpath})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def afc_mkdir(self, bundle_id: str, root: str, remote_dir: str) -> dict:
        """Create a directory inside the vended app area."""
        from .toolkit_api import _ok, _err

        if root != "media" and not bundle_id:
            return _err("BAD_TARGET", "bundle_id is required")
        rdir = _safe_remote_path(remote_dir)
        if rdir == "/":
            return _err("BAD_TARGET", "directory name is required")
        device_path = _afc_device_path(root, rdir)

        async def _op(house) -> None:
            await house.makedirs(device_path)

        future = asyncio.run_coroutine_threadsafe(
            self._with_afc(root, bundle_id, _op), _bg_loop
        )
        try:
            future.result(timeout=60)
            return _ok({"created": True, "remote": rdir})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def afc_rename(self, bundle_id: str, root: str, remote_path: str, new_path: str) -> dict:
        """Rename (or move) a file/directory inside the vended app area."""
        from .toolkit_api import _ok, _err

        if root != "media" and not bundle_id:
            return _err("BAD_TARGET", "bundle_id is required")
        src = _safe_remote_path(remote_path)
        dst = _safe_remote_path(new_path)
        if src == "/" or dst == "/":
            return _err("BAD_TARGET", "cannot rename the vended root")
        src_device = _afc_device_path(root, src)
        dst_device = _afc_device_path(root, dst)

        async def _op(house) -> None:
            await house.rename(src_device, dst_device)

        future = asyncio.run_coroutine_threadsafe(
            self._with_afc(root, bundle_id, _op), _bg_loop
        )
        try:
            future.result(timeout=120)
            return _ok({"renamed": True, "from": src, "to": dst})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def afc_read(
        self, bundle_id: str, root: str, remote_path: str, max_bytes: "int | None" = None
    ) -> dict:
        """Read raw bytes of a file in the vended area (e.g. for thumbnails).

        When ``max_bytes`` is set, the file size is checked first and oversized
        files are refused so a huge original is never loaded into memory.
        """
        from .toolkit_api import _ok, _err

        if root != "media" and not bundle_id:
            return _err("BAD_TARGET", "bundle_id is required")
        rpath = _safe_remote_path(remote_path)
        if rpath == "/":
            return _err("BAD_TARGET", "remote_path is required")
        device_path = _afc_device_path(root, rpath)

        async def _op(afc) -> bytes:
            st = await afc.stat(device_path)
            if st.get("st_ifmt") == "S_IFDIR":
                raise IsADirectoryError(f"{rpath} is a directory")
            size = int(st.get("st_size", 0))
            if max_bytes is not None and size > max_bytes:
                raise ValueError(f"file too large: {size} > {max_bytes} bytes")
            return await afc.get_file_contents(device_path)

        future = asyncio.run_coroutine_threadsafe(
            self._with_afc(root, bundle_id, _op), _bg_loop
        )
        try:
            data = future.result(timeout=120)
            return _ok({"remote": rpath, "size": len(data), "data": data})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def device_info(self) -> dict:
        """Return a flat dict of lockdown property values for this device.

        Reads the full public lockdown value set (no domain), which exposes the
        most detail available over USB without pairing (DeviceName, ProductType,
        ProductVersion, BuildVersion, SerialNumber, hardware/region fields, ...).
        """
        from .toolkit_api import _ok, _err

        async def _op() -> dict:
            from pymobiledevice3.lockdown import create_using_usbmux

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                return dict(await lockdown.get_value() or {})

        future = asyncio.run_coroutine_threadsafe(_op(), _bg_loop)
        try:
            raw = future.result(timeout=30)
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

        # Flatten for display: keep scalars as-is, stringify nested structures,
        # and drop raw bytes (pairing/certificate blobs are noise for a UI list).
        info: dict[str, object] = {}
        for key, value in raw.items():
            if isinstance(value, (bytes, bytearray)):
                continue
            if isinstance(value, (dict, list, tuple)):
                value = str(value)
            info[str(key)] = value
        return _ok({"udid": self.udid, "info": info})

    # ------------------------------------------------------------------
    # Configuration profiles (mobile_config / MCInstall)
    # ------------------------------------------------------------------
    #
    # These talk to the lockdown MCInstall service and do NOT require WDA or an
    # XPC tunnel. Profile installation usually still needs the user to confirm
    # in the device Settings app (system behaviour), so a successful return here
    # means "delivered for confirmation", not "fully installed".

    def list_profiles(self) -> dict:
        """List installed configuration profiles via MobileConfigService."""
        from .toolkit_api import _ok, _err

        async def _op() -> list[dict]:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                async with MobileConfigService(lockdown=lockdown) as mc:
                    raw = await mc.get_profile_list()
            return _normalize_profiles(raw)

        future = asyncio.run_coroutine_threadsafe(_op(), _bg_loop)
        try:
            return _ok({"profiles": future.result(timeout=30)})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def install_profile(self, path: str) -> dict:
        """Deliver a local .mobileconfig to the device for confirmation."""
        import os

        from .toolkit_api import _ok, _err

        if not path or not os.path.isfile(path):
            return _err("BAD_TARGET", f"file not found: {path}")

        async def _op() -> None:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService

            with open(path, "rb") as f:
                payload = f.read()
            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                async with MobileConfigService(lockdown=lockdown) as mc:
                    await mc.install_profile(payload)

        future = asyncio.run_coroutine_threadsafe(_op(), _bg_loop)
        try:
            future.result(timeout=120)
            # "delivered": the device may still require manual confirmation.
            return _ok({"delivered": True, "path": path})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def remove_profile(self, identifier: str) -> dict:
        """Remove an installed configuration profile by its identifier."""
        from .toolkit_api import _ok, _err

        if not identifier:
            return _err("BAD_TARGET", "identifier is required")

        async def _op() -> None:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                async with MobileConfigService(lockdown=lockdown) as mc:
                    await mc.remove_profile(identifier)

        future = asyncio.run_coroutine_threadsafe(_op(), _bg_loop)
        try:
            future.result(timeout=60)
            return _ok({"removed": True, "identifier": identifier})
        except Exception as exc:
            # Supervised / MDM-locked profiles refuse removal; surface as error.
            return _err("SUBPROCESS", str(exc))

    def export_profile(self, identifier: str, local_path: str) -> dict:
        """Export an installed profile's raw bytes to a local .mobileconfig.

        The raw profile bytes are carried by get_profile_list()'s
        'ProfileManifest' map (identifier -> {'Data': <bytes>, ...}); they are
        written verbatim (a signed profile stays a CMS-signed blob).
        """
        from .toolkit_api import _ok, _err

        if not identifier:
            return _err("BAD_TARGET", "identifier is required")

        async def _op() -> bytes:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                async with MobileConfigService(lockdown=lockdown) as mc:
                    raw = await mc.get_profile_list()
            manifest = (raw or {}).get("ProfileManifest") or {}
            entry = manifest.get(identifier)
            if not entry or entry.get("Data") is None:
                raise KeyError(identifier)
            return bytes(entry["Data"])

        future = asyncio.run_coroutine_threadsafe(_op(), _bg_loop)
        try:
            data = future.result(timeout=30)
        except KeyError:
            return _err("NOT_FOUND", f"profile not found on device: {identifier}")
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))
        try:
            with open(local_path, "wb") as f:
                f.write(data)
        except OSError as exc:
            return _err("SUBPROCESS", f"write failed: {exc}")
        return _ok({"exported": True, "identifier": identifier, "path": local_path})

    # ------------------------------------------------------------------
    # Crash reports (crash_reports / CrashReportsManager over AFC2)
    # ------------------------------------------------------------------
    #
    # Listing / exporting / deleting crash logs is a standard lockdown+AFC2
    # capability and needs neither WDA nor an XPC tunnel.

    async def _with_crash(self, op: "Callable[[object], Awaitable]"):
        """Open a CrashReportsManager session for one request and run ``op``."""
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.crash_reports import CrashReportsManager

        lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
        async with lockdown:
            async with CrashReportsManager(lockdown) as crash:
                return await op(crash)

    def list_crashes(self, sub_path: str = "/") -> dict:
        """List crash-report entries under ``sub_path`` (depth=1), like afc_list.

        ls("/") yields top-level items prefixed with "/", while ls of a
        sub-directory yields paths already relative to the crash root (e.g.
        "DiagnosticLogs/Audio"). Each entry exposes ``name`` (basename, for
        display) and ``path`` (the full crash-root-relative path, for navigation
        and pull/clear). stat uses the absolute form ("/" + path) to work at any
        depth.
        """
        from .toolkit_api import _ok, _err

        listing_path = (sub_path or "/").strip() or "/"

        async def _op(crash) -> list[dict]:
            names = await crash.ls(listing_path, depth=1)
            entries: list[dict] = []
            for name in names:
                full = name.lstrip("/")  # crash-root-relative, no leading slash
                is_dir, size, mtime = False, 0, ""
                try:
                    st = await crash.afc.stat("/" + full)
                    is_dir = st.get("st_ifmt") == "S_IFDIR"
                    size = int(st.get("st_size", 0))
                    mt = st.get("st_mtime")
                    mtime = mt.isoformat() if hasattr(mt, "isoformat") else str(mt or "")
                except Exception:
                    pass  # unreadable entry: surface name with default metadata
                entries.append({
                    "name": posixpath.basename(full),
                    "path": full,
                    "isDir": is_dir,
                    "size": size,
                    "mtime": mtime,
                })
            entries.sort(key=lambda e: (not e["isDir"], e["name"].lower()))
            return entries

        future = asyncio.run_coroutine_threadsafe(self._with_crash(_op), _bg_loop)
        try:
            return _ok({"entries": future.result(timeout=60)})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def pull_crash(self, remote_path: str, local_dir: str, erase: bool = False) -> dict:
        """Export one crash entry into ``local_dir``; optionally erase original.

        ``CrashReportsManager.pull`` writes ``entry`` into the ``out`` directory
        (named by its basename) and, when ``erase`` is set, removes the original
        from the device only after a successful copy.
        """
        import os

        from .toolkit_api import _ok, _err

        if not remote_path:
            return _err("BAD_TARGET", "remote_path is required")
        if not local_dir:
            return _err("BAD_TARGET", "local_dir is required")
        entry = remote_path.lstrip("/")

        async def _op(crash) -> None:
            await crash.pull(local_dir, entry=entry, erase=erase, progress_bar=False)

        future = asyncio.run_coroutine_threadsafe(self._with_crash(_op), _bg_loop)
        try:
            future.result(timeout=600)
            local_path = os.path.join(local_dir, os.path.basename(entry))
            return _ok({"pulled": True, "remote": entry,
                        "local": local_path, "erased": bool(erase)})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def clear_crash(self, remote_path: str) -> dict:
        """Delete a single crash entry from the device."""
        from .toolkit_api import _ok, _err

        if not remote_path:
            return _err("BAD_TARGET", "remote_path is required")
        entry = remote_path.lstrip("/")

        async def _op(crash) -> None:
            # Delete the specific entry directly (clear() would treat the path
            # as a directory and wipe everything under it).
            await crash.afc.rm(entry, force=True)

        future = asyncio.run_coroutine_threadsafe(self._with_crash(_op), _bg_loop)
        try:
            future.result(timeout=120)
            return _ok({"removed": True, "remote": entry})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    # ------------------------------------------------------------------
    # System log streaming (syslog / os_trace)
    # ------------------------------------------------------------------
    #
    # Streaming is long-lived, so it does not fit the one-shot request/response
    # model. open_log_stream schedules an async consumer on the shared _bg_loop
    # and pushes formatted lines into a thread-safe queue; the desktop UI drains
    # that queue from a worker thread and renders with rate limiting. Both
    # sources are lockdown services (no WDA / tunnel required).

    def open_log_stream(self, source: str) -> "LogStreamHandle":
        """Start a syslog/oslog stream; returns a handle exposing a line queue."""
        return LogStreamHandle(self.udid, source)


# ---------------------------------------------------------------------------
# Configuration-profile normalization
# ---------------------------------------------------------------------------

def _normalize_profiles(raw: dict) -> list[dict]:
    """Flatten MobileConfigService.get_profile_list() into UI-friendly rows.

    get_profile_list() returns a dict whose 'ProfileMetadata' maps each profile
    identifier to its metadata (name / type / organization / payload count).
    Field names vary by iOS version, so each is looked up defensively.
    """
    metadata = (raw or {}).get("ProfileMetadata") or {}
    profiles: list[dict] = []
    for identifier, meta in metadata.items():
        meta = meta or {}
        payloads = meta.get("PayloadContent") or meta.get("Payloads") or []
        profiles.append({
            "identifier": str(identifier),
            "name": str(meta.get("PayloadDisplayName")
                        or meta.get("Name") or identifier),
            "type": str(meta.get("PayloadType") or ""),
            "organization": str(meta.get("PayloadOrganization") or ""),
            "payloadCount": len(payloads) if isinstance(payloads, (list, tuple)) else 0,
        })
    profiles.sort(key=lambda p: p["name"].lower())
    return profiles


# ---------------------------------------------------------------------------
# Log stream handle (syslog / os_trace)
# ---------------------------------------------------------------------------

class LogStreamHandle:
    """A live system-log stream backed by a coroutine on the shared _bg_loop.

    The coroutine iterates the selected source's async generator and pushes
    formatted text lines into ``queue`` (a thread-safe queue.Queue). On error or
    natural end it pushes a sentinel ``(ERROR, message)`` / ``(EOF, None)`` tuple
    so the consumer can react. Call ``close()`` to cancel the stream and release
    the underlying lockdown connection.
    """

    LINE = "line"
    ERROR = "error"
    EOF = "eof"

    def __init__(self, udid: str, source: str) -> None:
        import queue as _queue

        self.udid = udid
        self.source = source
        self.queue: "_queue.Queue[tuple[str, object]]" = _queue.Queue(maxsize=20000)
        self._closed = False
        self._future = asyncio.run_coroutine_threadsafe(self._run(), _bg_loop)

    async def _run(self) -> None:
        try:
            from pymobiledevice3.lockdown import create_using_usbmux

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                if self.source == "oslog":
                    async for line in self._iter_oslog(lockdown):
                        self._put(self.LINE, line)
                else:
                    async for line in self._iter_syslog(lockdown):
                        self._put(self.LINE, line)
            self._put(self.EOF, None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._put(self.ERROR, str(exc))

    async def _iter_syslog(self, lockdown):
        from pymobiledevice3.services.syslog import SyslogService

        async for line in SyslogService(service_provider=lockdown).watch():
            yield line

    async def _iter_oslog(self, lockdown):
        from pymobiledevice3.services.os_trace import OsTraceService

        async for entry in OsTraceService(lockdown=lockdown).syslog():
            yield _format_oslog_entry(entry)

    def _put(self, kind: str, payload: object) -> None:
        if self._closed:
            return
        try:
            self.queue.put_nowait((kind, payload))
        except Exception:
            # Queue is full: drop the line rather than block the bg loop.
            pass

    def close(self) -> None:
        """Cancel the stream coroutine (idempotent)."""
        self._closed = True
        if self._future and not self._future.done():
            _bg_loop.call_soon_threadsafe(self._future.cancel)


def _format_oslog_entry(entry) -> str:
    """Render an os_trace SyslogEntry as a single readable line."""
    parts = []
    ts = getattr(entry, "timestamp", None)
    if ts is not None:
        parts.append(ts.isoformat() if hasattr(ts, "isoformat") else str(ts))
    pid = getattr(entry, "pid", None)
    label = getattr(entry, "label", None)
    subsystem = getattr(label, "subsystem", None) if label is not None else None
    category = getattr(label, "category", None) if label is not None else None
    level = getattr(entry, "level", None)
    image = getattr(entry, "image_name", None) or getattr(entry, "filename", None)
    tag = image or subsystem or ""
    head = []
    if pid is not None:
        head.append(f"[{pid}]")
    if level is not None:
        head.append(f"<{getattr(level, 'name', level)}>")
    if subsystem or category:
        head.append(f"{subsystem or ''}:{category or ''}")
    elif tag:
        head.append(str(tag))
    message = getattr(entry, "message", "") or ""
    parts.append(" ".join(head))
    parts.append(str(message))
    return " ".join(p for p in parts if p)


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
