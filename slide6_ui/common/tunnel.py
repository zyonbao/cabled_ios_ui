"""tunnel.py — detect and (with system authorization) launch the iOS 17+ XPC tunnel.

iOS 17+ devices require a root-run XPC tunnel daemon (`ios_toolkit.tunneld_main`)
before WDA can start; lower versions do not need it. The desktop console can
detect whether the tunnel port is alive and, if not, launch the daemon with
administrator privileges via the native macOS authorization dialog.

The tunneld entry point is resolved per runtime environment so the console works
both as source and as a Nuitka-frozen app bundle:
  - Frozen (Nuitka multidist): run the bundled ``cabled_ios_tunnel`` executable that
    sits next to the app binary in ``Contents/MacOS/`` (the multidist binary
    dispatches to the tunneld entry by its ``cabled_ios_tunnel`` basename).
  - Development: run the project interpreter with ``-m ios_toolkit.tunneld_main``.

Security: the command executed under elevation is built entirely from fixed,
internally-resolved paths (no UI/external input is interpolated), the target
binary/script path is validated to exist, the daemon binds only to 127.0.0.1,
and no credentials are ever passed to it.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# The tunneld port currently used by ios_toolkit (see device.TUNNELD_URL).
# Centralized here so a future change can make it configurable.
TUNNELD_HOST = "127.0.0.1"
TUNNELD_PORT = 49151

# Log file for the elevated daemon's stdout/stderr (debug aid).
_TUNNELD_LOG = "/tmp/ios_tunneld.log"


def is_tunnel_running(timeout: float = 1.0) -> bool:
    """Return True if something is listening on the tunneld port."""
    try:
        with socket.create_connection((TUNNELD_HOST, TUNNELD_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def ios_major(os_version: str) -> int:
    """Parse the major iOS version from an os_version string like '17.2.1'.

    Mirrors ios_toolkit.device._ios_major_version. On parse failure returns 0;
    callers treat 0 conservatively (i.e. assume a tunnel may be required).
    """
    try:
        return int(str(os_version).split(".")[0])
    except (ValueError, IndexError, AttributeError):
        return 0


def needs_tunnel(os_version: str) -> bool:
    """iOS 17+ needs the tunnel; unparseable versions are treated as needing it."""
    major = ios_major(os_version)
    return major == 0 or major >= 17


def _repo_root() -> Path:
    """Directory containing the ios_toolkit / slide6_ui packages.

    Resolved by walking up from this module to the nearest ancestor that holds
    the ``ios_toolkit`` package, so it stays correct regardless of how deeply
    this module is nested within slide6_ui.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "ios_toolkit").is_dir():
            return parent
    # Fallback for unexpected layouts: slide6_ui/common/tunnel.py -> repo root.
    return here.parents[2]


def _interpreter() -> Path:
    """Prefer the project .venv interpreter; fall back to the running one.

    Running under `osascript ... with administrator privileges` executes as root
    with a bare environment, so an absolute interpreter path that already has
    pymobiledevice3 installed is required.
    """
    venv_py = _repo_root() / ".venv" / "bin" / "python"
    if venv_py.exists():
        return venv_py
    return Path(sys.executable)


def _is_frozen() -> bool:
    """True when running as a Nuitka-compiled / frozen bundle.

    Nuitka injects a module-level ``__compiled__`` global into every compiled
    module; ``sys.frozen`` covers other freezers as a fallback signal.
    """
    return "__compiled__" in globals() or bool(getattr(sys, "frozen", False))


def _bundled_tunneld_binary() -> Path:
    """Path to the bundled cabled_ios_tunnel executable next to the app binary.

    In a Nuitka macOS app bundle the main binary lives in ``Contents/MacOS/``;
    the multidist ``cabled_ios_tunnel`` entry is placed alongside it.
    """
    return Path(sys.executable).resolve().parent / "cabled_ios_tunnel"


def _tunneld_command() -> list[str]:
    """Resolve the argv used to launch tunneld for the current environment.

    Frozen: the bundled ``cabled_ios_tunnel`` binary. Development: the project
    interpreter running ``-m ios_toolkit.tunneld_main``. All tokens are fixed,
    internally-resolved values — no external/UI input is ever included.
    """
    if _is_frozen():
        return [str(_bundled_tunneld_binary())]
    return [str(_interpreter()), "-m", "ios_toolkit.tunneld_main"]


def _tunneld_entry_exists() -> bool:
    """Validate the tunneld entry point exists before prompting for auth.

    Frozen builds check the bundled binary; source checkouts check the
    ``tunneld_main.py`` module file.
    """
    if _is_frozen():
        return _bundled_tunneld_binary().exists()
    return (_repo_root() / "ios_toolkit" / "tunneld_main.py").exists()


