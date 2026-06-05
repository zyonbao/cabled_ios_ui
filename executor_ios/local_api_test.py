"""
entry.py — manual smoke-test entry point for toolkit_api.

Usage:
    1. Fill in UDID and BUNDLE_ID below.
    2. Uncomment the test_ calls you want to run in main().
    3. python3 -m executor_ios.entry
"""

import base64
import json

from . import toolkit_api as api

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print(label: str, result: dict) -> None:
    ok = result.get("ok")
    status = "✅ OK" if ok else "❌ FAIL"
    print(f"\n[{status}] {label}")
    if ok:
        data = result.get("data", {})
        if "base64" in data:
            preview = data["base64"][:40] + "..." if data["base64"] else "(empty)"
            print(f"  mimeType : {data.get('mimeType')}")
            print(f"  base64   : {preview}")
        elif "targets" in data:
            for t in data["targets"]:
                print(f"  target   : {json.dumps(t, ensure_ascii=False)}")
        elif "selectors" in data:
            print(f"  selectors: {len(data['selectors'])} items")
            for s in data["selectors"]:
                print(f"    {s}")
        else:
            print(f"  data: {json.dumps(data, ensure_ascii=False)}")
    else:
        err = result.get("error", {})
        print(f"  kind   : {err.get('kind')}")
        print(f"  message: {err.get('message')}")


# ---------------------------------------------------------------------------
# Individual test functions
# ---------------------------------------------------------------------------

def test_list_targets() -> None:
    """7.1 — list USB-connected devices."""
    _print("list_targets()", api.list_targets())


def test_screenshot(udid: str) -> None:
    """7.2 — take a screenshot, verify base64 decodes to valid PNG, and save to CWD."""
    result = api.screenshot(udid)
    _print(f"screenshot({udid!r})", result)
    if result.get("ok"):
        raw = base64.b64decode(result["data"]["base64"])
        is_png = raw[:4] == b"\x89PNG"
        print(f"  PNG header OK: {is_png}")
        out_path = "screenshot.png"
        with open(out_path, "wb") as f:
            f.write(raw)
        print(f"  Saved to: {out_path}")


def test_dump_ui(udid: str) -> None:
    """7.3 — dump UI tree and check selector fields."""
    result = api.dump_ui(udid)
    _print(f"dump_ui({udid!r})", result)
    if result.get("ok"):
        selectors = result["data"].get("selectors", [])
        required_keys = {"resourceId", "text", "contentDesc", "class",
                         "bounds", "clickable", "enabled", "visible"}
        for i, s in enumerate(selectors[:5]):
            missing = required_keys - set(s.keys())
            if missing:
                print(f"  ⚠ selector[{i}] missing keys: {missing}")
        print(f"  All 8 fields present in first 5 selectors: "
              f"{all(not (required_keys - set(s.keys())) for s in selectors[:5])}")


def test_tap(udid: str, x: int, y: int) -> None:
    """7.4 — tap at (x, y). Adjust coordinates to hit a real button."""
    _print(f"tap({udid!r}, {x}, {y})", api.tap(udid, x, y))


