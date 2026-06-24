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
import contextlib
import json
import logging
from collections import deque
import math
import os
import posixpath
import random
import socket
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Awaitable, Callable, Optional

import requests
from keymouse_runtime_config import (
    DEFAULT_WDA_BUNDLE_ID,
    DEFAULT_WDA_MJPEG_PORT,
    DEFAULT_WDA_PORT,
    WDA_BUNDLE_ID_ENV,
    WDA_MJPEG_PORT_ENV,
    WDA_PORT_ENV,
    normalize_wda_bundle_id,
    normalize_wda_mjpeg_port,
    normalize_wda_port,
)

logger = logging.getLogger(__name__)

# Keep host pairing records inside the app's own data dir instead of
# pymobiledevice3's shared default (~/.pymobiledevice3). That default is often
# polluted with root-owned files from earlier ``sudo`` runs, which makes
# save_pair_record() fail with PermissionError. usbmuxd remains the
# authoritative store (validate_pairing reads it first), so this only relocates
# pmd3's local cache copy.
_PAIRING_RECORDS_DIR = os.path.expanduser("~/Library/CablediOS/PairingRecords")

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
    from pymobiledevice3.services.diagnostics import (  # noqa: F401
        DiagnosticsService,
    )
    from pymobiledevice3.exceptions import DeprecationError  # noqa: F401
    from pymobiledevice3.remote.remote_service_discovery import (  # noqa: F401
        RemoteServiceDiscoveryService,
    )
    from pymobiledevice3.services.dvt.testmanaged.xcuitest import (  # noqa: F401
        TestConfig,
        XCUITestService,
    )
    from pymobiledevice3.services.mobile_image_mounter import (  # noqa: F401
        DeveloperDiskImageMounter,
        MobileImageMounterService,
        PersonalizedImageMounter,
    )
    from pymobiledevice3.dtx_service_provider import (  # noqa: F401
        DtxServiceProvider,
    )
    from pymobiledevice3.services.dvt.instruments.dvt_provider import (  # noqa: F401
        DvtProvider,
    )
    from pymobiledevice3.services.dvt.instruments.device_info import (  # noqa: F401
        DeviceInfo,
    )
    from pymobiledevice3.services.dvt.instruments.process_control import (  # noqa: F401
        ProcessControl,
    )
    from pymobiledevice3.services.dvt.instruments.location_simulation import (  # noqa: F401
        LocationSimulation,
    )
    from pymobiledevice3.services.dvt.instruments.sysmontap import (  # noqa: F401
        Sysmontap,
    )
    from pymobiledevice3.services.dvt.instruments.condition_inducer import (  # noqa: F401
        ConditionInducer,
    )
    from pymobiledevice3.services.dvt.instruments.network_monitor import (  # noqa: F401
        NetworkMonitor,
    )
    from pymobiledevice3.services.webinspector import (  # noqa: F401
        WebinspectorService,
    )
    from pymobiledevice3.services.pcapd import PcapdService  # noqa: F401
    from pymobiledevice3.services.web_protocol.cdp_server import app as _cdp_app  # noqa: F401
    from pymobiledevice3.services.simulate_location import (  # noqa: F401
        DtSimulateLocation,
    )
    import gpxpy  # noqa: F401


# ---------------------------------------------------------------------------
# Background event loop (module-level singleton)
# ---------------------------------------------------------------------------

_bg_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
_bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True, name="ios-bg-loop")
_bg_thread.start()


def _run_isolated(coro: "Awaitable", timeout: "Optional[float]" = None):
    """Run a self-contained coroutine on a private event loop in the caller's thread.

    The shared _bg_loop multiplexes long-lived work (WDA mirror, syslog, the
    location session). Operations that may block for a long time and own their
    own device connection — notably DDI mount/unmount/status, whose image
    download (synchronous requests.get) and upload can take many seconds — would
    freeze every other device op if scheduled onto _bg_loop. Running them on a
    private loop (callers are AsyncRunner worker threads with no running loop)
    isolates that blocking from the shared loop.

    A ``timeout`` (seconds) bounds the operation so a stuck device service can
    never hang the caller indefinitely; it raises ``asyncio.TimeoutError``.
    """
    if timeout is not None:
        coro = asyncio.wait_for(coro, timeout)
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Virtual-location route helpers (module-level, pure functions)
# ---------------------------------------------------------------------------
#
# A "route" is a list of (latitude, longitude, delay_before_set_seconds) steps
# driven uniformly by iOSDevice._drive_route. The first step always carries a
# zero delay so playback begins immediately; subsequent delays pace the motion.

# Earth mean radius in metres (used for haversine distance).
_EARTH_RADIUS_M = 6371000.0

