"""
tunneld_main.py — Standalone entry point for the iOS XPC tunnel daemon.

Intended to be packaged as a self-contained binary (e.g. via PyInstaller)
and run as a LaunchDaemon on macOS, so that customer machines do not need
Python or pymobiledevice3 installed separately.

Usage (directly):
    sudo python3 -m executor_ios.tunneld_main

Usage (as packaged binary via LaunchDaemon):
    /Library/Application\ Support/ZoomTA/ios_tunneld

Tunneld listens on 127.0.0.1:49151 and exposes a REST API.
xpc_tunnel.py queries this API to retrieve RSD info for iOS 17+ devices.
"""

from __future__ import annotations

import sys


def main() -> None:
    try:
        from pymobiledevice3.tunneld.server import TunneldRunner
        from pymobiledevice3.remote.common import TunnelProtocol
    except ImportError as exc:
        print(f"Error: pymobiledevice3 is not available: {exc}", file=sys.stderr)
        sys.exit(1)

    # TunnelProtocol.DEFAULT is TCP on Python >= 3.13, QUIC otherwise.
    # TCP is preferred: it does not require aioquic and is more stable.
    protocol = TunnelProtocol.TCP if sys.version_info >= (3, 13) else TunnelProtocol.DEFAULT

    TunneldRunner.create(
        host="127.0.0.1",
        port=49151,
        protocol=protocol,
        usb_monitor=True,
        wifi_monitor=False,   # only USB devices are supported
        usbmux_monitor=True,
        mobdev2_monitor=False,
    )


if __name__ == "__main__":
    main()
