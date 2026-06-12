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
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

# The tunneld port used by ios_toolkit (see device._tunneld_url()). The host is
# fixed to loopback (the daemon must never be reachable off-box); only the port
# and the debug log path are user-configurable via Preferences.
TUNNELD_HOST = "127.0.0.1"
DEFAULT_TUNNELD_PORT = 49151

# Log file for the elevated daemon's stdout/stderr (debug aid).
DEFAULT_TUNNELD_LOG = "/tmp/ios_tunneld.log"

# QSettings keys (resolved against the app-level org/app set in app.py, so the
# default QSettings() constructor reads the same store the Preferences UI uses).
TUNNEL_PORT_KEY = "settings/tunnel_port"
TUNNEL_LOG_FILE_KEY = "settings/tunnel_log_file"

# Environment variable bridging the configured port to ios_toolkit.device, which
# stays free of any Qt/QSettings dependency. Set by apply_tunnel_env() at startup
# and whenever the port changes in Preferences.
TUNNELD_PORT_ENV = "IOS_TUNNELD_PORT"


def get_tunnel_port() -> int:
    """Return the configured tunneld port, falling back to the default.

    Invalid or out-of-range stored values are ignored so a corrupt setting can
    never break tunnel detection/launch.
    """
    raw = QSettings().value(TUNNEL_PORT_KEY, DEFAULT_TUNNELD_PORT)
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TUNNELD_PORT
    if not (1 <= port <= 65535):
        return DEFAULT_TUNNELD_PORT
    return port


def get_tunnel_log_file() -> str:
    """Return the configured tunneld log-file path, falling back to the default."""
    value = QSettings().value(TUNNEL_LOG_FILE_KEY, "", type=str) or ""
    return value.strip() or DEFAULT_TUNNELD_LOG


def apply_tunnel_env() -> None:
    """Publish the configured port to ios_toolkit via an environment variable.

    Called at startup and after the port changes so the in-process device
    manager queries the same tunneld the desktop UI launches.
    """
    os.environ[TUNNELD_PORT_ENV] = str(get_tunnel_port())


