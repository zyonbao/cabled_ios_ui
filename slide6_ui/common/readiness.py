"""readiness.py — unified device-readiness precheck for DVT / WDA features.

「开发者工具」and「键鼠操作」both depend on a version-specific set of
preconditions before their DVT / WDA capabilities work:

  - iOS 17+: an XPC tunnel must be up, the DeveloperDiskImage must be mounted,
    and the target RSD developer service (``com.apple.dt.testmanagerd.remote``)
    must be enumerated in the tunnel session. A tunnel established *before* a
    late DDI mount has a stale RSD list missing that service — hence the third
    check beyond tunnel + DDI.
  - iOS < 17: only the DeveloperDiskImage must be mounted (no tunnel / RSD).

This module is pure decision logic plus an optional blocking probe; it never
shows UI. Callers decide how to present the result (disable a button + tooltip,
a status line, or a dialog). Blocking probes MUST be dispatched off the GUI
thread (e.g. via ``AsyncRunner``).
"""

from __future__ import annotations

from dataclasses import dataclass

from ios_toolkit import toolkit_api as api

from .. import i18n
from . import tunnel

# Which precondition is missing (None when ready). Stable keys for callers.
MISSING_TUNNEL = "tunnel"
MISSING_DDI = "ddi"
MISSING_RSD = "rsd"

# The RSD developer service WDA / keyboard-mouse needs on iOS 17+.
TESTMANAGERD_REMOTE = "com.apple.dt.testmanagerd.remote"

# Stable i18n keys for actionable guidance per missing precondition.
_GUIDANCE_KEY = {
    MISSING_TUNNEL: "readiness.missing_tunnel",
    MISSING_DDI: "readiness.missing_ddi",
    MISSING_RSD: "readiness.missing_rsd",
}


def _guidance(missing: str) -> str:
    """Localized guidance for a missing precondition (resolved at call time)."""
    return i18n.t(_GUIDANCE_KEY[missing])


@dataclass(frozen=True)
class Readiness:
    """Result of a readiness check.

    ``ready`` is True only when every applicable precondition is satisfied.
    ``missing`` names the first failing precondition (one of the MISSING_* keys)
    or None when ready. ``message`` is actionable, localized guidance for the UI.
    """

    ready: bool
    missing: "str | None"
    message: str


def _missing(key: str) -> Readiness:
    return Readiness(False, key, _guidance(key))


def _ready() -> Readiness:
    return Readiness(True, None, i18n.t("readiness.ready"))


def _needs_tunnel(os_version: str) -> bool:
    return tunnel.needs_tunnel(os_version)


def evaluate(
    os_version: str,
    *,
    tunnel_running: bool,
    ddi_mounted: bool,
    rsd_ok: bool,
) -> Readiness:
    """Decide readiness from already-known precondition states (pure, no I/O).

    Use this when the caller already tracks the relevant states (e.g. the
    developer-tools tab knows ``ddi_mounted`` and its DVT-ready flag) so no extra
    device round-trips are needed. ``rsd_ok`` is ignored for iOS < 17.
    """
    if _needs_tunnel(os_version):
        if not tunnel_running:
            return _missing(MISSING_TUNNEL)
        if not ddi_mounted:
            return _missing(MISSING_DDI)
        if not rsd_ok:
            return _missing(MISSING_RSD)
        return _ready()
    # iOS < 17: DDI mount is the only gate.
    if not ddi_mounted:
        return _missing(MISSING_DDI)
    return _ready()


def probe(target: str, os_version: str, *, known_mounted: "bool | None" = None) -> Readiness:
    """Blocking readiness probe filling unknown states via the toolkit + tunnel.

    MUST run off the GUI thread. ``known_mounted`` lets a caller that already
    knows the mount state skip the ``ddi_status`` query (which would otherwise hit
    the device-side mounter — unresponsive right after a fresh mount).
    """
    needs_tunnel = _needs_tunnel(os_version)
    tunnel_running = tunnel.is_tunnel_running() if needs_tunnel else False

    # Short-circuit: on iOS 17+ a missing tunnel makes DDI/RSD moot.
    if needs_tunnel and not tunnel_running:
        return _missing(MISSING_TUNNEL)

    ddi_mounted = known_mounted
    if ddi_mounted is None:
        status = api.ddi_status(target)
        ddi_mounted = bool(status.get("ok") and status.get("data", {}).get("mounted"))
    if not ddi_mounted:
        return _missing(MISSING_DDI)

    rsd_ok = True
    if needs_tunnel:
        res = api.rsd_service_available(target, TESTMANAGERD_REMOTE)
        if res.get("ok"):
            rsd_ok = bool(res.get("data", {}).get("available"))
        else:
            # Inconclusive probe (timeout / handshake error under load) — do NOT
            # treat as "RSD missing": tunnel + DDI are already confirmed up, so a
            # false negative here would wrongly tell the user to restart. Give the
            # benefit of the doubt; a genuinely missing service still answers
            # ok=True with available=False above.
            rsd_ok = True

    return evaluate(
        os_version,
        tunnel_running=tunnel_running,
        ddi_mounted=ddi_mounted,
        rsd_ok=rsd_ok,
    )
