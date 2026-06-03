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


async def _start_forward(udid: str, local_port: int) -> None:
    """
    Persistent asyncio server: forwards local_port → device:8100 via usbmux.
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
            raw_sock = await mux_device.connect(8100)
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


def _launch_forward(udid: str, local_port: int) -> "Future[None]":
    """Submit _start_forward to the background loop and return its Future."""
    return asyncio.run_coroutine_threadsafe(_start_forward(udid, local_port), _bg_loop)


# ---------------------------------------------------------------------------
# WDA session primitive (reused from Phase 1 logic)
# ---------------------------------------------------------------------------

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
    ) -> None:
        self.udid = udid
        self.local_port = local_port
        self.name = name
        self.model = model
        self.os_version = os_version
        self._forward_task = forward_task
        self._session_id: Optional[str] = None
        self._session_lock = threading.Lock()
        self._wda_bundle_id = wda_bundle_id

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
            async with create_using_usbmux(serial=self.udid, autopair=False) as lockdown:
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

        Raises RuntimeError if WDA is not installed or if RSD info is missing
        for iOS 17+ devices.  After this call returns, is_prepared() is True.
        """
        if not self.is_wda_installed():
            raise RuntimeError(
                f"WDA not installed on device {self.udid}. "
                "Please install WebDriverAgentRunner manually."
            )

        major = self._ios_major_version()

        if major >= 17:
            rsd = _get_rsd_from_tunneld(self.udid)
            if rsd is None:
                raise RuntimeError(
                    f"iOS 17+ device {self.udid}: cannot get RSD info from tunneld. "
                    "Make sure ios_tunneld is running (it must run as root)."
                )
            rsd_address, rsd_port = rsd
            future = asyncio.run_coroutine_threadsafe(
                self._start_wda_rsd_async(rsd_address, rsd_port), _bg_loop
            )
            try:
                future.result(timeout=30)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to connect to XPC tunnel for iOS 17+ device {self.udid} "
                    f"(tunneld RSD: {rsd_address}:{rsd_port}). "
                    f"Make sure ios_tunneld is running.\nUnderlying error: {exc}"
                ) from exc
        else:
            future = asyncio.run_coroutine_threadsafe(
                self._start_wda_lockdown_async(), _bg_loop
            )
            try:
                future.result(timeout=30)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to start WDA on device {self.udid} (iOS {self.os_version}): {exc}"
                ) from exc

        self._wait_for_wda(timeout=60)
        with self._session_lock:
            self._session_id = None

    async def _start_wda_lockdown_async(self) -> None:
        """Start WDA via lockdown/usbmux (iOS ≤ 16)."""
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import (
            DvtSecureSocketProxyService,
        )
        from pymobiledevice3.services.dvt.instruments.process_control import ProcessControl

        async with create_using_usbmux(serial=self.udid, autopair=False) as lockdown:
            async with DvtSecureSocketProxyService(lockdown=lockdown) as dvt:
                async with ProcessControl(dvt) as pc:
                    await pc.launch(
                        bundle_id=self._wda_bundle_id,
                        arguments=[],
                        environment={},
                        wait_for_debugger=False,
                        start_suspended=False,
                    )

    async def _start_wda_rsd_async(self, rsd_address: str, rsd_port: int) -> None:
        """Start WDA via RemoteServiceDiscovery (iOS 17+)."""
        from pymobiledevice3.remote.remote_service_discovery import (
            RemoteServiceDiscoveryService,
        )
        from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import (
            DvtSecureSocketProxyService,
        )
        from pymobiledevice3.services.dvt.instruments.process_control import ProcessControl

        async with RemoteServiceDiscoveryService(
            (rsd_address, rsd_port)
        ) as rsd:
            async with DvtSecureSocketProxyService(lockdown=rsd) as dvt:
                async with ProcessControl(dvt) as pc:
                    await pc.launch(
                        bundle_id=self._wda_bundle_id,
                        arguments=[],
                        environment={},
                        wait_for_debugger=False,
                        start_suspended=False,
                    )

    def _wait_for_wda(self, timeout: float = 60.0) -> None:
        """Poll GET /status until WDA responds or timeout is reached."""
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.local_port}/status"
        while time.monotonic() < deadline:
            try:
                resp = requests.get(url, timeout=2.0)
                if resp.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(1.0)
        raise RuntimeError(f"WDA failed to start within {timeout:.0f}s on {self.udid}")

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
        val = resp.get("value") or {}
        error = val.get("error", "") if isinstance(val, dict) else ""
        return "invalid session id" in error.lower()

    # ------------------------------------------------------------------
    # WDA HTTP helpers (synchronous, use self.local_port)
    # ------------------------------------------------------------------

    def _get(self, path: str, timeout: float = 15.0) -> dict:
        url = f"http://127.0.0.1:{self.local_port}{path}"
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(str(exc)) from exc

    def _post(self, path: str, body: dict, timeout: float = 15.0) -> dict:
        url = f"http://127.0.0.1:{self.local_port}{path}"
        try:
            resp = requests.post(url, json=body, timeout=timeout)
            if not resp.ok:
                try:
                    detail = resp.json().get("value", {})
                    msg = detail.get("message") or detail.get("error") or resp.text
                except Exception:
                    msg = resp.text
                raise RuntimeError(f"HTTP {resp.status_code}: {msg}")
            return resp.json()
        except RuntimeError:
            raise
        except requests.RequestException as exc:
            raise RuntimeError(str(exc)) from exc

    def _post_with_session_retry(self, path_template: str, body: dict) -> dict:
        """
        POST to a session-scoped endpoint with automatic session rebuild on
        'invalid session id' errors.  path_template must contain '{sid}'.
        """
        sid = self._ensure_session()
        resp = self._post(path_template.format(sid=sid), body)
        if self._is_invalid_session_error(resp):
            self._invalidate_session()
            sid = self._ensure_session()
            resp = self._post(path_template.format(sid=sid), body)
        return resp

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
            self._post_with_session_retry(
                "/session/{sid}/actions",
                {"actions": [{
                    "type": "pointer",
                    "id": "finger1",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {"type": "pointerMove", "duration": 0, "x": x, "y": y},
                        {"type": "pointerDown", "button": 0},
                        {"type": "pause", "duration": 100},
                        {"type": "pointerUp", "button": 0},
                    ],
                }]},
            )
            return _ok({"exitCode": 0, "stdout": "", "stderr": "", "extra": {"tapX": x, "tapY": y}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> dict:
        from .toolkit_api import _ok, _err

        try:
            self._post_with_session_retry(
                "/session/{sid}/actions",
                {"actions": [{
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
                }]},
            )
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

    def key_event(self, key: str) -> dict:
        from .toolkit_api import (
            _ok, _err, _not_implemented,
            _W3C_KEY_MAP, _PRESS_BUTTON_MAP, _NOT_IMPLEMENTED_KEYS,
        )

        key_upper = key.upper()
        if key_upper in _NOT_IMPLEMENTED_KEYS:
            return _not_implemented(f"key_event({key})")

        try:
            if key_upper in _PRESS_BUTTON_MAP:
                try:
                    self._post("/wda/pressButton", {"name": _PRESS_BUTTON_MAP[key_upper]})
                except Exception as exc:
                    if "404" in str(exc) and key_upper == "HOME":
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

            new_udids = current_udids - set(self._devices)

        for udid in new_udids:

            # Read lockdown metadata
            name = model = os_version = ""
            try:
                async with create_using_usbmux(serial=udid, autopair=False) as lockdown:
                    name = getattr(lockdown, "display_name", None) or ""
                    model = getattr(lockdown, "product_type", None) or ""
                    os_version = getattr(lockdown, "product_version", None) or ""
            except Exception:
                pass

            local_port = _find_free_port()
            forward_task = _launch_forward(udid, local_port)

            device = iOSDevice(
                udid=udid,
                local_port=local_port,
                name=name,
                model=model,
                os_version=os_version,
                forward_task=forward_task,
                wda_bundle_id=wda_bundle_id,
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