def _applescript_quote(text: str) -> str:
    """Escape a string for embedding inside an AppleScript double-quoted literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def launch_tunneld(timeout: float = 30.0) -> bool:
    """Launch tunneld as root via the native authorization dialog.

    tunneld runs in the foreground under the elevated shell, so `do shell script`
    stays blocked for the daemon's whole lifetime. To avoid hanging, the osascript
    process is started without waiting on it: readiness is confirmed by polling the
    port, and user cancellation is detected when osascript exits before the port
    comes up. The osascript/daemon keep running in the background afterward (the
    daemon is a normal background process, not a self-detached daemon); it is
    stopped on request via stop_tunneld. The shell command is composed only of
    fixed, validated paths.
    """
    # Validate the tunneld entry is present before prompting for a password.
    if not _tunneld_entry_exists():
        logger.warning("tunneld entry point not found; cannot launch tunnel")
        return False

    logger.info("launching XPC tunnel (elevated); waiting up to %.0fs", timeout)
    cmd = _tunneld_command()
    # Quote the executable path (it may contain spaces, e.g. inside an app
    # bundle); the remaining tokens are fixed literals (e.g. "-m", module name).
    # The dev path additionally needs `cd <repo>` so `-m` resolves the package.
    exe_part = '"%s"' % cmd[0]
    rest_part = (" " + " ".join(cmd[1:])) if len(cmd) > 1 else ""
    prefix = "" if _is_frozen() else f'cd "{_repo_root()}" && '
    shell_cmd = (
        f"{prefix}{exe_part}{rest_part} "
        f'</dev/null >"{_TUNNELD_LOG}" 2>&1'
    )
    applescript = (
        f'do shell script "{_applescript_quote(shell_cmd)}" '
        f"with administrator privileges"
    )
    try:
        # Do not wait on osascript: it blocks while the foreground daemon runs.
        # stdout/stderr go to DEVNULL so a full pipe buffer can never deadlock it.
        proc = subprocess.Popen(
            ["osascript", "-e", applescript],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.error("failed to start osascript for tunnel launch: %s", exc)
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_tunnel_running(timeout=0.3):
            logger.info("XPC tunnel is up")
            return True
        if proc.poll() is not None:
            # osascript exited before the tunnel came up: cancelled or failed.
            up = is_tunnel_running(timeout=0.3)
            logger.warning("tunnel launch ended early (cancelled/failed); up=%s", up)
            return up
        time.sleep(0.3)
    logger.warning("tunnel launch timed out after %.0fs", timeout)
    return is_tunnel_running(timeout=0.3)


def restart_tunneld(timeout: float = 30.0) -> bool:
    """Stop and relaunch tunneld so the RSD service list is re-enumerated.

    iOS 17+ developer services (e.g. ``com.apple.dt.testmanagerd.remote``) are
    enumerated into a tunnel session's RSD service list at tunnel-establishment
    time. A tunnel created before the DDI was mounted therefore never exposes
    them; restarting forces a fresh handshake that picks up the now-available
    services. Both stop and relaunch run under the native admin authorization
    (tunneld is root); a failing stop is non-fatal (the port may already be
    free). Returns True if the tunnel is up again afterwards.
    """
    logger.info("restarting XPC tunnel to refresh RSD developer services")
    if not stop_tunneld():
        # Non-fatal: nothing listening, or the user/auth declined the kill. We
        # still attempt a relaunch and judge success by the port coming up.
        logger.warning("restart: stop_tunneld did not confirm; attempting relaunch anyway")
    return launch_tunneld(timeout=timeout)


def stop_tunneld() -> bool:
    """Stop the tunneld process with administrator privileges.

    The daemon runs as root, so a non-privileged ``lsof`` cannot see its socket;
    the port lookup and kill therefore run together inside the elevated shell
    (``lsof`` under root resolves the listener). tunneld does not reliably honor
    SIGTERM, so this escalates to SIGKILL if the process lingers. Returns True if
    the command was authorized and run.
    """
    kill_cmd = (
        f"PIDS=$(lsof -ti tcp:{TUNNELD_PORT}); "
        f'if [ -n "$PIDS" ]; then kill $PIDS 2>/dev/null; sleep 1; '
        f"PIDS2=$(lsof -ti tcp:{TUNNELD_PORT}); "
        f'if [ -n "$PIDS2" ]; then kill -9 $PIDS2; fi; fi'
    )
    applescript = (
        f'do shell script "{_applescript_quote(kill_cmd)}" '
        f"with administrator privileges"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