def is_tunnel_running(timeout: float = 1.0) -> bool:
    """Return True if something is listening on the tunneld port."""
    try:
        with socket.create_connection((TUNNELD_HOST, get_tunnel_port()), timeout=timeout):
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
    interpreter running ``-m ios_toolkit.tunneld_main``. The only non-fixed token
    is ``--port <n>``, where ``n`` is the validated integer from get_tunnel_port()
    (range-checked, never a raw string), so no free-form external input is ever
    interpolated into the elevated command.
    """
    port_args = ["--port", str(get_tunnel_port())]
    if _is_frozen():
        return [str(_bundled_tunneld_binary()), *port_args]
    return [str(_interpreter()), "-m", "ios_toolkit.tunneld_main", *port_args]


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


def _foreground_tunneld_command() -> str:
    """Build the shell command that runs tunneld in the FOREGROUND.

    The daemon runs in the foreground so the elevated ``do shell script`` stays
    blocked for its whole lifetime — this is what keeps the root daemon alive (a
    backgrounded ``nohup ... &`` child is reaped by the privileged helper the
    moment ``do shell script`` returns, so it must NOT be backgrounded). All
    tokens are fixed, internally-resolved paths — no external/UI input.
    """
    cmd = _tunneld_command()
    # Quote the executable path (it may contain spaces, e.g. inside an app
    # bundle); the remaining tokens are fixed literals plus the validated port.
    # The dev path additionally needs `cd <repo>` so `-m` resolves the package.
    exe_part = '"%s"' % cmd[0]
    rest_part = (" " + " ".join(cmd[1:])) if len(cmd) > 1 else ""
    prefix = "" if _is_frozen() else f'cd "{_repo_root()}" && '
    # The log path is user-configurable, so shell-quote it (shlex.quote) before
    # it reaches the elevated `do shell script`; this neutralizes any shell
    # metacharacters a malicious/typo'd path could otherwise inject.
    log_redirect = shlex.quote(get_tunnel_log_file())
    return f"{prefix}{exe_part}{rest_part} " f"</dev/null >{log_redirect} 2>&1"


def _kill_tunneld_shell() -> str:
    """Shell snippet that kills whatever holds the tunneld port (SIGKILL fallback)."""
    port = get_tunnel_port()
    return (
        f"PIDS=$(lsof -ti tcp:{port}); "
        f'if [ -n "$PIDS" ]; then kill $PIDS 2>/dev/null; sleep 1; '
        f"PIDS2=$(lsof -ti tcp:{port}); "
        f'if [ -n "$PIDS2" ]; then kill -9 $PIDS2 2>/dev/null; fi; fi'
    )


def _spawn_foreground_tunneld(shell_cmd: str, timeout: float, what: str) -> bool:
    """Run ``shell_cmd`` under a non-waiting elevated osascript and poll the port.

    Shared by launch/restart: the elevated osascript is started with Popen and
    NOT waited on (it blocks for the foreground daemon's lifetime); readiness is
    confirmed by polling the port, and user cancellation is detected when
    osascript exits before the port comes up.
    """
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
        logger.error("failed to start osascript for tunnel %s: %s", what, exc)
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_tunnel_running(timeout=0.3):
            logger.info("XPC tunnel %s: up", what)
            return True
        if proc.poll() is not None:
            # osascript exited before the tunnel came up: cancelled or failed.
            up = is_tunnel_running(timeout=0.3)
            logger.warning("tunnel %s ended early (cancelled/failed); up=%s", what, up)
            return up
        time.sleep(0.3)
    logger.warning("tunnel %s timed out after %.0fs", what, timeout)
    return is_tunnel_running(timeout=0.3)


def launch_tunneld(timeout: float = 30.0) -> bool:
    """Launch tunneld as root via the native authorization dialog.

    The daemon runs in the foreground under a non-waiting elevated osascript; the
    osascript/daemon keep running afterward and are stopped on request via
    stop_tunneld. The shell command is composed only of fixed, validated paths.
    """
    # Validate the tunneld entry is present before prompting for a password.
    if not _tunneld_entry_exists():
        logger.warning("tunneld entry point not found; cannot launch tunnel")
        return False

    logger.info("launching XPC tunnel (elevated); waiting up to %.0fs", timeout)
    return _spawn_foreground_tunneld(_foreground_tunneld_command(), timeout, "launch")


def restart_tunneld(timeout: float = 30.0) -> bool:
    """Restart tunneld with a SINGLE admin authorization so RSD re-enumerates.

    iOS 17+ developer services (e.g. ``com.apple.dt.testmanagerd.remote``) are
    enumerated into a tunnel session's RSD service list at tunnel-establishment
    time. A tunnel created before the DDI was mounted therefore never exposes
    them; restarting forces a fresh handshake that picks up the now-available
    services.

    Single password: the kill of the old root daemon and the relaunch of a fresh
    one run inside ONE elevated osascript — ``lsof|kill`` (with -9 fallback), then
    the tunneld command in the FOREGROUND. Crucially the relaunch is NOT
    backgrounded: a ``nohup ... &`` child is reaped by the privileged helper as
    soon as ``do shell script`` returns (which is why an earlier background
    approach killed-but-never-relaunched). Running it in the foreground under a
    non-waiting osascript keeps it alive, exactly like ``launch_tunneld``.

    On failure (port never comes up / cancelled) this does NOT fall back to the
    two-authorization path — it logs a WARNING and returns False so the UI can
    ask the user to retry manually.
    """
    if not _tunneld_entry_exists():
        logger.warning("tunneld entry point not found; cannot restart tunnel")
        return False

    logger.info("restarting XPC tunnel (single auth) to refresh RSD developer services")
    # Single elevated shell: kill the old root daemon, then run a fresh one in the
    # foreground (so it survives after do-shell-script returns).
    shell_cmd = f"{_kill_tunneld_shell()}; {_foreground_tunneld_command()}"
    return _spawn_foreground_tunneld(shell_cmd, timeout, "restart")


# --------------------------------------------------------------------------
# Active-tunnel discovery & batch cleanup
#
# The configurable port means a user who changes it and relaunches can leave
# several tunneld processes running on different ports. The helpers below find
# ALL of them (any port) and let the UI batch-kill a selection under a single
# authorization. Discovery reads process command lines via `ps` (no elevation);
# only killing root-owned processes needs admin rights.
# --------------------------------------------------------------------------

# Stable command-line markers identifying a tunneld process by launch form.
_TUNNELD_PY_MARKERS = ("ios_toolkit.tunneld_main", "tunneld_main.py")
_TUNNELD_MACHO_MARKER = "cabled_ios_tunnel"
# Extract the port from `--port 49151` or `--port=49151` for display.
_PORT_RE = re.compile(r"--port(?:=|\s+)(\d{1,5})")

TUNNEL_MODE_PYTHON = "python"
TUNNEL_MODE_MACHO = "macho"

def _classify_tunnel_command(command: str) -> "str | None":
    """Return the tunneld launch form for a command line, or None if not one.

    MachO is checked first: a frozen ``cabled_ios_tunnel`` never also carries the
    Python module markers, while the dev form always mentions the module/file.
    """
    if _TUNNELD_MACHO_MARKER in command:
        return TUNNEL_MODE_MACHO
    if any(marker in command for marker in _TUNNELD_PY_MARKERS):
        return TUNNEL_MODE_PYTHON
    return None


# Executables that merely *wrap* a tunneld launch (`/bin/sh -c "...python -m
# ios_toolkit.tunneld_main..."` and the elevated `osascript -e do shell script
# "..."`). They carry the tunneld markers inside a quoted argument, so even a
# token-aware check is fooled — but the program actually being executed
# (argv[0]) gives them away. The real listener's argv[0] is a Python
# interpreter or the cabled_ios_tunnel binary, never one of these.
_WRAPPER_BASENAMES = ("osascript", "sh", "bash", "zsh", "dash")


def _is_real_tunnel_process(command: str, mode: str) -> bool:
    """True only for the actual tunneld listener, not a wrapper that spawned it.

    Only one process actually binds the port; the launch chain
    (osascript → /bin/sh → python) puts wrappers in front of it whose command
    lines also contain the tunneld markers. We key off argv[0] (the executable
    actually running): the leaf is a Python interpreter (`-m
    ios_toolkit.tunneld_main` / ``tunneld_main.py``) or the ``cabled_ios_tunnel``
    binary; any wrapper executable is rejected.
    """
    tokens = command.split()
    if not tokens:
        return False
    exe = tokens[0].rsplit("/", 1)[-1]
    if exe in _WRAPPER_BASENAMES:
        return False
    if mode == TUNNEL_MODE_MACHO:
        return exe == _TUNNELD_MACHO_MARKER
    # python leaf: the interpreter runs the module/file as real argv tokens.
    if "-m" in tokens and "ios_toolkit.tunneld_main" in tokens:
        return True
    return any(tok.endswith("tunneld_main.py") for tok in tokens)


def list_tunnel_processes() -> list[dict]:
    """List every running tunneld process (any port) without elevation.

    Each entry is ``{pid:int, user:str, port:int|None, mode:str, command:str}``.
    On macOS a non-root user can read other users' (including root) process
    command lines, so this needs no authorization; only killing them does.
    """
    try:
        proc = subprocess.run(
            ["ps", "-axww", "-o", "pid=,user=,command="],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []

    self_pid = os.getpid()
    results: list[dict] = []
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        # "<pid> <user> <command...>" — keep the command's own spaces intact.
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid_s, user, command = parts
        if not pid_s.isdigit():
            continue
        pid = int(pid_s)
        if pid == self_pid:
            continue  # never list ourselves
        mode = _classify_tunnel_command(command)
        if mode is None:
            continue
        if not _is_real_tunnel_process(command, mode):
            continue  # drop sh/osascript wrappers; only the real listener stays
        match = _PORT_RE.search(command)
        port: "int | None" = None
        if match:
            value = int(match.group(1))
            if 1 <= value <= 65535:
                port = value
        results.append(
            {"pid": pid, "user": user, "port": port, "mode": mode, "command": command}
        )
    return results


def kill_tunnel_processes(pids: "list[int]") -> bool:
    """Kill the given tunneld PIDs under a SINGLE elevated authorization.

    Every PID is validated as a positive integer before being placed into the
    shell command; the command otherwise contains only fixed literals, so no UI
    or external free-form text is ever interpolated. Sends SIGTERM first, then
    SIGKILL to any survivor. Returns True if the elevated command was authorized
    and run (one password covers the whole batch). An empty/invalid list is a
    no-op returning False.
    """
    safe: list[int] = []
    for raw in pids:
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            safe.append(pid)
    if not safe:
        return False

    pid_list = " ".join(str(p) for p in safe)
    kill_cmd = (
        f"kill {pid_list} 2>/dev/null; sleep 1; "
        f"for p in {pid_list}; do kill -0 $p 2>/dev/null && kill -9 $p 2>/dev/null; done; "
        "true"
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


def stop_tunneld(timeout: float = 5.0) -> bool:
    """Stop the tunneld process with administrator privileges.

    The daemon runs as root, so a non-privileged ``lsof`` cannot see its socket;
    the port lookup and kill therefore run together inside the elevated shell
    (``lsof`` under root resolves the listener). tunneld does not reliably honor
    SIGTERM, so this escalates to SIGKILL if the process lingers. Returns True
    only when the command was authorized and the configured tunnel port is no
    longer listening within ``timeout`` seconds.
    """
    port = get_tunnel_port()
    kill_cmd = (
        f"PIDS=$(lsof -ti tcp:{port}); "
        f'if [ -n "$PIDS" ]; then kill $PIDS 2>/dev/null; sleep 1; '
        f"PIDS2=$(lsof -ti tcp:{port}); "
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
    if result.returncode != 0:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_tunnel_running(timeout=0.3):
            return True
        time.sleep(0.2)
    return not is_tunnel_running(timeout=0.3)