def test_swipe(udid: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
    """7.4 — swipe from (x1,y1) to (x2,y2). Adjust as needed."""
    _print(
        f"swipe({udid!r}, {x1},{y1} -> {x2},{y2}, {duration_ms}ms)",
        api.swipe(udid, x1, y1, x2, y2, duration_ms),
    )


def test_input_text(udid: str, text: str) -> None:
    """7.4 — type text into the currently focused element."""
    _print(f"input_text({udid!r}, {text!r})", api.input_text(udid, text))


def test_input_text_invalid(udid: str) -> None:
    """7.5 (validation) — ensure bad text returns BAD_TARGET, not an exception."""
    cases = [
        ("newline",       "hello\nworld"),
        ("single quote",  "it's"),
        ("backtick",      "hello`world"),
        ("too long",      "x" * 1025),
    ]
    for label, bad_text in cases:
        result = api.input_text(udid, bad_text)
        ok_flag = not result.get("ok") and result["error"]["kind"] == "BAD_TARGET"
        symbol = "✅" if ok_flag else "❌"
        print(f"  {symbol} input_text validation [{label}]: kind={result.get('error', {}).get('kind')}")


def test_pasteboard_roundtrip(udid: str) -> None:
    """set_pasteboard then get_pasteboard must round-trip the same text.

    Requires the WDA runner to be in the foreground (iOS UIPasteboard
    restriction); a backgrounded WDA typically yields isText=False / empty.
    """
    for label, text in [("ascii", "hello world"), ("中文/emoji", "你好🌟 世界")]:
        set_res = api.set_pasteboard(udid, text)
        _print(f"set_pasteboard({udid!r}, {text!r})", set_res)
        get_res = api.get_pasteboard(udid)
        _print(f"get_pasteboard({udid!r})", get_res)
        ok_flag = (
            get_res.get("ok")
            and get_res["data"].get("isText") is True
            and get_res["data"].get("text") == text
        )
        symbol = "✅" if ok_flag else "❌"
        print(f"  {symbol} pasteboard round-trip [{label}]")


def test_get_pasteboard_nontext(udid: str) -> None:
    """Manual: copy an image on the device first, then run this.

    A non-text (e.g. image) pasteboard should return ok=True with
    isText=False and empty text.
    """
    res = api.get_pasteboard(udid)
    _print(f"get_pasteboard({udid!r}) [expect non-text]", res)
    ok_flag = res.get("ok") and res["data"].get("isText") is False
    symbol = "✅" if ok_flag else "❌"
    print(f"  {symbol} non-text pasteboard reported isText=False")


def test_key_home(udid: str) -> None:
    """7.4 — press HOME; device should return to the home screen."""
    _print(f"key_event({udid!r}, 'HOME')", api.key_event(udid, "HOME"))


def test_key_enter(udid: str) -> None:
    """7.4 — send ENTER key via W3C key action."""
    _print(f"key_event({udid!r}, 'ENTER')", api.key_event(udid, "ENTER"))


def test_key_not_implemented(udid: str) -> None:
    """7.5 — BACK/MENU/RECENTS must return NOT_IMPLEMENTED, not raise."""
    for key in ("BACK", "MENU", "RECENTS", "WHATEVER"):
        result = api.key_event(udid, key)
        ok_flag = not result.get("ok") and result["error"]["kind"] == "NOT_IMPLEMENTED"
        symbol = "✅" if ok_flag else "❌"
        print(f"  {symbol} key_event NOT_IMPLEMENTED [{key}]")


def test_launch_app(udid: str, bundle_id: str) -> None:
    """7.4 — launch an app by bundle ID."""
    _print(f"launch_app({udid!r}, {bundle_id!r})", api.launch_app(udid, bundle_id))


def test_kill_app(udid: str, bundle_id: str) -> None:
    """7.4 — terminate the app."""
    _print(f"kill_app({udid!r}, {bundle_id!r})", api.kill_app(udid, bundle_id))


def test_bad_target(bundle_id: str) -> None:
    """7.5 — every op with a fake UDID must return BAD_TARGET, never raise."""
    fake_udid = "00000000-0000000000000000"
    ops = [
        ("screenshot",  lambda: api.screenshot(fake_udid)),
        ("dump_ui",     lambda: api.dump_ui(fake_udid)),
        ("tap",         lambda: api.tap(fake_udid, 0, 0)),
        ("swipe",       lambda: api.swipe(fake_udid, 0, 0, 0, 100)),
        ("input_text",  lambda: api.input_text(fake_udid, "hi")),
        ("set_pasteboard", lambda: api.set_pasteboard(fake_udid, "hi")),
        ("get_pasteboard", lambda: api.get_pasteboard(fake_udid)),
        ("key_event",   lambda: api.key_event(fake_udid, "HOME")),
        ("launch_app",  lambda: api.launch_app(fake_udid, bundle_id)),
        ("kill_app",    lambda: api.kill_app(fake_udid, bundle_id)),
    ]
    print("\n[BAD_TARGET checks — all must return BAD_TARGET, not raise]")
    for name, fn in ops:
        try:
            result = fn()
            kind = result.get("error", {}).get("kind", "?")
            symbol = "✅" if kind == "BAD_TARGET" else "❌"
            print(f"  {symbol} {name}: kind={kind}")
        except Exception as exc:
            print(f"  ❌ {name}: raised {type(exc).__name__}: {exc}")


def test_not_implemented_stubs(udid: str) -> None:
    """7.6 — switch_app_env and type_credential must return NOT_IMPLEMENTED."""
    for label, result in [
        ("switch_app_env",  api.switch_app_env(udid, "staging")),
        ("type_credential", api.type_credential(udid, "staging", "user", "password")),
    ]:
        kind = result.get("error", {}).get("kind", "?")
        symbol = "✅" if kind == "NOT_IMPLEMENTED" else "❌"
        print(f"  {symbol} {label}: kind={kind}")


# ---------------------------------------------------------------------------
# main — uncomment the tests you want to run
# ---------------------------------------------------------------------------

def main() -> None:
    '''
    cd ./ios_ui_ta_proxy
    python3 -m executor_ios.local_api_test
    '''


    UDID = "00008120-000E2D3E1122201E"
    # BUNDLE_ID = "us.zoom.videomeetings"
    # BUNDLE_ID = "hf.zoom.sdk.MobileRTCTASample"
    # BUNDLE_ID = "com.apple.mobilesafari"
    BUNDLE_ID = "com.apple.mobilenotes"

    if UDID == "YOUR-DEVICE-UDID-HERE":
        print("⚠  Please set UDID at the top of entry.py before running device tests.")
        print("   Get your UDID with: pymobiledevice3 usbmux list\n")

    # ---- No device needed ------------------------------------------------
    # print("=" * 60)
    # print("Tests that don't need a device")
    # print("=" * 60)
    # test_not_implemented_stubs(UDID)       # 7.6
    # test_input_text_invalid(UDID)          # 7.5 (validation)
    # test_key_not_implemented(UDID)         # 7.4 (NOT_IMPLEMENTED keys)

    # # ---- Needs a real UDID -----------------------------------------------
    # print("=" * 60)
    # print("Device tests")
    # print("=" * 60)

    test_list_targets()                    # 7.1
    test_screenshot(UDID)                  # 7.2
    test_dump_ui(UDID)                     # 7.3
    test_launch_app(UDID, BUNDLE_ID)       # 7.4 launch
    test_key_home(UDID)                    # 7.4 HOME (with fallback)
    # test_bad_target(BUNDLE_ID)             # 7.5 BAD_TARGET
    test_kill_app(UDID, BUNDLE_ID)         # 7.4 kill


if __name__ == "__main__":
    main()
