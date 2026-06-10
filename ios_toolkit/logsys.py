"""logsys.py — centralized, low-coupling application logging setup.

Business modules stay decoupled: they only ever call ``logging.getLogger(__name__)``
and never import this module. The GUI and the tunneld entry point call
``setup_logging`` once at startup (it is idempotent and may be re-called to apply
new settings) and ``shutdown_logging`` on exit.

File logging (when enabled): one log file per process run, named
``cabledios_log_<start_time>.log`` (``start_time`` = ``YYYYMMDD_HHMMSS``). A run
that lasts past 24h rolls over using RotatingFileHandler's numeric shard suffixes
(``.log`` newest, ``.log.1`` / ``.log.2`` … older), triggered on a 24h timer. At
most the most recent 5 runs are kept (older runs and all their shards are pruned
on startup). The console (stderr) mirrors INFO and above; the file records DEBUG
and above.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional

# Default location follows the macOS convention for app logs.
DEFAULT_LOG_DIR = os.path.expanduser("~/Library/CablediOS/Logs")

_FILE_PREFIX = "cabledios_log_"
_FILE_SUFFIX = ".log"
_KEEP_RUNS = 5
_SHARD_INTERVAL_S = 24 * 60 * 60  # rotate within a single run every 24h
_SHARD_BACKUP_COUNT = 30          # cap shards retained for one long-running run
_LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Attribute marking handlers this module installed, so re-init only removes our
# own handlers and never touches third-party ones.
_OWNED = "_cabledios_logsys_owned"

# One run token for the whole process lifetime (stable across re-inits) so a
# settings change reuses the same per-run file instead of spawning a new one.
_run_token: "Optional[str]" = None

_logger = logging.getLogger(__name__)


class _TimedShardHandler(RotatingFileHandler):
    """RotatingFileHandler that rolls over on a time interval, not on size.

    Keeps the parent's numeric ``.1/.2/...`` shard naming (``.log`` is newest)
    but triggers ``doRollover`` every ``interval_s`` seconds instead of at
    ``maxBytes``.
    """

    def __init__(
        self,
        filename: str,
        interval_s: int = _SHARD_INTERVAL_S,
        backup_count: int = _SHARD_BACKUP_COUNT,
        encoding: str = "utf-8",
    ) -> None:
        # maxBytes=0 disables the parent's size-based rollover entirely.
        super().__init__(filename, maxBytes=0, backupCount=backup_count, encoding=encoding)
        self._interval_s = interval_s
        self._next_rollover = time.time() + interval_s

    def shouldRollover(self, record):  # noqa: N802 - logging API name
        if time.time() >= self._next_rollover:
            return 1
        return 0

    def doRollover(self):  # noqa: N802 - logging API name
        super().doRollover()
        self._next_rollover = time.time() + self._interval_s


def _get_run_token() -> str:
    global _run_token
    if _run_token is None:
        _run_token = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _run_token


def _remove_owned_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        if getattr(handler, _OWNED, False):
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
            root.removeHandler(handler)


def _prune_old_runs(log_dir: str, keep: int = _KEEP_RUNS) -> None:
    """Keep only the most recent ``keep`` runs (each run = base + its shards)."""
    if keep <= 0:
        return
    try:
        names = os.listdir(log_dir)
    except OSError:
        return
    # Run anchors are the base files (``..._<token>.log``); shard files end with
    # ``.log.1`` etc. and are not anchors. The token is YYYYMMDD_HHMMSS, so a
    # lexicographic sort is chronological.
    bases = sorted(
        n for n in names if n.startswith(_FILE_PREFIX) and n.endswith(_FILE_SUFFIX)
    )
    for base in bases[:-keep]:
        for n in names:
            if n == base or n.startswith(base + "."):
                try:
                    os.remove(os.path.join(log_dir, n))
                except OSError:
                    pass


def setup_logging(enabled: bool = True, log_dir: "Optional[str]" = None) -> dict:
    """Configure application logging; idempotent (safe to call again to re-apply).

    ``enabled`` gates file logging; the console (stderr, INFO+) is always on.
    Returns a small dict describing the active configuration.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    _remove_owned_handlers(root)

    formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

    # Console handler: always present, INFO and above (debug stays file-only).
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    setattr(console, _OWNED, True)
    root.addHandler(console)

    info = {"enabled": bool(enabled), "console": True, "file": None, "log_dir": None}

    if enabled:
        directory = os.path.abspath(os.path.expanduser(log_dir or DEFAULT_LOG_DIR))
        try:
            os.makedirs(directory, exist_ok=True)
            filename = os.path.join(
                directory, f"{_FILE_PREFIX}{_get_run_token()}{_FILE_SUFFIX}"
            )
            file_handler = _TimedShardHandler(filename)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            setattr(file_handler, _OWNED, True)
            root.addHandler(file_handler)
            _prune_old_runs(directory)
            info["file"] = filename
            info["log_dir"] = directory
        except OSError as exc:
            # Unwritable directory etc.: keep console logging, surface the reason.
            _logger.warning("file logging disabled: cannot use %s: %s", log_dir, exc)

    _logger.info(
        "logging initialized (enabled=%s, dir=%s)", info["enabled"], info["log_dir"]
    )
    return info


def shutdown_logging() -> None:
    """Flush and close handlers this module installed (call on process exit)."""
    _remove_owned_handlers(logging.getLogger())
