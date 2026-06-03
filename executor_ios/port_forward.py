"""
USB port forwarding for iOS devices via usbmux (no XPC tunnel / no sudo needed).

Forwards a local TCP port to a port on the connected iOS device through the
USB usbmux channel. This is the standard way to expose WDA (port 8100) on
localhost before iOS 17 — and it still works on iOS 17+, because WDA uses
plain usbmux TCP, not CoreDevice/RemoteXPC.

Usage:
    python3 -m executor_ios.port_forward                    # 8100 -> 8100, auto device
    python3 -m executor_ios.port_forward --udid <UDID>
    python3 -m executor_ios.port_forward --local 8200 --device 8100
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)

_RELAY_CHUNK = 65536


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, tag: str) -> None:
    """Copy bytes from reader to writer until EOF."""
    try:
        while True:
            chunk = await reader.read(_RELAY_CHUNK)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _handle_client(
    local_reader: asyncio.StreamReader,
    local_writer: asyncio.StreamWriter,
    device_udid: Optional[str],
    device_port: int,
) -> None:
    """Handle one incoming local connection: open usbmux channel and relay."""
    peer = local_writer.get_extra_info("peername")
    logger.debug("New connection from %s", peer)

    try:
        from pymobiledevice3.usbmux import list_devices
        from pymobiledevice3.tcp_forwarder import UsbmuxTcpForwarder  # type: ignore[import]
    except ImportError:
        # Fallback: use low-level usbmux connect via lockdown
        try:
            from pymobiledevice3.usbmux import list_devices
        except ImportError as exc:
            logger.error("pymobiledevice3 not installed: %s", exc)
            local_writer.close()
            return

    # Try the preferred high-level API first, fall back to manual relay
    try:
        await _relay_via_usbmux(local_reader, local_writer, device_udid, device_port)
    except Exception as exc:
        logger.error("Relay error for %s: %s", peer, exc)
        try:
            local_writer.close()
        except Exception:
            pass


async def _relay_via_usbmux(
    local_reader: asyncio.StreamReader,
    local_writer: asyncio.StreamWriter,
    device_udid: Optional[str],
    device_port: int,
) -> None:
    """Open a usbmux connection to device_port and relay bidirectionally."""
    from pymobiledevice3.usbmux import list_devices

    devices = await list_devices()
    if not devices:
        raise RuntimeError("No iOS devices found via usbmux")

    device = None
    if device_udid:
        for d in devices:
            if d.serial == device_udid:
                device = d
                break
        if device is None:
            raise RuntimeError(f"Device {device_udid} not found")
    else:
        device = devices[0]
        if len(devices) > 1:
            logger.warning("Multiple devices found, using %s. Use --udid to specify.", device.serial)

    # Open a raw TCP-over-USB connection to the device port
    device_reader, device_writer = await device.create_connection(device_port)

    # Bidirectional relay
    await asyncio.gather(
        _relay(local_reader, device_writer, "local→device"),
        _relay(device_reader, local_writer, "device→local"),
    )


async def _run_forwarder(
    local_port: int,
    device_port: int,
    device_udid: Optional[str],
) -> None:
    def client_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        asyncio.ensure_future(
            _handle_client(reader, writer, device_udid, device_port)
        )

    server = await asyncio.start_server(client_handler, host="127.0.0.1", port=local_port)
    addr = server.sockets[0].getsockname()  # type: ignore[union-attr]
    print(f"Forwarding 127.0.0.1:{addr[1]} → device:{device_port}", flush=True)
    if device_udid:
        print(f"Device UDID: {device_udid}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    async with server:
        await server.serve_forever()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Forward a local port to an iOS device port via usbmux (no sudo needed)."
    )
    parser.add_argument("--local", type=int, default=8100, metavar="PORT",
                        help="Local port to listen on (default: 8100)")
    parser.add_argument("--device", type=int, default=8100, metavar="PORT",
                        help="Device port to forward to (default: 8100)")
    parser.add_argument("--udid", metavar="UDID",
                        help="Target device UDID (auto-select if omitted)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        asyncio.run(_run_forwarder(
            local_port=args.local,
            device_port=args.device,
            device_udid=args.udid,
        ))
    except KeyboardInterrupt:
        print("\nForwarder stopped.", file=sys.stderr)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