# Hard cap on generated steps to bound memory / runtime for pathological input.
_MAX_ROUTE_STEPS = 200000


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in metres."""
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _interpolate_route(
    waypoints: "list", speed_mps: float, tick_s: float
) -> "list":
    """Build evenly-timed steps that walk through ``waypoints`` at ``speed_mps``.

    Between each consecutive pair of waypoints the segment is split into ticks of
    ``tick_s`` seconds; intermediate coordinates are linearly interpolated (good
    enough for short simulation hops). Each generated step (except the very
    first) carries ``tick_s`` as its delay so the caller paces motion at the
    requested speed. Raises ``ValueError`` on invalid input.
    """
    pts = [(float(la), float(lo)) for la, lo in waypoints]
    if len(pts) < 2:
        raise ValueError("trajectory needs at least 2 waypoints")
    if speed_mps <= 0:
        raise ValueError("speed must be positive")
    if tick_s <= 0:
        raise ValueError("tick interval must be positive")
    for la, lo in pts:
        if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
            raise ValueError("waypoint latitude/longitude out of range")

    step_dist = speed_mps * tick_s  # metres advanced per tick
    steps: list = [(pts[0][0], pts[0][1], 0.0)]
    for (lat1, lon1), (lat2, lon2) in zip(pts, pts[1:]):
        seg = _haversine_m(lat1, lon1, lat2, lon2)
        n = max(1, int(math.ceil(seg / step_dist))) if seg > 0 else 1
        for i in range(1, n + 1):
            frac = i / n
            lat = lat1 + (lat2 - lat1) * frac
            lon = lon1 + (lon2 - lon1) * frac
            steps.append((lat, lon, tick_s))
            if len(steps) >= _MAX_ROUTE_STEPS:
                return steps
    return steps


class _GpxNoTrackpointsError(ValueError):
    """A parsed GPX file contained no usable track/route/waypoint points."""


_GPX_IGNORE_MODES = ("interval", "speed")


def _parse_gpx_steps(
    path: str,
    ignore_timestamps: bool = False,
    timing_randomness_range: int = 0,
    ignore_mode: str = "interval",
    interval_s: float = 1.0,
    speed_mps: float = 5.0,
    default_interval_s: float = 1.0,
) -> "list":
    """Parse a GPX file into route steps ``[(lat, lon, delay), ...]``.

    The first point always carries a zero delay. Each subsequent point's delay
    is derived per the playback timing mode:

    - ``ignore_timestamps`` false (reproduce recorded timing): timestamped
      points use the inter-point time difference (negative clamped to 0), and
      ``timing_randomness_range`` (milliseconds) jitters each delay by ``±N ms``
      (never below 0); points without timestamps fall back to
      ``default_interval_s``.
    - ``ignore_timestamps`` true: timestamps are not used and no jitter is
      applied. ``ignore_mode`` selects the cadence — ``"interval"`` waits a
      fixed ``interval_s`` per point; ``"speed"`` waits the haversine distance
      between consecutive points divided by ``speed_mps``.

    Raises ``_GpxNoTrackpointsError`` if the file yields no usable points, and
    ``ValueError`` on invalid timing parameters.
    """
    import gpxpy

    # Validate timing parameters before parsing so bad input fails fast.
    if ignore_timestamps:
        if ignore_mode not in _GPX_IGNORE_MODES:
            raise ValueError(f"invalid ignore_mode: {ignore_mode}")
        if ignore_mode == "speed" and speed_mps <= 0:
            raise ValueError("speed must be positive")
        if ignore_mode == "interval" and interval_s < 0:
            raise ValueError("interval must be non-negative")

    with open(path) as f:
        gpx = gpxpy.parse(f)

    # Collect (lat, lon, time) across tracks, then routes, then waypoints.
    raw: list = []
    for track in gpx.tracks:
        for segment in track.segments:
            for p in segment.points:
                raw.append((p.latitude, p.longitude, p.time))
    if not raw:
        for route in gpx.routes:
            for p in route.points:
                raw.append((p.latitude, p.longitude, p.time))
    if not raw:
        for p in gpx.waypoints:
            raw.append((p.latitude, p.longitude, p.time))
    if not raw:
        raise _GpxNoTrackpointsError("GPX file has no usable track points")

    steps: list = []
    last_time = None
    prev_lat = None
    prev_lon = None
    for idx, (lat, lon, t) in enumerate(raw):
        if idx == 0:
            delay = 0.0
        elif ignore_timestamps:
            if ignore_mode == "speed":
                # speed_mps > 0 is guaranteed by validation above.
                dist = _haversine_m(prev_lat, prev_lon, lat, lon)
                delay = dist / speed_mps
            else:
                delay = interval_s
        elif t is not None and last_time is not None:
            delay = (t - last_time).total_seconds()
            if delay < 0:
                delay = 0.0
            if timing_randomness_range:
                delay += random.randint(
                    -timing_randomness_range, timing_randomness_range
                ) / 1000.0
                delay = max(0.0, delay)
        else:
            delay = default_interval_s
        last_time = t
        prev_lat, prev_lon = lat, lon
        steps.append((float(lat), float(lon), float(delay)))
        if len(steps) >= _MAX_ROUTE_STEPS:
            break
    return steps


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

# Kept as the legacy filename on purpose so existing user config keeps loading
# after the package rename (executor_ios -> ios_toolkit).
_CONFIG_PATH = Path.home() / ".executor_ios.json"


def _load_config() -> dict:
    """Read ~/.executor_ios.json; return defaults for any missing field."""
    defaults = {
        "wda_bundle_id": DEFAULT_WDA_BUNDLE_ID,
        "wda_port": DEFAULT_WDA_PORT,
        "wda_mjpeg_port": DEFAULT_WDA_MJPEG_PORT,
    }
    try:
        with _CONFIG_PATH.open() as f:
            data = json.load(f)
        config = {**defaults, **data}
    except FileNotFoundError:
        config = defaults
    except Exception:
        config = defaults

    config["wda_bundle_id"] = normalize_wda_bundle_id(
        os.environ.get(WDA_BUNDLE_ID_ENV, config.get("wda_bundle_id", DEFAULT_WDA_BUNDLE_ID))
    )
    config["wda_port"] = normalize_wda_port(
        os.environ.get(WDA_PORT_ENV, config.get("wda_port", DEFAULT_WDA_PORT))
    )
    config["wda_mjpeg_port"] = normalize_wda_mjpeg_port(
        os.environ.get(WDA_MJPEG_PORT_ENV, config.get("wda_mjpeg_port", DEFAULT_WDA_MJPEG_PORT))
    )

    return config


# ---------------------------------------------------------------------------
# Tunneld RSD query
# ---------------------------------------------------------------------------

# Loopback host is fixed (the daemon must never be reachable off-box); the port
# is configurable from the desktop UI and bridged in via this environment
# variable (see slide6_ui.common.tunnel.apply_tunnel_env). Falls back to the
# historical default when unset or malformed.
TUNNELD_HOST = "127.0.0.1"
TUNNELD_DEFAULT_PORT = 49151
TUNNELD_PORT_ENV = "IOS_TUNNELD_PORT"


def _tunneld_port() -> int:
    """Resolve the tunneld port from the environment, with a safe fallback."""
    raw = os.environ.get(TUNNELD_PORT_ENV, "")
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return TUNNELD_DEFAULT_PORT
    return port if 1 <= port <= 65535 else TUNNELD_DEFAULT_PORT


def _tunneld_url() -> str:
    """Base URL of the local tunneld HTTP API for the configured port."""
    return f"http://{TUNNELD_HOST}:{_tunneld_port()}"


def _get_rsd_from_tunneld(udid: str) -> Optional[tuple[str, int]]:
    """
    Query the local tunneld HTTP API for the RSD address/port of a specific device.
    Returns (rsd_address, rsd_port) or None if tunneld is not running or device not found.
    """
    try:
        resp = requests.get(_tunneld_url(), timeout=3.0)
        tunnels: dict[str, list[dict]] = resp.json()
        entries = tunnels.get(udid, [])
        if entries:
            return entries[0]["tunnel-address"], int(entries[0]["tunnel-port"])
        logger.debug("tunneld has no RSD entry for udid=%s", udid)
    except Exception as exc:
        logger.debug("tunneld query failed for udid=%s: %s", udid, exc)
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


class _TunnelRequiredError(RuntimeError):
    """An iOS 17+ DVT/RSD operation needs the XPC tunnel, but it is not up.

    Carries no localized text: it only marks the failure category so the error
    boundary can attach the stable ``TUNNEL_REQUIRED`` code (the UI localizes).
    """


# English-only debug detail; the user-facing text is localized in the UI by code.
_TUNNEL_REQUIRED_MSG = (
    "XPC tunnel is required for this iOS 17+ operation; "
    "start ios_tunneld (root) and retry"
)


def _dvt_exc_to_err(exc: Exception) -> dict:
    """Map a DVT/RSD operation exception to an error envelope with a stable code.

    Keeps the per-op error handling uniform: a missing XPC tunnel becomes the
    stable ``TUNNEL_REQUIRED`` code, everything else stays a generic SUBPROCESS
    with the exception text as English debug detail.
    """
    from .toolkit_api import _err

    if isinstance(exc, _TunnelRequiredError):
        return _err("SUBPROCESS", str(exc), code="TUNNEL_REQUIRED")
    return _err("SUBPROCESS", str(exc))


def _diag_exc_to_err(exc: Exception) -> dict:
    """Map a DiagnosticsService exception to an error envelope with a stable code.

    Adds DiagnosticsService-specific mapping on top of the DVT mapping: a missing
    XPC tunnel becomes ``TUNNEL_REQUIRED`` and a MobileGestalt ``DeprecationError``
    (iOS >= 17.4) becomes ``MOBILEGESTALT_DEPRECATED``; everything else stays a
    generic SUBPROCESS with the exception text as English debug detail.
    """
    from pymobiledevice3.exceptions import DeprecationError

    from .toolkit_api import _err

    if isinstance(exc, _TunnelRequiredError):
        return _err("SUBPROCESS", str(exc), code="TUNNEL_REQUIRED")
    if isinstance(exc, DeprecationError):
        return _err("SUBPROCESS", str(exc), code="MOBILEGESTALT_DEPRECATED")
    return _err("SUBPROCESS", str(exc))


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
        # iOS 17+ virtual-location simulation only stays active while its DTX
        # connection is open, so it is kept alive by a long-lived background task.
        self._location_task: Optional["Future[None]"] = None
        self._location_lock = threading.Lock()
        # Live route playback progress (polled by the UI). Guarded by
        # _location_lock; "current" counts points applied so far of "total".
        self._route_progress: dict = {"current": 0, "total": 0, "playing": False}

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
            90: "LANDSCAPE_RIGHT",
            180: "PORTRAIT_UPSIDE_DOWN",
            270: "LANDSCAPE_LEFT",
        }
        # Fallback for the coarse /orientation string.
        normalize = {
            "PORTRAIT": ("PORTRAIT", 0),
            "UIA_DEVICE_ORIENTATION_PORTRAIT": ("PORTRAIT", 0),
            "PORTRAITUPSIDEDOWN": ("PORTRAIT_UPSIDE_DOWN", 180),
            "UPSIDE_DOWN": ("PORTRAIT_UPSIDE_DOWN", 180),
            "UIA_DEVICE_ORIENTATION_PORTRAIT_UPSIDEDOWN": ("PORTRAIT_UPSIDE_DOWN", 180),
            "LANDSCAPELEFT": ("LANDSCAPE_LEFT", 270),
            "LANDSCAPE": ("LANDSCAPE_LEFT", 270),
            "UIA_DEVICE_ORIENTATION_LANDSCAPELEFT": ("LANDSCAPE_LEFT", 270),
            "LANDSCAPERIGHT": ("LANDSCAPE_RIGHT", 90),
            "UIA_DEVICE_ORIENTATION_LANDSCAPERIGHT": ("LANDSCAPE_RIGHT", 90),
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

    # -- App-switcher gestures -----------------------------------------

    def _app_switcher_swipe_w3c_fallback(
        self,
        cx: float,
        h: int,
        *,
        to_y_ratio: float,
        move_duration_ms: int,
        pause_before_ms: int,
        pause_after_ms: int,
    ) -> None:
        """Fallback swipe-up-hold for App Switcher using W3C touch actions."""
        y_start = h - 2
        y_end = int(h * to_y_ratio)
        self._pointer_gesture([
            {"type": "pointerMove", "duration": 0, "x": int(cx), "y": y_start},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": pause_before_ms},
            {"type": "pointerMove", "duration": move_duration_ms, "x": int(cx), "y": y_end},
            {"type": "pause", "duration": pause_after_ms},
            {"type": "pointerUp", "button": 0},
        ])

    def _app_switcher_swipe_native(
        self,
        *,
        to_y_ratio: float,
        press_duration: float,
        velocity_duration: float,
        hold_duration: float,
        w3c_move_duration_ms: int,
        w3c_pause_before_ms: int,
        w3c_pause_after_ms: int,
    ) -> dict:
        """Execute the App Switcher swipe-up-hold gesture."""
        size = self.window_size()
        if not size.get("ok"):
            return size
        w = size["data"]["width"]
        h = size["data"]["height"]
        cx = w / 2.0
        from_y = float(h - 1)
        to_y = h * to_y_ratio
        velocity = (from_y - to_y) / velocity_duration

        try:
            self._post_with_session_retry(
                "/session/{sid}/wda/pressAndDragWithVelocity",
                {
                    "fromX": cx, "fromY": from_y,
                    "toX": cx, "toY": to_y,
                    "pressDuration": press_duration,
                    "velocity": velocity,
                    "holdDuration": hold_duration,
                },
            )
            return {}
        except Exception:
            self._app_switcher_swipe_w3c_fallback(
                cx,
                h,
                to_y_ratio=to_y_ratio,
                move_duration_ms=w3c_move_duration_ms,
                pause_before_ms=w3c_pause_before_ms,
                pause_after_ms=w3c_pause_after_ms,
            )
            return {"w3c_fallback": True}

    def _bottom_edge_swipe_w3c(
        self,
        *,
        to_y_ratio: float,
    ) -> dict:
        """Execute a fast bottom-edge swipe using segmented W3C touch actions."""
        size = self.window_size()
        if not size.get("ok"):
            return size
        w = size["data"]["width"]
        h = size["data"]["height"]
        cx = w / 2.0
        y_start = h - 2
        y_end = int(h * to_y_ratio)
        y_mid_1 = int(h * 0.90)
        y_mid_2 = int(h * 0.68)

        self._pointer_gesture([
            {"type": "pointerMove", "duration": 0, "x": int(cx), "y": y_start},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerMove", "duration": 24, "x": int(cx), "y": y_mid_1},
            {"type": "pointerMove", "duration": 36, "x": int(cx), "y": y_mid_2},
            {"type": "pointerMove", "duration": 48, "x": int(cx), "y": y_end},
            {"type": "pointerUp", "button": 0},
        ])
        return {}

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

    def _app_switcher_swipe(self) -> dict:
        """Open App Switcher via one native swipe-up-hold attempt."""
        from .toolkit_api import _ok

        result = self._app_switcher_swipe_native(
            to_y_ratio=0.6,
            press_duration=0.03,
            velocity_duration=0.1,
            hold_duration=0.1,
            w3c_move_duration_ms=600,
            w3c_pause_before_ms=70,
            w3c_pause_after_ms=1100,
        )
        if result.get("ok") is False:
            return result
        if result.get("w3c_fallback"):
            return _ok({"exitCode": 0, "stdout": "", "stderr": "",
                        "extra": {"gesture": "app_switcher", "method": "w3c_fallback"}})
        return _ok({"exitCode": 0, "stdout": "", "stderr": "",
                    "extra": {"gesture": "app_switcher",
                              "method": "pressAndDragWithVelocity"}})

    def app_switcher(self) -> dict:
        """Open the iOS App Switcher via swipe-up-and-hold."""

        try:
            return self._app_switcher_swipe()
        except Exception as exc:
            from .toolkit_api import _err
            return _err("SUBPROCESS", str(exc))

    def bottom_edge_swipe(self) -> dict:
        """Perform a bottom-edge swipe-up gesture."""
        from .toolkit_api import _ok, _err

        try:
            result = self._bottom_edge_swipe_w3c(
                to_y_ratio=0.32,
            )
            if result.get("ok") is False:
                return result
            return _ok({"exitCode": 0, "stdout": "", "stderr": "",
                        "extra": {"gesture": "bottom_edge_swipe",
                                  "method": "w3c_actions"}})
        except Exception as exc:
            return _err("SUBPROCESS", str(exc))

    # ------------------------------------------------------------------
    # App management (installation_proxy)
    # ------------------------------------------------------------------
    #
    # These operate over lockdown/usbmux and do NOT require WDA or an XPC
    # tunnel, so they work regardless of WDA install state or iOS version.

    @staticmethod
    def _format_app_version(short: "Optional[str]", build: "Optional[str]") -> str:
        """Render an app version as 'short (build)', collapsing duplicates/blanks."""
        short = (short or "").strip()
        build = (build or "").strip()
        if short and build and build != short:
            return f"{short} ({build})"
        return short or build

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
            # Sandbox (VendContainer) access is only granted to *debuggable*
            # apps, i.e. those carrying the get-task-allow entitlement. On iOS
            # installation_proxy returns this under the bare key "get-task-allow"
            # (the "com.apple.security." prefix is the macOS spelling, kept here
            # only as a secondary fallback). SignerIdentity is NOT a valid
            # signal: App Store apps also carry one ("Apple iPhone OS
            # Application Signing") yet their containers cannot be vended.
            sandbox_accessible = bool(
                entitlements.get("get-task-allow")
                or entitlements.get("com.apple.security.get-task-allow")
            )
            apps.append({
                "bundleId": bundle_id,
                "name": (info.get("CFBundleDisplayName")
                         or info.get("CFBundleName") or bundle_id),
                # Marketing version (build in parentheses when it differs); both
                # already come back in this same get_apps payload, so exposing
                # them is free — no extra device round-trip.
                "version": self._format_app_version(
                    info.get("CFBundleShortVersionString"),
                    info.get("CFBundleVersion"),
                ),
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
    # Host pairing (trust) — over usbmux lockdown, no WDA / tunnel required
    # ------------------------------------------------------------------
    #
    # Most lockdown services (app install, AFC, crash, profiles, DDI/DVT, WDA)
    # require a valid host pairing record. These helpers expose the pairing state
    # and let the UI establish or revoke trust without auto-pairing elsewhere
    # (all other lockdown connections use autopair=False on purpose).

    async def _open_lockdown_no_autopair(self):
        """Create an initialized usbmux lockdown client WITHOUT the built-in
        validate/autopair step.

        ``create_using_usbmux`` always runs ``_handle_autopair`` ->
        ``validate_pairing`` (even with ``autopair=False``). On a device that
        still carries a stale host pair record, ``validate_pairing`` raises
        ``ConnectionTerminatedError`` (a wrapped SSL EOF) and tears down the
        whole connection — which previously broke both the pairing probe and the
        pair request itself (the on-device "Trust" prompt was never sent).
        Building the client by hand lets us decide when to validate / pair.

        The caller owns the returned client and must ``await lockdown.close()``.
        """
        from pymobiledevice3 import usbmux
        from pymobiledevice3.lockdown import (
            DEFAULT_LABEL,
            SERVICE_PORT,
            SYSTEM_BUID,
            PlistUsbmuxLockdownClient,
            UsbmuxLockdownClient,
        )
        from pymobiledevice3.pair_records import (
            create_pairing_records_cache_folder,
            generate_host_id,
        )
        from pymobiledevice3.service_connection import ServiceConnection
        from pymobiledevice3.usbmux import PlistMuxConnection

        service = await ServiceConnection.create_using_usbmux(self.udid, SERVICE_PORT)
        try:
            cls: type = UsbmuxLockdownClient
            system_buid = SYSTEM_BUID
            async with await usbmux.create_mux() as mux:
                if isinstance(mux, PlistMuxConnection):
                    # Modern usbmuxd: BUID + pair-record persistence available.
                    system_buid = await mux.get_buid()
                    cls = PlistUsbmuxLockdownClient
            lockdown = cls(
                service,
                host_id=generate_host_id(),
                identifier=service.mux_device.serial,
                label=DEFAULT_LABEL,
                system_buid=system_buid,
                pair_record=None,
                pairing_records_cache_folder=create_pairing_records_cache_folder(
                    Path(_PAIRING_RECORDS_DIR)
                ),
                port=SERVICE_PORT,
            )
            await lockdown._initialize()
        except Exception:
            await service.close()
            raise
        return lockdown

    def _clear_unwritable_pair_cache(self) -> None:
        """Remove a stale local pair-record file we are unable to overwrite.

        Records left behind by an earlier ``sudo`` run are owned by root. The
        cache directory itself is user-owned, so we can *delete* (but not
        rewrite) such files — clearing one lets ``lockdown.pair()`` persist a
        fresh, user-owned record instead of failing with ``PermissionError``.
        Best-effort: any failure here is logged and ignored.
        """
        try:
            from pymobiledevice3.pair_records import create_pairing_records_cache_folder

            folder = create_pairing_records_cache_folder(Path(_PAIRING_RECORDS_DIR))
            path = folder / f"{self.udid}.plist"
            if path.exists() and not os.access(path, os.W_OK):
                path.unlink()
                logger.info("pair: removed unwritable stale cache record %s", path)
        except Exception:
            logger.warning("pair: failed to clear stale cache record udid=%s",
                           self.udid, exc_info=True)

    async def _probe_paired_async(self) -> bool:
        """Report whether a valid host pairing record exists for this device.

        We run ``validate_pairing`` ourselves so we can interpret the
        SSL-EOF / connection-terminated case the way pymobiledevice3 intends but
        currently fails to: its ``except SSLZeroReturnError`` no longer matches
        because ``ssl_start`` rewraps the error as ``ConnectionTerminatedError``.
        A stale record the device no longer honors means "not paired", not a
        hard error.
        """
        import ssl

        from pymobiledevice3.exceptions import ConnectionTerminatedError

        lockdown = await self._open_lockdown_no_autopair()
        try:
            try:
                return bool(await lockdown.validate_pairing())
            except (ConnectionTerminatedError, ssl.SSLError):
                logger.info(
                    "pairing probe: validate raised SSL/terminated -> treating "
                    "udid=%s as unpaired", self.udid)
                return False
        finally:
            with contextlib.suppress(Exception):
                await lockdown.close()

    def pairing_state(self) -> dict:
        """Report whether a valid host pairing record exists for this device."""
        from .toolkit_api import _ok, _err

        logger.info("pairing_state: probing udid=%s", self.udid)
        future = asyncio.run_coroutine_threadsafe(self._probe_paired_async(), _bg_loop)
        try:
            paired = future.result(timeout=20)
            logger.info("pairing_state: udid=%s paired=%s", self.udid, paired)
            return _ok({"paired": paired})
        except Exception as exc:
            logger.exception("pairing_state: probe failed udid=%s", self.udid)
            return _err("SUBPROCESS", str(exc))

    def pair(self) -> dict:
        """Initiate host pairing; the device shows a "Trust This Computer" prompt.

        We pair on a fresh connection WITHOUT validating first: a stale host
        record makes validation abort before the trust prompt can even be sent.
        ``lockdown.pair()`` regenerates the host certificate, drives the
        on-device dialog, and (for usbmux clients) persists the fresh record back
        to usbmuxd — overwriting any stale record so later validation succeeds.
        Blocks until the user accepts (and enters the passcode) or it fails.
        """
        from .toolkit_api import _ok, _err

        # Drop a stale, root-owned cache record up front so save_pair_record()
        # can write a fresh user-owned one after the trust prompt succeeds.
        self._clear_unwritable_pair_cache()

        async def _op() -> bool:
            lockdown = await self._open_lockdown_no_autopair()
            try:
                logger.info(
                    "pair: requesting pairing (awaiting on-device trust) udid=%s",
                    self.udid)
                await lockdown.pair()
                logger.info("pair: pair() returned udid=%s paired=%s",
                            self.udid, getattr(lockdown, "paired", None))
                return True
            finally:
                with contextlib.suppress(Exception):
                    await lockdown.close()

        # Generous timeout: the user must physically accept on the device.
        future = asyncio.run_coroutine_threadsafe(_op(), _bg_loop)
        try:
            future.result(timeout=120)
        except Exception as exc:
            logger.exception("pair: failed udid=%s", self.udid)
            return _err("SUBPROCESS", str(exc))

        # Confirm the persisted pairing state on a clean connection.
        try:
            verify = asyncio.run_coroutine_threadsafe(self._probe_paired_async(), _bg_loop)
            paired = verify.result(timeout=20)
        except Exception:
            logger.exception("pair: post-pair verify failed udid=%s", self.udid)
            paired = True
        logger.info("pair: final state udid=%s paired=%s", self.udid, paired)
        return _ok({"paired": paired})

    def unpair(self) -> dict:
        """Revoke this host's pairing record on the device.

        Unpair only needs the existing record to send the ``Unpair`` request (no
        SSL handshake), so we load it manually and skip validation — which would
        otherwise abort on a stale record.
        """
        from .toolkit_api import _ok, _err

        async def _op() -> bool:
            lockdown = await self._open_lockdown_no_autopair()
            try:
                await lockdown.fetch_pair_record()
                if getattr(lockdown, "pair_record", None):
                    await lockdown.unpair()
                    logger.info("unpair: unpair() sent udid=%s", self.udid)
                else:
                    logger.info("unpair: no pair record to revoke udid=%s", self.udid)
                return False
            finally:
                with contextlib.suppress(Exception):
                    await lockdown.close()

        future = asyncio.run_coroutine_threadsafe(_op(), _bg_loop)
        try:
            paired = future.result(timeout=30)
            logger.info("unpair: completed udid=%s paired=%s", self.udid, paired)
            return _ok({"paired": paired})
        except Exception as exc:
            logger.exception("unpair: failed udid=%s", self.udid)
            return _err("SUBPROCESS", str(exc))

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

    # Note: iOS does not expose the raw bytes of an installed profile via
    # MCInstall (GetProfileList returns metadata only), so there is no
    # export_profile capability.

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
    # Developer tooling: DDI mount + DVT instruments (process / location)
    # ------------------------------------------------------------------
    #
    # DDI mount / unmount / status talk to the lockdown mobile_image_mounter over
    # usbmux and do NOT require an XPC tunnel (even on iOS 17+). DVT instruments
    # (process list/control, location simulation) DO require a mounted DDI and,
    # on iOS 17+, the tunneld RSD. Connection selection mirrors the WDA flow.

    @staticmethod
    def _ddi_image_type(major: int) -> str:
        """iOS 17+ uses personalized images; earlier versions use developer ones."""
        return "Personalized" if major >= 17 else "Developer"

    def ddi_status(self) -> dict:
        """Report DDI mount state + developer-mode status (usbmux, no tunnel).

        ``copy_devices`` is the source of truth for what is actually mounted (it
        returns each image's real DiskImageType and MountPath), so the UI can
        show which image is mounted and unmount uses the true path. ``mounted``
        falls back to ``is_image_mounted`` when CopyDevices is unsupported.
        """
        from .toolkit_api import _ok, _err

        major = self._ios_major_version()
        image_type = self._ddi_image_type(major)

        async def _op() -> dict:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_image_mounter import (
                MobileImageMounterService,
            )

            # Step-level traces so a hang can be pinpointed to the exact call
            # (the last "ddi_status step:" line before a timeout is the culprit).
            logger.debug("ddi_status step: creating usbmux lockdown")
            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                logger.debug("ddi_status step: opening mounter service")
                async with MobileImageMounterService(lockdown) as mounter:
                    images: list[dict] = []
                    mounted: Optional[bool] = None
                    dev_mode: bool = True
                    # Do the lightweight, reliable queries FIRST so we always get
                    # the mounted boolean + developer-mode flag, then attempt the
                    # detail-listing CopyDevices LAST (see below).
                    try:
                        logger.debug("ddi_status step: is_image_mounted")
                        mounted = await asyncio.wait_for(
                            mounter.is_image_mounted(image_type), timeout=10
                        )
                    except Exception as exc:
                        logger.debug("ddi_status step: is_image_mounted failed: %s", exc)
                    try:
                        logger.debug("ddi_status step: query_developer_mode_status")
                        dev_mode = await asyncio.wait_for(
                            mounter.query_developer_mode_status(), timeout=5
                        )
                    except Exception as exc:
                        # Pre-iOS16 devices have no developer-mode gate; also tolerate
                        # a slow/timed-out query so status never blocks on it.
                        logger.debug("ddi_status step: dev-mode query failed: %s", exc)
                        dev_mode = True
                    # CopyDevices enriches the UI with image type + mount path, but
                    # can hang indefinitely right after a personalized mount on
                    # iOS 17+ (the device-side mounter stops replying). Run it LAST
                    # and bounded: a timeout only loses the detail list (mounted is
                    # already known), and because no further command is issued on
                    # this session afterwards a late reply cannot desync it.
                    try:
                        logger.debug("ddi_status step: copy_devices")
                        devices = await asyncio.wait_for(mounter.copy_devices(), timeout=5)
                        for d in devices or []:
                            images.append({
                                "diskImageType": str(
                                    d.get("DiskImageType") or d.get("ImageType") or ""
                                ),
                                "mountPath": str(d.get("MountPath") or ""),
                            })
                        if mounted is None:
                            mounted = len(images) > 0
                    except asyncio.TimeoutError:
                        logger.warning(
                            "ddi_status step: copy_devices hung (>5s); "
                            "reporting status without image detail"
                        )
                    except Exception as exc:
                        logger.debug("ddi_status step: copy_devices failed: %s", exc)
            logger.debug("ddi_status step: done")
            return {
                "mounted": bool(mounted),
                "developerMode": bool(dev_mode),
                "images": images,
            }

        # Run on a private loop (see _run_isolated): a slow/blocking image
        # download or upload during a concurrent mount must not freeze _bg_loop.
        # Bounded so a stuck mounter service cannot hang the UI indefinitely.
        try:
            data = _run_isolated(_op(), timeout=20)
        except asyncio.TimeoutError:
            logger.warning("ddi_status timed out (udid=%s)", self.udid)
            return _err(
                "TIMEOUT",
                "Querying DDI status timed out (device mounter service not responding)",
                code="DDI_STATUS_TIMEOUT",
            )
        except Exception as exc:
            logger.warning("ddi_status failed (udid=%s): %s", self.udid, exc, exc_info=True)
            return _err("SUBPROCESS", str(exc))
        data.update({"imageType": image_type, "iosMajor": major})
        logger.debug(
            "ddi_status: udid=%s mounted=%s images=%s",
            self.udid, data.get("mounted"), len(data.get("images") or []),
        )
        return _ok(data)

    def ddi_wait_ready(self, timeout: float = 500.0) -> dict:
        """Wait until the developer (DVT) services are reachable.

        The lightest reliable readiness signal: open + immediately close a
        ``DvtProvider`` — i.e. just the DTX capability handshake, with no
        instrument call — retrying with backoff until it succeeds or ``timeout``
        (seconds) elapses. This probes the developer-services path (RSD/tunnel on
        iOS 17+, usbmux on iOS<17), NOT the mounter — which is exactly the
        service that stays unresponsive while the device finalises a fresh
        personalized mount. Use it to gate DVT features after a successful mount
        instead of polling ``ddi_status`` (which would just hit the busy mounter).
        """
        from .toolkit_api import _ok, _err

        async def _probe(_dvt) -> bool:
            # Reaching the body means RSD + DvtProvider handshake succeeded.
            return True

        deadline = time.monotonic() + max(1.0, float(timeout))
        attempt = 0
        last_err: "Optional[Exception]" = None
        logger.info("ddi_wait_ready: probing DVT readiness (udid=%s timeout=%ss)",
                    self.udid, timeout)
        while time.monotonic() < deadline:
            attempt += 1
            try:
                # Bound each attempt: a hung RSD/handshake must not pin the loop.
                async def _attempt() -> bool:
                    return await asyncio.wait_for(self._with_dvt(_probe), timeout=20)

                future = asyncio.run_coroutine_threadsafe(_attempt(), _bg_loop)
                future.result(timeout=25)
                logger.info("ddi_wait_ready: DVT ready (udid=%s, attempt=%s)",
                            self.udid, attempt)
                return _ok({"ready": True, "attempts": attempt})
            except Exception as exc:
                last_err = exc
                logger.debug("ddi_wait_ready: attempt %s not ready: %s", attempt, exc)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(5.0, max(0.5, remaining)))
        logger.warning(
            "ddi_wait_ready: timed out (udid=%s, %ss, last=%s)",
            self.udid, timeout, last_err,
        )
        return _err(
            "TIMEOUT",
            "Timed out waiting for DVT readiness (device still preparing DeveloperDiskImage)",
            code="DVT_READY_TIMEOUT",
        )

    def rsd_service_available(self, service_name: str, timeout: float = 12.0) -> dict:
        """Check whether an RSD developer service is exposed by the tunnel (iOS 17+).

        Lightweight readiness probe for the symptom behind "keyboard-mouse / WDA
        fails after a late DDI mount": a tunnel established before the DDI was
        mounted has a stale RSD service list that lacks the just-published
        developer services (notably ``com.apple.dt.testmanagerd.remote``). We only
        open the RSD XPC connection and read its handshake ``peer_info["Services"]``
        — no DVT/instruments session — so this is far cheaper than ddi_wait_ready.

        Returns ``_ok({"available": bool})``. When the tunnel has no RSD entry for
        this device (tunnel down or device absent) we report ``available=False``
        rather than erroring; the caller checks tunnel liveness separately and maps
        the combination to the right guidance.
        """
        from .toolkit_api import _ok, _err

        rsd = _get_rsd_from_tunneld(self.udid)
        if rsd is None:
            # No tunnel (or device not in its table) → service can't be available.
            return _ok({"available": False})

        async def _op() -> bool:
            from pymobiledevice3.remote.remote_service_discovery import (
                RemoteServiceDiscoveryService,
            )

            async with RemoteServiceDiscoveryService(rsd) as rsd_svc:
                services = (rsd_svc.peer_info or {}).get("Services", {}) or {}
                return service_name in services

        try:
            available = _run_isolated(_op(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("rsd_service_available timed out (udid=%s)", self.udid)
            return _err(
                "TIMEOUT",
                "Querying RSD service timed out (XPC tunnel not responding)",
                code="RSD_QUERY_TIMEOUT",
            )
        except Exception as exc:
            logger.debug("rsd_service_available failed (udid=%s): %s", self.udid, exc)
            # A handshake failure means the tunnel session is unusable for this
            # service; treat as unavailable rather than a hard error.
            return _ok({"available": False})
        logger.debug(
            "rsd_service_available: udid=%s service=%s available=%s",
            self.udid, service_name, available,
        )
        return _ok({"available": bool(available)})

    def ddi_mount(
        self,
        family: str,
        *,
        image: "Optional[str]" = None,
        signature: "Optional[str]" = None,
        build_manifest: "Optional[str]" = None,
        trustcache: "Optional[str]" = None,
    ) -> dict:
        """Mount an already-resolved DeveloperDiskImage onto the device.

        Pure device interaction over usbmux lockdown (no XPC tunnel): image
        acquisition (offline index, local lookup, GitHub download, fallback) is
        handled upstream by ``ios_toolkit.ddi_provider``; this only uploads and
        mounts the given files. ``family`` selects the mounter:
          - "personalized" (iOS 17+): needs image / build_manifest / trustcache
          - "developer"    (iOS <17): needs image / signature
        An already-mounted image is treated as success (idempotent).
        """
        from .toolkit_api import _ok, _err

        if not image:
            return _err("BAD_TARGET", "missing image file", code="DDI_IMAGE_MISSING")
        if family == "personalized":
            if not build_manifest or not trustcache:
                return _err(
                    "BAD_TARGET",
                    "personalized mount requires image / build_manifest / trustcache",
                    code="DDI_PERSONALIZED_ARGS_MISSING",
                )
        elif family == "developer":
            if not signature:
                return _err(
                    "BAD_TARGET",
                    "developer mount requires image / signature",
                    code="DDI_DEVELOPER_ARGS_MISSING",
                )
        else:
            return _err(
                "BAD_TARGET",
                "unknown DDI family",
                details={"family": family},
                code="DDI_UNKNOWN_FAMILY",
            )

        logger.info(
            "ddi_mount: udid=%s family=%s image=%s", self.udid, family, image,
        )

        async def _op() -> None:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services import mobile_image_mounter as mim

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                if family == "personalized":
                    await mim.PersonalizedImageMounter(lockdown=lockdown).mount(
                        Path(image), Path(build_manifest), Path(trustcache)
                    )
                else:
                    await mim.DeveloperDiskImageMounter(lockdown=lockdown).mount(
                        Path(image), Path(signature)
                    )

        # Uploading the image can block for a while; run on a private loop so it
        # does not freeze the shared _bg_loop. A generous timeout guards against
        # a permanently stuck operation.
        try:
            _run_isolated(_op(), timeout=300)
        except asyncio.TimeoutError:
            logger.warning("ddi_mount timed out (family=%s)", family)
            return _err(
                "TIMEOUT",
                "Mounting DDI timed out (image upload too slow or stuck)",
                code="DDI_MOUNT_TIMEOUT",
            )
        except Exception as exc:
            from pymobiledevice3.services.mobile_image_mounter import (
                AlreadyMountedError,
                DeveloperModeIsNotEnabledError,
            )

            if isinstance(exc, AlreadyMountedError):
                logger.info("ddi_mount: already mounted (family=%s)", family)
                return _ok({"mounted": True, "family": family, "already": True})
            if isinstance(exc, DeveloperModeIsNotEnabledError):
                logger.warning("ddi_mount: developer mode not enabled")
                return _err(
                    "SUBPROCESS",
                    "Developer Mode is off (enable it on the device, then retry)",
                    code="DEVELOPER_MODE_OFF",
                )
            logger.warning("ddi_mount failed (family=%s): %s", family, exc, exc_info=True)
            return _err("SUBPROCESS", str(exc))
        logger.info("ddi_mount: mounted (family=%s)", family)
        return _ok({"mounted": True, "family": family})

    def ddi_unmount(self) -> dict:
        """Unmount the DeveloperDiskImage by its actual mount path(s).

        The unmount command is path-based, and the personalized/developer mount
        path can differ from the version-derived default, so the real paths are
        read from ``copy_devices`` first; the version-based well-known paths are
        only a fallback when CopyDevices is unsupported.
        """
        from .toolkit_api import _ok, _err

        major = self._ios_major_version()

        async def _op() -> int:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_image_mounter import (
                DeveloperDiskImageMounter,
                MobileImageMounterService,
                PersonalizedImageMounter,
            )

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                async with MobileImageMounterService(lockdown) as mounter:
                    mount_paths: list[str] = []
                    # CopyDevices can hang right after a personalized mount on
                    # iOS 17+; bound it and fall back to the well-known umount path.
                    try:
                        devices = await asyncio.wait_for(
                            mounter.copy_devices(), timeout=5
                        )
                        for d in devices or []:
                            mp = d.get("MountPath")
                            if mp:
                                mount_paths.append(str(mp))
                    except asyncio.TimeoutError:
                        logger.warning(
                            "ddi_unmount: copy_devices hung (>5s); using fallback path"
                        )
                    except Exception as exc:
                        logger.debug("ddi_unmount: copy_devices failed: %s", exc)
                    logger.debug("ddi_unmount: copy_devices mount paths=%s", mount_paths)
                    if mount_paths:
                        for mp in mount_paths:
                            await mounter.unmount_image(mp)
                        return len(mount_paths)
                # Fallback: no CopyDevices support; use the well-known path.
                if major >= 17:
                    await PersonalizedImageMounter(lockdown=lockdown).umount()
                else:
                    await DeveloperDiskImageMounter(lockdown=lockdown).umount()
                return 1

        logger.info("ddi_unmount: udid=%s os_major=%s", self.udid, major)
        try:
            count = _run_isolated(_op(), timeout=60)
        except asyncio.TimeoutError:
            logger.warning("ddi_unmount timed out")
            return _err(
                "TIMEOUT",
                "Unmounting DDI timed out (device mounter service not responding)",
                code="DDI_UNMOUNT_TIMEOUT",
            )
        except Exception as exc:
            from pymobiledevice3.services.mobile_image_mounter import NotMountedError

            if isinstance(exc, NotMountedError):
                logger.info("ddi_unmount: nothing mounted")
                return _ok({"unmounted": True, "already": True})
            logger.warning("ddi_unmount failed: %s", exc, exc_info=True)
            return _err("SUBPROCESS", str(exc))
        logger.info("ddi_unmount: unmounted %s path(s)", count)
        return _ok({"unmounted": True, "count": count})

    async def _with_dvt(self, op: "Callable[[object], Awaitable]"):
        """Open a DVT (instruments) session for one request and run ``op(dvt)``.

        iOS < 17 connects over usbmux lockdown; iOS 17+ connects over the
        tunneld RSD (raising a readable error when the tunnel is not running).
        Requires a mounted DDI (pymobiledevice3 raises if it is missing).
        """
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider

        major = self._ios_major_version()
        if major >= 17:
            rsd = _get_rsd_from_tunneld(self.udid)
            if rsd is None:
                raise _TunnelRequiredError(_TUNNEL_REQUIRED_MSG)
            from pymobiledevice3.remote.remote_service_discovery import (
                RemoteServiceDiscoveryService,
            )

            async with RemoteServiceDiscoveryService(rsd) as rsd_svc:
                async with DvtProvider(rsd_svc) as dvt:
                    return await op(dvt)
        else:
            from pymobiledevice3.lockdown import create_using_usbmux

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                async with DvtProvider(lockdown) as dvt:
                    return await op(dvt)

    def list_processes(self) -> dict:
        """List running processes via DVT DeviceInfo.proclist."""
        from .toolkit_api import _ok, _err

        async def _op(dvt) -> list[dict]:
            from pymobiledevice3.services.dvt.instruments.device_info import DeviceInfo

            async with DeviceInfo(dvt) as di:
                raw = await di.proclist()
            procs: list[dict] = []
            for p in raw or []:
                start = p.get("startDate")
                procs.append({
                    "pid": p.get("pid"),
                    "name": p.get("name") or p.get("realAppName") or "",
                    "realAppName": p.get("realAppName") or "",
                    "isApplication": bool(p.get("isApplication", False)),
                    "startDate": start.isoformat() if hasattr(start, "isoformat") else str(start or ""),
                })
            return procs

        future = asyncio.run_coroutine_threadsafe(self._with_dvt(_op), _bg_loop)
        try:
            procs = future.result(timeout=60)
            logger.debug("list_processes: udid=%s count=%s", self.udid, len(procs))
            return _ok({"processes": procs})
        except Exception as exc:
            logger.warning("list_processes failed (udid=%s): %s", self.udid, exc, exc_info=True)
            return _dvt_exc_to_err(exc)

    def launch_app_dvt(self, bundle_id: str) -> dict:
        """Launch an app by bundle id via DVT ProcessControl; return its pid."""
        from .toolkit_api import _ok, _err

        if not bundle_id:
            return _err("BAD_TARGET", "bundle_id is required")

        async def _op(dvt) -> int:
            from pymobiledevice3.services.dvt.instruments.process_control import (
                ProcessControl,
            )

            async with ProcessControl(dvt) as pc:
                return await pc.launch(bundle_id)

        logger.info("launch_app_dvt: udid=%s bundle_id=%s", self.udid, bundle_id)
        future = asyncio.run_coroutine_threadsafe(self._with_dvt(_op), _bg_loop)
        try:
            pid = future.result(timeout=60)
            logger.info("launch_app_dvt: launched %s pid=%s", bundle_id, pid)
            return _ok({"launched": True, "bundleId": bundle_id, "pid": pid})
        except Exception as exc:
            logger.warning("launch_app_dvt failed (%s): %s", bundle_id, exc, exc_info=True)
            return _dvt_exc_to_err(exc)

    def kill_process(self, pid: int) -> dict:
        """Terminate a process by pid via DVT ProcessControl."""
        from .toolkit_api import _ok, _err

        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            return _err("BAD_TARGET", f"invalid pid: {pid}")

        async def _op(dvt) -> None:
            from pymobiledevice3.services.dvt.instruments.process_control import (
                ProcessControl,
            )

            async with ProcessControl(dvt) as pc:
                await pc.kill(pid_int)

        logger.info("kill_process: udid=%s pid=%s", self.udid, pid_int)
        future = asyncio.run_coroutine_threadsafe(self._with_dvt(_op), _bg_loop)
        try:
            future.result(timeout=60)
            logger.info("kill_process: killed pid=%s", pid_int)
            return _ok({"killed": True, "pid": pid_int})
        except Exception as exc:
            logger.warning("kill_process failed (pid=%s): %s", pid_int, exc, exc_info=True)
            return _dvt_exc_to_err(exc)

    # -- Diagnostics ------------------------------------------------------

    async def _with_diagnostics(self, op: "Callable[[object], Awaitable]"):
        """Open a DiagnosticsService for one request and run ``op(ds)``.

        iOS < 17 connects over usbmux lockdown; iOS 17+ connects over the
        tunneld RSD (raising _TunnelRequiredError when the tunnel is not up).
        Unlike DVT, this does NOT require a mounted DDI.
        """
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        major = self._ios_major_version()
        if major >= 17:
            rsd = _get_rsd_from_tunneld(self.udid)
            if rsd is None:
                raise _TunnelRequiredError(_TUNNEL_REQUIRED_MSG)
            from pymobiledevice3.remote.remote_service_discovery import (
                RemoteServiceDiscoveryService,
            )

            async with RemoteServiceDiscoveryService(rsd) as rsd_svc:
                async with DiagnosticsService(rsd_svc) as ds:
                    return await op(ds)
        else:
            from pymobiledevice3.lockdown import create_using_usbmux

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                async with DiagnosticsService(lockdown) as ds:
                    return await op(ds)

    async def _diag_power(self, action_name: str) -> None:
        """Send a power action (Restart/Shutdown/Sleep) via DiagnosticsService.

        The action's Success response arrives before the device tears down, so
        the service close that follows can fail once the device drops the
        connection; that teardown error is suppressed because the action has
        already succeeded.
        """
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        major = self._ios_major_version()
        if major >= 17:
            rsd = _get_rsd_from_tunneld(self.udid)
            if rsd is None:
                raise _TunnelRequiredError(_TUNNEL_REQUIRED_MSG)
            from pymobiledevice3.remote.remote_service_discovery import (
                RemoteServiceDiscoveryService,
            )

            async with RemoteServiceDiscoveryService(rsd) as rsd_svc:
                ds = DiagnosticsService(rsd_svc)
                await ds.connect()
                try:
                    await ds.action(action_name)
                finally:
                    with contextlib.suppress(Exception):
                        await ds.close()
        else:
            from pymobiledevice3.lockdown import create_using_usbmux

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                ds = DiagnosticsService(lockdown)
                await ds.connect()
                try:
                    await ds.action(action_name)
                finally:
                    with contextlib.suppress(Exception):
                        await ds.close()

    def _run_diag_power(self, action_name: str, label: str) -> dict:
        """Shared power-action runner: dispatch, bound by timeout, uniform errors."""
        from .toolkit_api import _ok

        logger.info("diag power: udid=%s action=%s", self.udid, action_name)
        future = asyncio.run_coroutine_threadsafe(
            self._diag_power(action_name), _bg_loop
        )
        try:
            future.result(timeout=30)
            logger.info("diag power: %s sent (udid=%s)", action_name, self.udid)
            return _ok({"action": action_name})
        except Exception as exc:
            logger.warning("diag power %s failed (udid=%s): %s", action_name, self.udid, exc, exc_info=True)
            return _dvt_exc_to_err(exc)

    def device_restart(self) -> dict:
        """Restart (reboot) the device via DiagnosticsService."""
        return self._run_diag_power("Restart", "restart")

    def device_shutdown(self) -> dict:
        """Power off the device via DiagnosticsService."""
        return self._run_diag_power("Shutdown", "shutdown")

    def device_sleep(self) -> dict:
        """Put the device to sleep via DiagnosticsService."""
        return self._run_diag_power("Sleep", "sleep")

    def _run_diag_query(self, name: str, op: "Callable[[object], Awaitable]") -> dict:
        """Shared info-query runner: open DiagnosticsService, run op, wrap result."""
        from .toolkit_api import _ok

        future = asyncio.run_coroutine_threadsafe(
            self._with_diagnostics(op), _bg_loop
        )
        try:
            data = future.result(timeout=30)
            logger.debug("diag query %s ok (udid=%s)", name, self.udid)
            return _ok({"info": data if data is not None else {}})
        except Exception as exc:
            logger.warning("diag query %s failed (udid=%s): %s", name, self.udid, exc, exc_info=True)
            return _diag_exc_to_err(exc)

    def diagnostics_battery(self) -> dict:
        """Query battery (IOPMPowerSource) diagnostics."""
        return self._run_diag_query("battery", lambda ds: ds.get_battery())

    def diagnostics_wifi(self) -> dict:
        """Query Wi-Fi interface diagnostics."""
        return self._run_diag_query("wifi", lambda ds: ds.get_wifi())

    def diagnostics_info(self) -> dict:
        """Query the full diagnostics info bundle (diag_type='All')."""
        return self._run_diag_query("info", lambda ds: ds.info("All"))

    def diagnostics_ioregistry(self) -> dict:
        """Query the device IORegistry (root, unfiltered)."""
        return self._run_diag_query("ioregistry", lambda ds: ds.ioregistry())

    def diagnostics_mobilegestalt(self) -> dict:
        """Query MobileGestalt keys (deprecated by Apple on iOS >= 17.4)."""
        return self._run_diag_query("mobilegestalt", lambda ds: ds.mobilegestalt())

    # -- Virtual location -------------------------------------------------

    def _cancel_location_task(self) -> None:
        """Cancel any live iOS 17+ location-simulation session task."""
        with self._location_lock:
            task = self._location_task
            self._location_task = None
            self._route_progress["playing"] = False
        if task is not None and not task.done():
            task.cancel()

    def get_route_progress(self) -> dict:
        """Return a snapshot of route playback progress for UI polling.

        ``{"current": <points applied>, "total": <points>, "playing": <bool>}``.
        ``playing`` is False once all points are applied (or the session ends).
        """
        with self._location_lock:
            return dict(self._route_progress)

    async def _drive_route(
        self, loc, steps: "list", ready: "threading.Event"
    ) -> None:
        """Walk a location object through ``steps`` = [(lat, lon, delay), ...].

        ``delay`` (seconds) is waited *before* applying each point; the first
        step carries a zero delay so playback starts immediately. ``ready`` is
        set right after the first point is applied so a sync caller can return
        without waiting for the whole route to finish.
        """
        first = True
        applied = 0
        for lat, lon, delay in steps:
            if delay and delay > 0:
                await asyncio.sleep(delay)
            await loc.set(lat, lon)
            applied += 1
            with self._location_lock:
                self._route_progress["current"] = applied
            if first:
                ready.set()
                first = False
        # All points applied: motion is done even though an iOS 17+ session
        # keeps its connection open afterward to persist the final location.
        with self._location_lock:
            self._route_progress["playing"] = False

    async def _run_route_async(
        self, major: int, steps: "list", ready: "threading.Event", err_holder: dict
    ) -> None:
        """Drive a location route, version-aware (shared by point + trajectory).

        iOS<17 applies points over a lockdown ``DtSimulateLocation`` session; the
        simulated location persists after the connection closes. iOS 17+ drives a
        DVT ``LocationSimulation`` over RSD/tunnel and, because the simulation is
        only active while the DTX connection lives, keeps the connection open
        after the route finishes so the final point persists until cancelled.
        """
        try:
            if major < 17:
                from pymobiledevice3.lockdown import create_using_usbmux
                from pymobiledevice3.services.simulate_location import (
                    DtSimulateLocation,
                )

                lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
                async with lockdown:
                    await self._drive_route(DtSimulateLocation(lockdown), steps, ready)
                # <17: simulated location persists after the connection closes.
            else:
                rsd = _get_rsd_from_tunneld(self.udid)
                if rsd is None:
                    raise _TunnelRequiredError(_TUNNEL_REQUIRED_MSG)
                from pymobiledevice3.remote.remote_service_discovery import (
                    RemoteServiceDiscoveryService,
                )
                from pymobiledevice3.services.dvt.instruments.dvt_provider import (
                    DvtProvider,
                )
                from pymobiledevice3.services.dvt.instruments.location_simulation import (
                    LocationSimulation,
                )

                async with RemoteServiceDiscoveryService(rsd) as rsd_svc:
                    async with DvtProvider(rsd_svc) as dvt:
                        async with LocationSimulation(dvt) as loc:
                            await self._drive_route(loc, steps, ready)
                            # Keep the connection (and thus the simulation) alive.
                            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # surface to the sync caller via err_holder
            err_holder["error"] = exc
        finally:
            ready.set()  # never leave a sync caller blocked on ready

    def _start_route(self, steps: "list", ok_data: dict) -> dict:
        """Schedule a route session and return once the first point is applied."""
        from .toolkit_api import _ok, _err

        if not steps:
            return _err("BAD_TARGET", "empty trajectory")

        major = self._ios_major_version()
        logger.info(
            "start route: udid=%s os_major=%s points=%s", self.udid, major, len(steps)
        )
        # Replace any in-flight session before starting a new one.
        self._cancel_location_task()
        with self._location_lock:
            self._route_progress = {"current": 0, "total": len(steps), "playing": True}
        ready = threading.Event()
        err_holder: dict = {}
        task = asyncio.run_coroutine_threadsafe(
            self._run_route_async(major, steps, ready, err_holder), _bg_loop
        )
        # iOS 17+ RSD/DVT setup can take a few seconds; <17 lockdown is quick.
        timeout = 45 if major >= 17 else 30
        if not ready.wait(timeout=timeout):
            task.cancel()
            with self._location_lock:
                self._route_progress["playing"] = False
            logger.warning("start route timed out (udid=%s)", self.udid)
            return _err("SUBPROCESS", "Starting simulated location timed out", code="LOCATION_START_TIMEOUT")
        if err_holder.get("error") is not None:
            task.cancel()
            with self._location_lock:
                self._route_progress["playing"] = False
            logger.warning(
                "start route failed (udid=%s): %s", self.udid, err_holder["error"]
            )
            return _dvt_exc_to_err(err_holder["error"])
        with self._location_lock:
            self._location_task = task
        logger.info("route started; persistent session=%s", major >= 17)
        return _ok(ok_data)

    def set_location(self, latitude: float, longitude: float) -> dict:
        """Set a single simulated GPS location (version-aware)."""
        from .toolkit_api import _err

        try:
            lat = float(latitude)
            lon = float(longitude)
        except (TypeError, ValueError):
            return _err("BAD_TARGET", "latitude/longitude must be numbers")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return _err("BAD_TARGET", "latitude/longitude out of range")

        return self._start_route(
            [(lat, lon, 0.0)],
            {"set": True, "latitude": lat, "longitude": lon},
        )

    def play_route_gpx(
        self,
        path: str,
        ignore_timestamps: bool = False,
        timing_randomness_range: int = 0,
        ignore_mode: str = "interval",
        interval_s: float = 1.0,
        speed_mps: float = 5.0,
    ) -> dict:
        """Play back a GPX trajectory as a moving simulated location."""
        from .toolkit_api import _err

        try:
            steps = _parse_gpx_steps(
                path,
                bool(ignore_timestamps),
                int(timing_randomness_range or 0),
                str(ignore_mode),
                float(interval_s),
                float(speed_mps),
            )
        except FileNotFoundError:
            return _err("BAD_TARGET", "GPX file not found", details={"path": path}, code="GPX_FILE_NOT_FOUND")
        except _GpxNoTrackpointsError as exc:
            return _err("BAD_TARGET", str(exc), code="GPX_NO_TRACKPOINTS")
        except ValueError as exc:
            return _err("BAD_TARGET", str(exc))
        except Exception as exc:
            return _err("SUBPROCESS", "Failed to parse GPX", details={"exc": str(exc)}, code="GPX_PARSE_FAILED")

        return self._start_route(
            steps, {"playing": True, "source": "gpx", "points": len(steps)}
        )

    def play_route_manual(
        self, waypoints: "list", speed_mps: float, tick_s: float = 1.0
    ) -> dict:
        """Play a self-interpolated trajectory through waypoints at a given speed."""
        from .toolkit_api import _err

        try:
            steps = _interpolate_route(waypoints, float(speed_mps), float(tick_s))
        except (TypeError, ValueError) as exc:
            return _err("BAD_TARGET", str(exc))

        return self._start_route(
            steps, {"playing": True, "source": "manual", "points": len(steps)}
        )

    def clear_location(self) -> dict:
        """Clear any simulated GPS location and restore real GPS."""
        from .toolkit_api import _ok, _err

        major = self._ios_major_version()
        logger.info("clear_location: udid=%s os_major=%s", self.udid, major)

        # Stop any in-flight route/point session first (both versions may hold
        # one now that single-point set also runs as a route task).
        self._cancel_location_task()

        if major < 17:
            async def _op() -> None:
                from pymobiledevice3.lockdown import create_using_usbmux
                from pymobiledevice3.services.simulate_location import DtSimulateLocation

                lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
                async with lockdown:
                    await DtSimulateLocation(lockdown).clear()

            future = asyncio.run_coroutine_threadsafe(_op(), _bg_loop)
            try:
                future.result(timeout=30)
                return _ok({"cleared": True})
            except Exception as exc:
                return _err("SUBPROCESS", str(exc))

        # iOS 17+: the session is already cancelled above (which closes the
        # connection and stops the simulation); also issue an explicit clear on a
        # fresh connection (best effort) so real GPS resumes immediately.
        async def _op(dvt) -> None:
            from pymobiledevice3.services.dvt.instruments.location_simulation import (
                LocationSimulation,
            )

            async with LocationSimulation(dvt) as loc:
                await loc.clear()

        future = asyncio.run_coroutine_threadsafe(self._with_dvt(_op), _bg_loop)
        try:
            future.result(timeout=30)
        except Exception:
            # The session was already cancelled (simulation stopped); a failed
            # explicit clear is non-fatal.
            pass
        return _ok({"cleared": True})

    def shutdown_location(self) -> None:
        """Cancel any live location session (call on exit / device switch)."""
        self._cancel_location_task()

    # ------------------------------------------------------------------
    # System log streaming (syslog / os_trace)
    # ------------------------------------------------------------------
    #
    # Streaming is long-lived, so it does not fit the one-shot request/response
    # model. open_log_stream schedules an async consumer on the shared _bg_loop
    # and pushes formatted lines into a thread-safe queue; the desktop UI drains
    # that queue from a worker thread and renders with rate limiting. Both
    # sources are lockdown services (no WDA / tunnel required).

    def open_log_stream(
        self,
        source: str,
        pid: int = -1,
        message_filter: int = 65535,
        stream_flags: int = 60,
    ) -> "LogStreamHandle":
        """Start a syslog/oslog stream; returns a handle exposing a line queue.

        For ``oslog`` the (pid / message_filter / stream_flags) are passed
        straight to ``OsTraceService.syslog(...)`` so source-side filtering (at
        least pid) happens on the device; ``syslog`` ignores them.
        """
        return LogStreamHandle(
            self.udid, source, pid=pid,
            message_filter=message_filter, stream_flags=stream_flags,
        )

    def open_performance_stream(self, interval_ms: int = 500) -> "PerformanceStreamHandle":
        """Start a live DVT performance stream (CPU/GPU/memory metrics)."""
        return PerformanceStreamHandle(self, interval_ms=interval_ms)

    def open_condition_inducer(self) -> "ConditionInducerHandle":
        """Open a connection-scoped DVT Condition Inducer session."""
        return ConditionInducerHandle(self)

    def open_network_stream(self) -> "NetworkStreamHandle":
        """Open a live DVT network monitor (connection flows + throughput)."""
        return NetworkStreamHandle(self)

    @contextlib.asynccontextmanager
    async def _lockdown_provider(self):
        """Yield a connected lockdown service provider, torn down on exit.

        RSD over tunnel on iOS 17+, else usbmux lockdown — each via its own async
        context manager so cleanup is correct for both. For lockdown-only services
        (WebInspector) that need neither DDI nor a DvtProvider, unlike :meth:`_with_dvt`.
        """
        if self._ios_major_version() >= 17:
            rsd = _get_rsd_from_tunneld(self.udid)
            if rsd is None:
                raise _TunnelRequiredError(_TUNNEL_REQUIRED_MSG)
            from pymobiledevice3.remote.remote_service_discovery import (
                RemoteServiceDiscoveryService,
            )

            async with RemoteServiceDiscoveryService(rsd) as provider:
                yield provider
        else:
            from pymobiledevice3.lockdown import create_using_usbmux

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                yield lockdown

    def list_web_pages(self) -> dict:
        """Enumerate WebInspector-debuggable pages (Safari tabs / app WebViews)."""
        from .toolkit_api import _ok, _err

        async def _op() -> list[dict]:
            from pymobiledevice3.services.webinspector import WebinspectorService

            async with self._lockdown_provider() as provider:
                wi = WebinspectorService(lockdown=provider)
                try:
                    await wi.connect()
                    pages = await wi.get_open_application_pages(timeout=3)
                    out = []
                    for ap in pages:
                        app, page = ap.application, ap.page
                        out.append({
                            "app": getattr(app, "name", "") or "",
                            "bundle": getattr(app, "bundle", "") or "",
                            "page_id": getattr(page, "id_", getattr(page, "id", None)),
                            "title": getattr(page, "web_title", getattr(page, "title", "")) or "",
                            "url": getattr(page, "web_url", getattr(page, "url", "")) or "",
                        })
                    return out
                finally:
                    try:
                        await wi.close()
                    except Exception:
                        pass

        future = asyncio.run_coroutine_threadsafe(_op(), _bg_loop)
        try:
            pages = future.result(timeout=30)
            return _ok({"pages": pages})
        except Exception as exc:
            from pymobiledevice3.exceptions import WebInspectorNotEnabledError

            if isinstance(exc, WebInspectorNotEnabledError):
                return _err(
                    "SUBPROCESS",
                    "Web Inspector is disabled on the device",
                    code="WEBINSPECTOR_DISABLED",
                )
            return _dvt_exc_to_err(exc)

    def open_cdp_bridge(self, host: str = "127.0.0.1", port: int = 9222) -> "WebInspectorBridgeHandle":
        """Start a local CDP bridge server for Chrome DevTools."""
        return WebInspectorBridgeHandle(self, host=host, port=port)

    def open_pcap_stream(self, out_path: str, process: "Optional[str]" = None,
                         interface: "Optional[str]" = None, max_packets: int = 100000,
                         max_bytes: int = 50 * 1024 * 1024, max_seconds: int = 600) -> "PcapStreamHandle":
        """Start a pcapd packet capture (over usbmux) writing to ``out_path``."""
        return PcapStreamHandle(
            self, out_path, process=process, interface=interface,
            max_packets=max_packets, max_bytes=max_bytes, max_seconds=max_seconds,
        )

    def collect_logarchive(self, out_path: str) -> dict:
        """Collect device logs into a ``.logarchive`` at ``out_path`` (one-shot).

        Runs on a private event loop (own lockdown connection) so it neither
        depends on nor disturbs any live log stream on the shared loop.
        """
        async def _collect() -> None:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.os_trace import OsTraceService

            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                async with OsTraceService(lockdown=lockdown) as svc:
                    await svc.collect(out_path)

        _run_isolated(_collect(), timeout=600.0)
        return {"ok": True, "data": {"path": out_path}}


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

    def __init__(
        self,
        udid: str,
        source: str,
        pid: int = -1,
        message_filter: int = 65535,
        stream_flags: int = 60,
    ) -> None:
        import queue as _queue

        self.udid = udid
        self.source = source
        self.pid = pid
        self.message_filter = message_filter
        self.stream_flags = stream_flags
        self.queue: "_queue.Queue[tuple[str, object]]" = _queue.Queue(maxsize=20000)
        self._closed = False
        self._lines = 0
        # Set once _run() has fully unwound (including the relay-socket close in
        # its finally). close() waits on this rather than future.result(), because
        # cancelling the future makes result() raise immediately without waiting
        # for the coroutine's cleanup — and we must not return until the relay is
        # actually released.
        self._done = threading.Event()
        logger.debug(
            "LogStreamHandle open: source=%s udid=%s pid=%s msg_filter=%s flags=%s",
            source, udid, pid, message_filter, stream_flags,
        )
        self._future = asyncio.run_coroutine_threadsafe(self._run(), _bg_loop)

    async def _run(self) -> None:
        # Hold the async generator so it can be explicitly aclose()'d on stop:
        # OsTraceService.syslog() may otherwise leave a half-open relay socket on
        # plain cancellation, which makes a subsequent open_log_stream hang or
        # yield nothing (the "repeated start/stop becomes unresponsive" bug).
        gen = None
        svc = None
        try:
            from pymobiledevice3.lockdown import create_using_usbmux

            logger.debug("LogStreamHandle._run: creating lockdown (source=%s)", self.source)
            lockdown = await create_using_usbmux(serial=self.udid, autopair=False)
            async with lockdown:
                logger.debug("LogStreamHandle._run: lockdown ready, opening %s generator", self.source)
                if self.source == "oslog":
                    from pymobiledevice3.services.os_trace import OsTraceService

                    # Tolerate device-reported log levels outside the library's
                    # SyslogLogLevel enum (e.g. 4) so a single odd entry can't
                    # abort the whole stream with "is not a valid SyslogLogLevel".
                    _patch_oslog_level_enum()
                    svc = OsTraceService(lockdown=lockdown)
                    gen = svc.syslog(
                        pid=self.pid,
                        message_filter=self.message_filter,
                        stream_flags=self.stream_flags,
                    )
                    async for entry in gen:
                        if self._closed:
                            break
                        self._put(self.LINE, _oslog_entry_to_dict(entry))
                else:
                    from pymobiledevice3.services.syslog import SyslogService

                    svc = SyslogService(service_provider=lockdown)
                    gen = svc.watch()
                    async for line in gen:
                        if self._closed:
                            break
                        self._put(self.LINE, line)
            logger.debug("LogStreamHandle._run: generator ended naturally (lines=%s)", self._lines)
            self._put(self.EOF, None)
        except asyncio.CancelledError:
            # Swallow: the finally below releases the generator/socket cleanly so
            # the next stream starts from a clean slate.
            logger.debug("LogStreamHandle._run: cancelled (lines=%s)", self._lines)
        except Exception as exc:
            logger.warning("LogStreamHandle._run: error after %s lines: %s", self._lines, exc)
            self._put(self.ERROR, str(exc))
        finally:
            # aclose() only terminates the generator coroutine; it does NOT close
            # the LockdownService's underlying relay socket (OsTraceService /
            # SyslogService.watch have no cleanup of their own). Without an
            # explicit svc.close() the device-side os_trace_relay/syslog_relay
            # StartActivity stream lingers, so the *next* stream connects but
            # receives no data ("second start shows nothing"). Close both.
            if gen is not None:
                try:
                    logger.debug("LogStreamHandle._run: aclose generator")
                    await gen.aclose()
                except Exception as exc:
                    logger.debug("LogStreamHandle._run: aclose failed: %s", exc)
            if svc is not None:
                try:
                    logger.debug("LogStreamHandle._run: closing relay service socket")
                    await svc.close()
                    logger.debug("LogStreamHandle._run: relay service socket closed")
                except Exception as exc:
                    logger.debug("LogStreamHandle._run: svc.close failed: %s", exc)
            # Signal close() that the relay is fully released (cleanup complete).
            self._done.set()

    def _put(self, kind: str, payload: object) -> None:
        if self._closed:
            return
        if kind == self.LINE:
            self._lines += 1
            if self._lines == 1:
                logger.debug("LogStreamHandle: first line received (source=%s)", self.source)
        try:
            self.queue.put_nowait((kind, payload))
        except Exception:
            # Queue is full: drop the line rather than block the bg loop.
            pass

    def close(self) -> None:
        """Stop the stream and release its connection (idempotent, blocking).

        Cancels the coroutine and then **waits** for it to finish — its ``finally``
        runs ``gen.aclose()`` and tears down the lockdown relay. Returning only
        after that completes guarantees the device-side syslog/os_trace relay is
        released before a new stream is opened, so repeated start/stop cycles keep
        producing data (a fresh relay can't attach while a stale one lingers).
        """
        logger.debug(
            "LogStreamHandle.close: source=%s lines=%s future_done=%s",
            self.source, self._lines, self._future.done() if self._future else None,
        )
        self._closed = True
        if self._future and not self._future.done():
            _bg_loop.call_soon_threadsafe(self._future.cancel)
        # Wait for _run() to fully unwind (its finally closes the relay socket),
        # bounded so a stuck device service can't hang the UI thread. Returning
        # only after this guarantees the device relay is released before a new
        # stream is opened — otherwise the next start receives no data.
        if self._done.wait(timeout=3.0):
            logger.debug("LogStreamHandle.close: relay released")
        else:
            logger.warning("LogStreamHandle.close: timed out waiting for relay release")


class PerformanceStreamHandle:
    """Live performance stream backed by DVT sysmontap on the shared loop."""

    LINE = "line"
    ERROR = "error"
    EOF = "eof"
    # All 64-bit Apple devices use 16KB VM pages; sysmontap page counters
    # (physMemSize, vm*Count) are expressed in these pages.
    _PAGE_SIZE = 16384

    def __init__(self, device: "iOSDevice", interval_ms: int = 500) -> None:
        import queue as _queue

        self._device = device
        self.interval_ms = int(interval_ms)
        self.queue: "_queue.Queue[tuple[str, object]]" = _queue.Queue(maxsize=5000)
        self._closed = False
        self._samples = 0
        self._done = threading.Event()
        self._last_system: dict = {}
        self._last_process_entries: list[dict] = []
        self._last_per_cpu: list[dict] = []
        self._last_system_cpu: dict = {}
        self._cpu_count = 0
        # sysmontap's first frame carries uninitialized CPU values (a spurious 0
        # or 100 with EnabledCPUs=0), so the first valid sample is dropped.
        self._first_sample_skipped = False
        logger.debug(
            "PerformanceStreamHandle open: udid=%s interval_ms=%s",
            self._device.udid,
            self.interval_ms,
        )
        self._future = asyncio.run_coroutine_threadsafe(self._run(), _bg_loop)

    async def _run(self) -> None:
        tap = None
        try:
            from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap

            async def _stream(dvt) -> None:
                nonlocal tap
                tap = await Sysmontap.create(dvt, interval=self.interval_ms)
                async with tap:
                    async for row in tap:
                        if self._closed:
                            break
                        sample = self._normalize_row(tap, row)
                        if sample is None:
                            continue
                        if not self._first_sample_skipped:
                            self._first_sample_skipped = True
                            continue
                        self._put(self.LINE, sample)

            await self._device._with_dvt(_stream)
            self._put(self.EOF, None)
        except asyncio.CancelledError:
            logger.debug(
                "PerformanceStreamHandle._run: cancelled (samples=%s)",
                self._samples,
            )
        except Exception as exc:
            logger.warning(
                "PerformanceStreamHandle._run: error after %s samples: %s",
                self._samples,
                exc,
                exc_info=True,
            )
            self._put(self.ERROR, str(exc))
        finally:
            self._done.set()

    def _normalize_row(self, tap, row: object) -> dict | None:
        import dataclasses

        payload = row if isinstance(row, dict) else {}
        system = payload.get("System")
        processes = payload.get("Processes")
        per_cpu = payload.get("PerCPUUsage")
        system_cpu = payload.get("SystemCPUUsage")

        # sysmontap emits ~2000 raw rows/sec but only refreshes metric blocks
        # once per sample interval; rows without any metric block carry no new
        # data, so ignore them instead of re-emitting cached values.
        if not (
            isinstance(system, (list, tuple))
            or isinstance(system_cpu, dict)
            or isinstance(per_cpu, list)
            or isinstance(processes, dict)
        ):
            return None

        cpu_count = payload.get("EnabledCPUs") or payload.get("CPUCount")
        if isinstance(cpu_count, (int, float)) and cpu_count > 0:
            self._cpu_count = int(cpu_count)

        system_dict: dict = {}
        if isinstance(system, (list, tuple)):
            try:
                system_dict = dataclasses.asdict(tap.system_attributes_cls(*system))
            except Exception:
                system_dict = {}

        process_entries: list[dict] = []
        if isinstance(processes, dict):
            for proc_values in processes.values():
                if not isinstance(proc_values, (list, tuple)):
                    continue
                try:
                    process_entries.append(
                        dataclasses.asdict(tap.process_attributes_cls(*proc_values))
                    )
                except Exception:
                    continue

        if isinstance(per_cpu, list):
            self._last_per_cpu = [p for p in per_cpu if isinstance(p, dict)]
        if isinstance(system_cpu, dict):
            self._last_system_cpu = system_cpu
        if system_dict:
            self._last_system = system_dict
        if process_entries:
            self._last_process_entries = process_entries

        # The System block (carrying CPU + memory + IO counters together) arrives
        # once per sample interval; emit exactly one sample per such frame. Other
        # rows (e.g. Processes-only) only refresh caches above.
        if not system_dict:
            return None

        system_view = self._last_system
        process_view = self._last_process_entries
        per_cpu_view = self._last_per_cpu

        cpu_count = self._cpu_count or len(per_cpu_view)
        cpu = self._extract_cpu_percent(
            self._last_system_cpu, cpu_count, per_cpu_view, process_view
        )
        physical_mem_mb = self._extract_physical_mem_mb(system_view)
        mem_used_mb = self._extract_system_used_mb(system_view)
        net_in = self._extract_counter(system_view, "netBytesIn")
        net_out = self._extract_counter(system_view, "netBytesOut")
        disk_read = self._extract_counter(system_view, "diskBytesRead")
        disk_write = self._extract_counter(system_view, "diskBytesWritten")
        if (
            cpu is None
            and mem_used_mb is None
            and net_in is None
            and net_out is None
            and disk_read is None
            and disk_write is None
        ):
            return None
        sample = {
            "timestamp": time.time(),
            "cpu_percent": cpu,
            "memory_used_mb": mem_used_mb,
            "physical_mem_mb": physical_mem_mb,
            "net_bytes_in": net_in,
            "net_bytes_out": net_out,
            "disk_bytes_read": disk_read,
            "disk_bytes_written": disk_write,
        }
        return sample

    @staticmethod
    def _extract_cpu_percent(
        system_cpu: object,
        cpu_count: int,
        per_cpu: object,
        process_entries: list[dict],
    ) -> float | None:
        # sysmontap CPU loads are percentages summed across cores (0~100*nCores);
        # negative values are uninitialized sentinels (-1) and are ignored. We
        # report device-wide utilization on a 0~100 scale.
        cores = cpu_count if cpu_count and cpu_count > 0 else 1

        # Primary: the SystemCPUUsage aggregate (what pymobiledevice3's own CLI
        # uses), normalized by active core count.
        if isinstance(system_cpu, dict):
            total = system_cpu.get("CPU_TotalLoad")
            if isinstance(total, (int, float)) and total >= 0:
                return max(0.0, min(100.0, float(total) / cores))

        # Fallback: average the per-core CPU_TotalLoad values (each already 0~100).
        if isinstance(per_cpu, list):
            values = [
                float(item["CPU_TotalLoad"])
                for item in per_cpu
                if isinstance(item, dict)
                and isinstance(item.get("CPU_TotalLoad"), (int, float))
                and item["CPU_TotalLoad"] >= 0
            ]
            if values:
                return max(0.0, min(100.0, sum(values) / len(values)))

        # Last resort: sum per-process cpuUsage, normalized by core count.
        cpu_usage_values = [
            float(proc["cpuUsage"])
            for proc in process_entries
            if isinstance(proc, dict)
            and isinstance(proc.get("cpuUsage"), (int, float))
            and proc["cpuUsage"] >= 0
        ]
        if cpu_usage_values:
            return max(0.0, min(100.0, sum(cpu_usage_values) / cores))
        return None

    @staticmethod
    def _extract_physical_mem_mb(system_dict: dict) -> float | None:
        """Total physical memory (MB). ``physMemSize`` is a 16KB-page count."""
        raw = system_dict.get("physMemSize")
        if not isinstance(raw, (int, float)) or raw <= 0:
            return None
        mb = (float(raw) * PerformanceStreamHandle._PAGE_SIZE) / (1024 * 1024)
        return mb if mb > 0 else None

    @staticmethod
    def _extract_system_used_mb(system_dict: dict) -> float | None:
        """System used memory (MB) ≈ iOS "Memory Used": active + wired + compressed.

        Reclaimable inactive/purgeable cache is excluded so the value tracks real
        pressure instead of sitting near the physical ceiling. VM counters are
        16KB-page counts.
        """
        pages = 0.0
        seen = False
        for key in ("vmActiveCount", "vmWireCount", "vmCompressorPageCount"):
            value = system_dict.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                pages += float(value)
                seen = True
        if not seen:
            return None
        mb = (pages * PerformanceStreamHandle._PAGE_SIZE) / (1024 * 1024)
        return mb if mb > 0 else None

    @staticmethod
    def _extract_counter(system_dict: dict, key: str) -> float | None:
        value = system_dict.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)
        return None

    def _put(self, kind: str, payload: object) -> None:
        if self._closed:
            return
        if kind == self.LINE:
            self._samples += 1
        try:
            self.queue.put_nowait((kind, payload))
        except Exception:
            pass

    def close(self) -> None:
        """Stop the stream and wait for coroutine cleanup."""
        self._closed = True
        if self._future and not self._future.done():
            _bg_loop.call_soon_threadsafe(self._future.cancel)
        if not self._done.wait(timeout=3.0):
            logger.warning(
                "PerformanceStreamHandle.close: timed out waiting cleanup"
            )


class ConditionInducerHandle:
    """Connection-scoped DVT Condition Inducer session on the shared loop.

    The induced condition is only active while the DVT connection lives; closing
    the connection (or the handle) makes the device auto-revert. The device also
    enforces a single active condition at a time, so switching profiles means
    "disable then enable". A long-lived background coroutine holds the connection
    open and parks on a stop event; ``apply``/``clear`` run their own coroutines
    against the same captured ``ConditionInducer`` instance on the loop.
    """

    def __init__(self, device: "iOSDevice") -> None:
        self._device = device
        self._ci = None
        self._models: list[dict] = []
        self._active: Optional[dict] = None
        self._error: Optional[Exception] = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._done = threading.Event()
        self._stop_event: Optional[asyncio.Event] = None
        logger.debug("ConditionInducerHandle open: udid=%s", self._device.udid)
        self._future = asyncio.run_coroutine_threadsafe(self._run(), _bg_loop)

    async def _run(self) -> None:
        self._stop_event = asyncio.Event()
        try:
            from pymobiledevice3.services.dvt.instruments.condition_inducer import (
                ConditionInducer,
            )

            async def _op(dvt) -> None:
                async with ConditionInducer(dvt) as ci:
                    self._ci = ci
                    self._models = self._serialize_models(await ci.list())
                    self._ready.set()
                    await self._stop_event.wait()
                    # Explicitly revert and confirm before dropping the connection:
                    # disable is fire-and-forget and some conditions (e.g. thermal)
                    # take ~1s to actually clear, so wait for isActive to settle.
                    try:
                        await self._clear_and_confirm()
                    except Exception:
                        pass

            await self._device._with_dvt(_op)
        except asyncio.CancelledError:
            logger.debug("ConditionInducerHandle._run: cancelled")
        except Exception as exc:
            logger.warning(
                "ConditionInducerHandle._run: error: %s", exc, exc_info=True
            )
            self._error = exc
        finally:
            self._ci = None
            self._ready.set()
            self._done.set()

    @staticmethod
    def _serialize_models(raw: object) -> list[dict]:
        """Flatten sysmon condition groups, dropping internal-only entries."""
        groups: list[dict] = []
        for group in raw or []:
            if not isinstance(group, dict) or group.get("isInternal"):
                continue
            profiles = []
            for prof in group.get("profiles") or []:
                if not isinstance(prof, dict) or not prof.get("identifier"):
                    continue
                profiles.append({
                    "identifier": prof.get("identifier"),
                    "name": prof.get("name") or prof.get("identifier"),
                    "description": prof.get("description") or "",
                })
            if not profiles:
                continue
            groups.append({
                "identifier": group.get("identifier"),
                "name": group.get("name") or group.get("identifier"),
                "is_destructive": bool(group.get("isDestructive")),
                "profiles": profiles,
            })
        return groups

    def wait_ready(self, timeout: float = 45.0) -> Optional[Exception]:
        """Block until models are enumerated or the session fails.

        ``_run``'s ``finally`` always sets ``_ready``, so a wait timeout means the
        session genuinely hung (e.g. a stalled DVT/RSD call). Surface that as a
        timeout error rather than a false success, so the caller closes the handle
        (which cancels the hung task) instead of returning a half-open session.
        """
        if not self._ready.wait(timeout=timeout):
            return TimeoutError("condition inducer open timed out")
        return self._error

    @property
    def models(self) -> list[dict]:
        return self._models

    def state(self) -> Optional[dict]:
        with self._lock:
            return dict(self._active) if self._active else None

    def _find(self, group_id: str, profile_id: str) -> Optional[dict]:
        for group in self._models:
            if group["identifier"] != group_id:
                continue
            for prof in group["profiles"]:
                if prof["identifier"] == profile_id:
                    return {
                        "group": group_id,
                        "group_name": group["name"],
                        "profile": profile_id,
                        "profile_name": prof["name"],
                        "summary": prof.get("description") or prof["name"],
                    }
        return None

    def apply(self, group_id: str, profile_id: str) -> dict:
        """Apply a profile; switches by disabling any active condition first."""
        from .toolkit_api import _ok, _err

        meta = self._find(group_id, profile_id)
        if meta is None:
            return _err(
                "BAD_TARGET",
                f"unknown condition: {group_id}/{profile_id}",
                code="CONDITION_UNKNOWN",
            )
        if self._ci is None:
            return _err(
                "SUBPROCESS",
                "condition inducer not connected",
                code="CONDITION_NOT_READY",
            )
        future = asyncio.run_coroutine_threadsafe(
            self._apply_async(group_id, profile_id), _bg_loop
        )
        try:
            future.result(timeout=30)
        except Exception as exc:
            return _dvt_exc_to_err(exc)
        with self._lock:
            self._active = meta
        logger.info("condition applied: udid=%s %s/%s", self._device.udid, group_id, profile_id)
        return _ok({"state": "active", **meta})

    async def _apply_async(self, group_id: str, profile_id: str) -> None:
        # Single active condition: the device rejects enable while ANY condition is
        # active — including one we did not set (a stale session or another tool).
        # Unconditionally disable+confirm first so enable never hits
        # "A condition is already active"; it is idempotent and fast when none is set.
        await self._clear_and_confirm()
        await self._ci.service.enable_condition_with_identifier_profile_identifier_(
            group_id, profile_id
        )

    async def _clear_and_confirm(self, attempts: int = 20, interval: float = 0.2) -> None:
        """Disable the active condition and wait until the device reports none.

        ``disableActiveCondition`` is fire-and-forget and the device may take ~1s
        to actually revert (notably thermal), so poll ``list`` on the live
        connection until nothing is active before returning.
        """
        if self._ci is None:
            return
        await self._ci.service.disable_active_condition()
        for _ in range(attempts):
            await asyncio.sleep(interval)
            try:
                groups = await self._ci.list()
            except Exception:
                return
            if not any(isinstance(g, dict) and g.get("isActive") for g in groups):
                return
        logger.warning(
            "ConditionInducerHandle: condition still active after disable (udid=%s)",
            self._device.udid,
        )

    def clear(self) -> dict:
        """Stop the active condition; idempotent when nothing is active."""
        from .toolkit_api import _ok

        if self._ci is None or self._active is None:
            with self._lock:
                self._active = None
            return _ok({"state": "inactive", "already_inactive": True})
        future = asyncio.run_coroutine_threadsafe(self._clear_and_confirm(), _bg_loop)
        try:
            future.result(timeout=30)
        except Exception as exc:
            return _dvt_exc_to_err(exc)
        with self._lock:
            self._active = None
        logger.info("condition cleared: udid=%s", self._device.udid)
        return _ok({"state": "inactive"})

    def close(self) -> None:
        """Revert the condition and tear down the held connection."""
        if self._stop_event is not None and not self._done.is_set():
            _bg_loop.call_soon_threadsafe(self._stop_event.set)
        # Cleanup performs a confirm-poll revert (~up to 4s) before disconnecting.
        if not self._done.wait(timeout=8.0):
            if self._future and not self._future.done():
                _bg_loop.call_soon_threadsafe(self._future.cancel)
            logger.warning("ConditionInducerHandle.close: timed out waiting cleanup")
        with self._lock:
            self._active = None


class NetworkStreamHandle:
    """Live network monitor backed by DVT NetworkMonitor on the shared loop.

    Event-driven (no device sample interval): the device pushes interface /
    connection-detection / connection-update events. The handle maintains a
    thread-safe model — connections keyed by ``connection_serial`` plus a global
    cumulative rx/tx counter for throughput — that the UI polls via ``snapshot``.
    Connections are pruned to a ring-buffer cap and a 10-minute window. Per-flow
    pid is not available on modern iOS (always -2), so there is no process model.
    """

    WINDOW_S = 600.0
    MAX_CONNS = 4000

    def __init__(self, device: "iOSDevice") -> None:
        self._device = device
        self._closed = False
        self._error: Optional[Exception] = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._done = threading.Event()
        self._conns: dict = {}
        self._ifaces: dict = {}
        self._cum_rx = 0.0
        self._cum_tx = 0.0
        self._events = 0
        self._dropped = 0
        self._prune_counter = 0
        logger.debug("NetworkStreamHandle open: udid=%s", self._device.udid)
        self._future = asyncio.run_coroutine_threadsafe(self._run(), _bg_loop)

    async def _run(self) -> None:
        try:
            from pymobiledevice3.services.dvt.instruments.network_monitor import (
                ConnectionDetectionEvent,
                ConnectionUpdateEvent,
                InterfaceDetectionEvent,
                NetworkMonitor,
            )

            async def _op(dvt) -> None:
                async with NetworkMonitor(dvt) as nm:
                    self._ready.set()
                    async for event in nm:
                        if self._closed:
                            break
                        if event is None:
                            continue
                        try:
                            self._handle_event(
                                event,
                                InterfaceDetectionEvent,
                                ConnectionDetectionEvent,
                                ConnectionUpdateEvent,
                            )
                        except Exception:
                            self._dropped += 1

            await self._device._with_dvt(_op)
        except asyncio.CancelledError:
            logger.debug("NetworkStreamHandle._run: cancelled (events=%s)", self._events)
        except Exception as exc:
            logger.warning("NetworkStreamHandle._run: error: %s", exc, exc_info=True)
            self._error = exc
        finally:
            self._ready.set()
            self._done.set()

    @staticmethod
    def _proto(kind: object) -> str:
        # Verified on-device: kind 1 = TCP, 2 = UDP.
        return {1: "TCP", 2: "UDP"}.get(kind, "unknown")

    @staticmethod
    def _endpoint(addr: object) -> tuple[str, int]:
        try:
            ip = str(addr.data.address)
            port = int(addr.port)
            return ip, port
        except Exception:
            return "unknown", 0

    @staticmethod
    def _direction(local_port: int, remote_port: int) -> str:
        # No explicit field; derive heuristically (device usually initiates).
        if not remote_port:
            return "unknown"
        if remote_port <= local_port:
            return "out"
        return "in"

    @staticmethod
    def _blank_record(serial: object, now: float) -> dict:
        return {
            "serial": serial, "proto": "unknown", "direction": "unknown",
            "local": "unknown", "remote": "unknown", "remote_ip": "unknown",
            "iface": "unknown", "rx_bytes": 0.0, "tx_bytes": 0.0,
            "rx_pkts": 0, "tx_pkts": 0, "retx": 0, "dups": 0,
            "avg_rtt": 0, "first_ts": now, "last_ts": now, "seen": False,
        }

    def _handle_event(self, event, IfaceCls, DetCls, UpdCls) -> None:
        now = time.time()
        self._events += 1
        if isinstance(event, IfaceCls):
            with self._lock:
                self._ifaces[event.interface_index] = event.name
            return
        if isinstance(event, DetCls):
            lip, lport = self._endpoint(event.local_address)
            rip, rport = self._endpoint(event.remote_address)
            with self._lock:
                rec = self._blank_record(event.serial_number, now)
                rec.update(
                    proto=self._proto(event.kind),
                    direction=self._direction(lport, rport),
                    local=f"{lip}:{lport}",
                    remote=f"{rip}:{rport}",
                    remote_ip=rip,
                    iface=self._ifaces.get(event.interface_index, str(event.interface_index)),
                )
                self._conns[event.serial_number] = rec
                self._prune_locked(now)
            return
        if isinstance(event, UpdCls):
            with self._lock:
                rec = self._conns.get(event.connection_serial)
                if rec is None:
                    rec = self._conns[event.connection_serial] = self._blank_record(
                        event.connection_serial, now
                    )
                # Verified on-device: update fields are PER-INTERVAL deltas, and a
                # connection's FIRST update carries its pre-monitoring accumulated
                # total (can be hundreds of MB). Seed the first update as a baseline
                # (counts toward the connection total but NOT live throughput), then
                # accumulate subsequent deltas.
                d_rx = float(getattr(event, "rx_bytes", 0) or 0)
                d_tx = float(getattr(event, "tx_bytes", 0) or 0)
                d_rxp = int(getattr(event, "rx_packets", 0) or 0)
                d_txp = int(getattr(event, "tx_packets", 0) or 0)
                d_retx = int(getattr(event, "tx_retx", 0) or 0)
                d_dups = int(getattr(event, "rx_dups", 0) or 0)
                if rec.get("seen"):
                    self._cum_rx += max(0.0, d_rx)
                    self._cum_tx += max(0.0, d_tx)
                    rec["rx_bytes"] += d_rx
                    rec["tx_bytes"] += d_tx
                    rec["rx_pkts"] += d_rxp
                    rec["tx_pkts"] += d_txp
                    rec["retx"] += d_retx
                    rec["dups"] += d_dups
                else:
                    rec["seen"] = True
                    rec["rx_bytes"] = d_rx
                    rec["tx_bytes"] = d_tx
                    rec["rx_pkts"] = d_rxp
                    rec["tx_pkts"] = d_txp
                    rec["retx"] = d_retx
                    rec["dups"] = d_dups
                rec["avg_rtt"] = int(getattr(event, "avg_rtt", 0) or 0)
                rec["last_ts"] = now
                self._prune_locked(now)

    def _prune_locked(self, now: float) -> None:
        # Amortized prune: scanning all connections every event is O(n^2) under a
        # connection storm, so only prune when over the hard cap or every N events
        # (for window expiry). When over the cap, drop to a low-water mark so the
        # next prune is N events away instead of every event.
        self._prune_counter += 1
        over = len(self._conns) > self.MAX_CONNS
        if not over and self._prune_counter < 512:
            return
        self._prune_counter = 0
        cutoff = now - self.WINDOW_S
        kept = [r for r in self._conns.values() if r["last_ts"] >= cutoff]
        if len(kept) > self.MAX_CONNS:
            kept.sort(key=lambda r: r["last_ts"])
            target = int(self.MAX_CONNS * 0.9)
            self._dropped += len(kept) - target
            kept = kept[len(kept) - target:]
        if len(kept) != len(self._conns):
            self._conns = {r["serial"]: r for r in kept}

    def wait_ready(self, timeout: float = 45.0) -> Optional[Exception]:
        """Block until monitoring started, or surface a timeout/error."""
        if not self._ready.wait(timeout=timeout):
            return TimeoutError("network monitor open timed out")
        return self._error

    def snapshot(self) -> dict:
        """Thread-safe copy of the current model for UI rendering."""
        with self._lock:
            return {
                "running": not self._closed and self._error is None,
                "cum_rx": self._cum_rx,
                "cum_tx": self._cum_tx,
                "timestamp": time.time(),
                "connections": [dict(r) for r in self._conns.values()],
                "dropped": self._dropped,
            }

    def close(self) -> None:
        """Stop monitoring and tear down the connection."""
        self._closed = True
        if self._future and not self._future.done():
            _bg_loop.call_soon_threadsafe(self._future.cancel)
        if not self._done.wait(timeout=3.0):
            logger.warning("NetworkStreamHandle.close: timed out waiting cleanup")


class WebInspectorBridgeHandle:
    """Embedded CDP (Chrome DevTools Protocol) bridge for WebInspector.

    Runs pymobiledevice3's CDP FastAPI app under a uvicorn server on a dedicated
    thread/loop (the server owns its loop, so it does not use ``_bg_loop``). The
    app's lifespan connects a ``WebinspectorService`` over the device's lockdown
    provider (RSD/tunnel on 17+). ``close()`` flips uvicorn's ``should_exit`` so
    the port is released. WebInspector is lockdown-only — no DDI required.
    """

    def __init__(self, device: "iOSDevice", host: str = "127.0.0.1", port: int = 9222) -> None:
        self._device = device
        self.host = host
        self.port = port
        self._server = None
        self._error: Optional[Exception] = None
        self._done = threading.Event()
        logger.debug("WebInspectorBridgeHandle open: udid=%s %s:%s", device.udid, host, port)
        self._thread = threading.Thread(target=self._run, daemon=True, name="cdp-bridge")
        self._thread.start()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except Exception as exc:
            logger.warning("WebInspectorBridgeHandle._run: error: %s", exc, exc_info=True)
            self._error = exc
        finally:
            self._done.set()
            try:
                loop.close()
            except Exception:
                pass

    async def _serve(self) -> None:
        import uvicorn

        from pymobiledevice3.services.web_protocol.cdp_server import app
        from pymobiledevice3.services.webinspector import WebinspectorService

        async with self._device._lockdown_provider() as provider:
            # The CDP app's lifespan calls inspector.connect() on startup.
            app.state.inspector = WebinspectorService(lockdown=provider)
            config = uvicorn.Config(
                app, host=self.host, port=self.port,
                log_level="error", ws="wsproto", loop="none",
            )
            self._server = uvicorn.Server(config)
            await self._server.serve()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def wait_ready(self, timeout: float = 20.0) -> Optional[Exception]:
        """Block until the CDP server is serving, or surface an error/timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._error is not None:
                return self._error
            if self._server is not None and getattr(self._server, "started", False):
                return None
            if self._done.is_set():
                # serve() returned before 'started' → startup failed
                return self._error or RuntimeError("CDP bridge failed to start")
            time.sleep(0.1)
        return TimeoutError("CDP bridge start timed out")

    def close(self) -> None:
        """Stop the CDP server and release the port."""
        if self._server is not None:
            self._server.should_exit = True
        if not self._done.wait(timeout=8.0):
            logger.warning("WebInspectorBridgeHandle.close: timed out waiting cleanup")


class PcapStreamHandle:
    """Live packet capture backed by pcapd over usbmux, writing a .pcap file.

    pcapd MUST go over usbmux lockdown — Apple prohibits it over RSD/tunnel
    (``ServiceProhibited``), so this needs neither tunnel nor DDI. A tee generator
    feeds each packet to ``write_to_pcap`` (pcapng on disk) while recording a
    bounded rolling summary + counters that the UI polls via ``snapshot``. Capture
    auto-stops on any limit (packets / bytes / seconds); ``close()`` cancels the
    background task to interrupt an idle ``watch`` and finalize the file.
    """

    MAX_SUMMARY = 500

    def __init__(self, device: "iOSDevice", out_path: str, process: "Optional[str]" = None,
                 interface: "Optional[str]" = None, max_packets: int = 100000,
                 max_bytes: int = 50 * 1024 * 1024, max_seconds: int = 600) -> None:
        self._device = device
        self._out_path = out_path
        self._process = process or None
        self._interface = interface or None
        self._max_packets = max_packets
        self._max_bytes = max_bytes
        self._max_seconds = max_seconds
        self._closed = False
        self._error: Optional[Exception] = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._done = threading.Event()
        self._packets = 0
        self._bytes = 0
        self._start_ts = 0.0
        self._stopped_reason: Optional[str] = None
        self._summary: "deque[dict]" = deque(maxlen=self.MAX_SUMMARY)
        logger.debug("PcapStreamHandle open: udid=%s out=%s", device.udid, out_path)
        self._future = asyncio.run_coroutine_threadsafe(self._run(), _bg_loop)

    async def _run(self) -> None:
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.pcapd import PcapdService

            lockdown = await create_using_usbmux(serial=self._device.udid, autopair=False)
            async with lockdown:
                svc = PcapdService(lockdown=lockdown)
                self._start_ts = time.time()
                with open(self._out_path, "wb") as fh:
                    self._ready.set()
                    await svc.write_to_pcap(fh, self._tee(svc))
        except asyncio.CancelledError:
            logger.debug("PcapStreamHandle._run: cancelled (packets=%s)", self._packets)
        except Exception as exc:
            logger.warning("PcapStreamHandle._run: error: %s", exc, exc_info=True)
            self._error = exc
        finally:
            self._ready.set()
            self._done.set()

    async def _tee(self, svc):
        async for pkt in svc.watch(
            packets_count=-1, process=self._process, interface_name=self._interface,
        ):
            if self._closed:
                return
            length = len(pkt.data)
            try:
                ts = float(pkt.seconds) + float(pkt.microseconds) / 1_000_000
            except Exception:
                ts = time.time()
            with self._lock:
                self._packets += 1
                self._bytes += length
                self._summary.append({
                    "ts": ts,
                    "comm": getattr(pkt, "comm", "") or "unknown",
                    "pid": getattr(pkt, "pid", None),
                    "iface": getattr(pkt, "interface_name", "") or "unknown",
                    "proto": getattr(getattr(pkt, "protocol_family", None), "name", "unknown"),
                    "length": length,
                })
            yield pkt
            if self._limit_reached():
                self._stopped_reason = "limit"
                return

    def _limit_reached(self) -> bool:
        if self._max_packets and self._packets >= self._max_packets:
            return True
        if self._max_bytes and self._bytes >= self._max_bytes:
            return True
        if self._max_seconds and (time.time() - self._start_ts) >= self._max_seconds:
            return True
        return False

    def wait_ready(self, timeout: float = 30.0) -> Optional[Exception]:
        """Block until capture started (file open) or an error surfaced."""
        if not self._ready.wait(timeout=timeout):
            return TimeoutError("pcap capture start timed out")
        return self._error

    def snapshot(self) -> dict:
        """Thread-safe copy of capture counters + recent packet summary."""
        with self._lock:
            return {
                "running": not self._done.is_set() and self._error is None,
                "packets": self._packets,
                "bytes": self._bytes,
                "elapsed": (time.time() - self._start_ts) if self._start_ts else 0.0,
                "out_path": self._out_path,
                "stopped_reason": self._stopped_reason,
                "summary": list(self._summary),
            }

    def close(self) -> None:
        """Stop capture, cancel the background task and finalize the file."""
        self._closed = True
        if self._future and not self._future.done():
            _bg_loop.call_soon_threadsafe(self._future.cancel)
        if not self._done.wait(timeout=5.0):
            logger.warning("PcapStreamHandle.close: timed out waiting cleanup")


_oslog_level_patched = False


def _patch_oslog_level_enum() -> None:
    """Make pymobiledevice3's ``SyslogLogLevel`` tolerate unknown level values.

    The bundled ``parse_syslog_entry`` does ``SyslogLogLevel(level)`` on a raw
    device byte, but the enum only covers a handful of known values. Devices can
    report levels outside that set (e.g. 4), which raises ``ValueError`` inside
    the ``syslog()`` async generator and kills the whole stream after 0 lines.
    Install a ``_missing_`` hook so an unknown value yields a synthetic member
    (numeric value preserved, name ``LEVEL_<n>``) instead of crashing.
    """
    global _oslog_level_patched
    if _oslog_level_patched:
        return
    try:
        from pymobiledevice3.services.os_trace import SyslogLogLevel

        if getattr(SyslogLogLevel, "_cabledios_tolerant", False):
            _oslog_level_patched = True
            return

        @classmethod
        def _missing_(cls, value):  # type: ignore[no-redef]
            if not isinstance(value, int):
                return None
            pseudo = int.__new__(cls, value)
            pseudo._name_ = f"LEVEL_{value}"
            pseudo._value_ = value
            return pseudo

        SyslogLogLevel._missing_ = _missing_
        SyslogLogLevel._cabledios_tolerant = True
        _oslog_level_patched = True
    except Exception as exc:  # pragma: no cover - defensive, never block streaming
        logger.debug("_patch_oslog_level_enum: skipped (%s)", exc)


def _oslog_entry_to_dict(entry) -> dict:
    """Flatten an os_trace SyslogEntry into a structured dict for the UI.

    Carries the discrete columns the oslog table renders plus a pre-formatted
    one-line ``display`` string for text export. ``subsystem``/``category`` come
    from the optional ``label`` and may be empty.
    """
    ts = getattr(entry, "timestamp", None)
    if ts is not None and hasattr(ts, "isoformat"):
        ts_str = ts.isoformat()
    else:
        ts_str = str(ts) if ts is not None else ""
    label = getattr(entry, "label", None)
    level = getattr(entry, "level", None)
    level_str = getattr(level, "name", None) or (str(level) if level is not None else "")
    return {
        "pid": getattr(entry, "pid", None),
        "timestamp": ts_str,
        "level": level_str,
        "image_name": getattr(entry, "image_name", "") or "",
        "filename": getattr(entry, "filename", "") or "",
        "message": getattr(entry, "message", "") or "",
        "subsystem": getattr(label, "subsystem", "") if label is not None else "",
        "category": getattr(label, "category", "") if label is not None else "",
        "display": _format_oslog_entry(entry),
    }


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
        self._config_signature: tuple[str, int, int] | None = None

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
        wda_bundle_id = config.get("wda_bundle_id", DEFAULT_WDA_BUNDLE_ID)
        wda_device_port = int(config.get("wda_port", DEFAULT_WDA_PORT))
        wda_mjpeg_port = int(config.get("wda_mjpeg_port", DEFAULT_WDA_MJPEG_PORT))
        config_signature = (wda_bundle_id, wda_device_port, wda_mjpeg_port)

        devices = await usbmux.list_devices()
        current_udids = {dev.serial for dev in devices if dev.is_usb}

        with self._lock:
            config_changed = self._config_signature != config_signature
            stale_udids = set(self._devices) - current_udids
            if config_changed:
                stale_udids |= set(self._devices)
            for udid in stale_udids:
                device = self._devices.pop(udid)
                device._forward_task.cancel()
                if device._mjpeg_forward_task is not None:
                    device._mjpeg_forward_task.cancel()
                # Tear down the WDA XCUITest session so the runner exits cleanly.
                if device._wda_task is not None:
                    device._wda_task.cancel()

            new_udids = current_udids - set(self._devices)
            self._config_signature = config_signature

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
            forward_task = _launch_forward(udid, local_port, wda_device_port)

            mjpeg_local_port = _find_free_port(local_port + 1)
            mjpeg_forward_task = _launch_forward(
                udid, mjpeg_local_port, wda_mjpeg_port
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
