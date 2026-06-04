"""
web_server.py — interactive browser UI for controlling USB-connected iOS devices.

Serves a single-page app that mirrors a device screen via WDA's MJPEG
broadcaster (continuous, high-fps) and forwards mouse tap/swipe gestures and
Mac-keyboard input back to the device.

This module lives alongside (not inside) the executor_ios package and reuses its
capability layer (executor_ios.toolkit_api).

Run from the repository root:
    python3 -m web_console.web_server            # http://127.0.0.1:8787
    python3 -m web_console.web_server --port 9000

The HTTP layer is a thin wrapper over toolkit_api / device; all blocking WDA
calls run in FastAPI's threadpool (handlers are declared as sync `def`).
"""

from __future__ import annotations

import argparse
import asyncio
import base64

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

from executor_ios import toolkit_api as api

WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(title="executor_ios web UI", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TargetBody(BaseModel):
    target: str


class TapBody(BaseModel):
    target: str
    x: int
    y: int


class SwipeBody(BaseModel):
    target: str
    x1: int
    y1: int
    x2: int
    y2: int
    durationMs: int = 250


class KeyBody(BaseModel):
    target: str
    key: str


class TypeBody(BaseModel):
    target: str
    text: str


class ChordBody(BaseModel):
    target: str
    key: str
    modifiers: list[str] = []


class StreamConfigBody(BaseModel):
    target: str
    framerate: int = 20
    scalingFactor: int = 60
    quality: int = 70


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raise_if_error(result: dict) -> dict:
    """Convert a toolkit_api error envelope into an HTTP error."""
    if not result.get("ok"):
        err = result.get("error", {})
        kind = err.get("kind", "INTERNAL")
        status = 404 if kind == "BAD_TARGET" else 503
        raise HTTPException(status_code=status, detail=err.get("message", "unknown error"))
    return result


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/devices")
def devices() -> dict:
    """List USB devices; `state` is 'online' only when WDA is installed."""
    return _raise_if_error(api.list_targets())["data"]


@app.post("/api/prepare")
def prepare(body: TargetBody) -> dict:
    """Start WDA (may take a while on first launch) and confirm reachability."""
    return _raise_if_error(api.prepare(body.target))["data"]


@app.get("/api/window_size")
def window_size(target: str) -> dict:
    """WDA logical window size (points) for mapping browser clicks to device."""
    return _raise_if_error(api.window_size(target))["data"]


@app.get("/api/orientation")
def orientation(target: str) -> dict:
    """Current screen orientation (enum + clockwise degrees) for rendering."""
    return _raise_if_error(api.orientation(target))["data"]


@app.get("/api/screenshot")
def screenshot(target: str) -> Response:
    """Return a single raw PNG frame (manual/debug helper).

    The live UI mirrors via /api/stream (MJPEG); this single-shot endpoint is
    kept for debugging and assumes /api/prepare has already been called.
    """
    manager = api._get_manager()
    device = manager.get_device(target)
    if device is None:
        raise HTTPException(status_code=404, detail=f"device not found: {target}")
    result = device.screenshot()
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", {}).get("message", "screenshot failed"))
    png = base64.b64decode(result["data"]["base64"])
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.post("/api/tap")
def tap(body: TapBody) -> dict:
    return _raise_if_error(api.tap(body.target, body.x, body.y))["data"]


@app.post("/api/swipe")
def swipe(body: SwipeBody) -> dict:
    return _raise_if_error(
        api.swipe(body.target, body.x1, body.y1, body.x2, body.y2, body.durationMs)
    )["data"]


@app.post("/api/key")
def key(body: KeyBody) -> dict:
    return _raise_if_error(api.key_event(body.target, body.key))["data"]


@app.post("/api/type")
def type_text(body: TypeBody) -> dict:
    """Type text into the device's focused field (Mac keyboard mirroring)."""
    return _raise_if_error(api.send_keys(body.target, body.text))["data"]


@app.post("/api/chord")
def chord(body: ChordBody) -> dict:
    """Send a modifier-key chord (e.g. ⌘C) to the device's focused field."""
    return _raise_if_error(api.key_chord(body.target, body.key, body.modifiers))["data"]


class LaunchBody(BaseModel):
    target: str
    package: str


@app.post("/api/launch")
def launch(body: LaunchBody) -> dict:
    """Launch an app by bundle id (mainly a test/QA helper)."""
    return _raise_if_error(api.launch_app(body.target, body.package))["data"]


@app.post("/api/app_switcher")
def app_switcher(body: TargetBody) -> dict:
    """Open the iOS App Switcher (multitasking / background view)."""
    return _raise_if_error(api.app_switcher(body.target))["data"]


@app.post("/api/stream_config")
def stream_config(body: StreamConfigBody) -> dict:
    """Live-tune the MJPEG broadcaster (framerate / scaling / quality)."""
    return _raise_if_error(
        api.configure_mjpeg(body.target, body.framerate, body.scalingFactor, body.quality)
    )["data"]


@app.get("/api/stream")
async def stream(target: str) -> StreamingResponse:
    """Proxy the device's WDA MJPEG broadcaster to the browser.

    The browser renders the multipart/x-mixed-replace stream directly in an
    <img>, giving a continuous high-fps mirror instead of per-frame polling.
    """
    manager = api._get_manager()
    device = manager.get_device(target)
    if device is None:
        raise HTTPException(status_code=404, detail=f"device not found: {target}")
    port = getattr(device, "mjpeg_local_port", 0)
    if not port:
        raise HTTPException(status_code=503, detail="MJPEG port not available for device")

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"cannot connect to MJPEG stream: {exc}")

    # WDA's broadcaster only starts streaming once the client sends some bytes.
    writer.write(b"GET / HTTP/1.0\r\n\r\n")
    await writer.drain()

    # Consume WDA's own HTTP status line + headers; reuse its Content-Type.
    content_type = "multipart/x-mixed-replace; boundary=--BoundaryString"
    try:
        header_blob = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        for line in header_blob.split(b"\r\n"):
            if line.lower().startswith(b"content-type:"):
                content_type = line.split(b":", 1)[1].strip().decode("latin1")
    except Exception as exc:
        writer.close()
        raise HTTPException(status_code=503, detail=f"MJPEG stream handshake failed: {exc}")

    async def relay():
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                writer.close()
            except Exception:
                pass

    return StreamingResponse(
        relay(),
        media_type=content_type,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


# Static assets (JS/CSS). Mounted last so it does not shadow /api routes.
app.mount("/", StaticFiles(directory=str(WEB_DIR)), name="static")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="executor_ios interactive web UI")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="bind port (default 8787)")
    args = parser.parse_args()

    import uvicorn

    print(f"executor_ios web UI → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
