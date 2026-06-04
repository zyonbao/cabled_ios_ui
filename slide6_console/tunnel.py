"""tunnel.py — detect and (with system authorization) launch the iOS 17+ XPC tunnel.

iOS 17+ devices require a root-run XPC tunnel daemon (`executor_ios.tunneld_main`)
before WDA can start; lower versions do not need it. The desktop console can
detect whether the tunnel port is alive and, if not, launch the daemon with
administrator privileges via the native macOS authorization dialog.

Security: the command executed under elevation is built entirely from fixed,
internally-resolved paths (no UI/external input is interpolated), the target
script path is validated to exist, the daemon binds only to 127.0.0.1, and no
credentials are ever passed to it.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

# The tunneld port currently used by executor_ios (see device.TUNNELD_URL).
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

    Mirrors executor_ios.device._ios_major_version. On parse failure returns 0;
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
    """Directory containing the executor_ios / slide6_console packages."""
    return Path(__file__).resolve().parent.parent


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
    root = _repo_root()
    interpreter = _interpreter()
    # Validate the script entry is present before prompting for a password.
    if not (root / "executor_ios" / "tunneld_main.py").exists():
        return False

    shell_cmd = (
        f'cd "{root}" && '
        f'"{interpreter}" -m executor_ios.tunneld_main '
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
    except OSError:
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_tunnel_running(timeout=0.3):
            return True
        if proc.poll() is not None:
            # osascript exited before the tunnel came up: cancelled or failed.
            return is_tunnel_running(timeout=0.3)
        time.sleep(0.3)
    return is_tunnel_running(timeout=0.3)


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
