r"""
tunneld_main.py — Standalone entry point for the iOS XPC tunnel daemon.

Intended to be packaged as a self-contained binary (e.g. via PyInstaller)
and run as a LaunchDaemon on macOS, so that customer machines do not need
Python or pymobiledevice3 installed separately.

Usage (directly):
    sudo python3 -m ios_toolkit.tunneld_main

Usage (as packaged binary via LaunchDaemon):
    /Library/Application\ Support/ZoomTA/ios_tunneld

Tunneld listens on 127.0.0.1:49151 and exposes a REST API.
device.py queries this API to retrieve RSD info for iOS 17+ devices.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import logsys

_logger = logging.getLogger(__name__)

# Defaults must match slide6_ui.common.tunnel (DEFAULT_TUNNELD_PORT) so a daemon
# started without explicit args is still discoverable by the desktop UI.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 49151


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ios_tunneld",
        description="iOS XPC tunnel daemon (RSD provider for iOS 17+).",
    )
    # Bind address is fixed to loopback by default; do not expose off-box.
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host (default: %(default)s)")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="bind port (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if not (1 <= args.port <= 65535):
        parser.error(f"--port must be in 1..65535 (got {args.port})")
    return args


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    # Standalone process (no Qt / QSettings): log with defaults so tunneld
    # activity lands in the same log directory for cross-process diagnosis.
    logsys.setup_logging(enabled=True, log_dir=None)
    try:
        try:
            from pymobiledevice3.tunneld.server import TunneldRunner
            from pymobiledevice3.remote.common import TunnelProtocol
        except ImportError as exc:
            _logger.error("pymobiledevice3 is not available: %s", exc)
            print(f"Error: pymobiledevice3 is not available: {exc}", file=sys.stderr)
            sys.exit(1)

        # TunnelProtocol.DEFAULT is TCP on Python >= 3.13, QUIC otherwise.
        # TCP is preferred: it does not require aioquic and is more stable.
        protocol = (
            TunnelProtocol.TCP if sys.version_info >= (3, 13) else TunnelProtocol.DEFAULT
        )

        _logger.info("starting tunneld on %s:%d (protocol=%s)", args.host, args.port, protocol)
        TunneldRunner.create(
            host=args.host,
            port=args.port,
            protocol=protocol,
            usb_monitor=True,
            wifi_monitor=False,   # only USB devices are supported
            usbmux_monitor=True,
            mobdev2_monitor=False,
        )
    finally:
        logsys.shutdown_logging()


if __name__ == "__main__":
    main()
