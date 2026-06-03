"""
toolkit_cli.py — one-shot JSON CLI entry point for Studio broker.

Usage:
    python3 -B -m executor_ios.toolkit_cli

Protocol:
    stdin  → one JSON request object
    stdout → one JSON response object
    exit 0 → request processed (check "ok" field)
    exit 2 → stdin parse error or missing required fields
    exit 5 → unhandled internal exception
"""

import json
import sys

from . import toolkit_api as api


# ---------------------------------------------------------------------------
# op → handler mapping (all 11 ops from the contract)
# ---------------------------------------------------------------------------

def _handle_list_targets(args: dict) -> dict:
    return api.list_targets()


def _handle_screenshot(args: dict) -> dict:
    return api.screenshot(args["target"])


def _handle_dump_ui(args: dict) -> dict:
    return api.dump_ui(args["target"])


def _handle_tap(args: dict) -> dict:
    return api.tap(args["target"], args["x"], args["y"])


def _handle_swipe(args: dict) -> dict:
    return api.swipe(
        args["target"],
        args["x1"], args["y1"],
        args["x2"], args["y2"],
        args.get("durationMs", 250),  # camelCase from contract → duration_ms
    )


def _handle_input_text(args: dict) -> dict:
    return api.input_text(args["target"], args["text"])


def _handle_key_event(args: dict) -> dict:
    return api.key_event(args["target"], args["key"])


def _handle_launch_app(args: dict) -> dict:
    return api.launch_app(args["target"], args["package"], args.get("activity"))


def _handle_kill_app(args: dict) -> dict:
    return api.kill_app(args["target"], args["package"])


def _handle_switch_app_env(args: dict) -> dict:
    return api.switch_app_env(args["target"], args["env"])


def _handle_type_credential(args: dict) -> dict:
    return api.type_credential(
        args["target"],
        args["env"],
        args["role"],
        args["field"],
        args.get("skipClear", False),  # camelCase from contract → skip_clear
    )


OP_TABLE: dict[str, object] = {
    "list_targets":    _handle_list_targets,
    "screenshot":      _handle_screenshot,
    "dump_ui":         _handle_dump_ui,
    "tap":             _handle_tap,
    "swipe":           _handle_swipe,
    "input_text":      _handle_input_text,
    "key_event":       _handle_key_event,
    "launch_app":      _handle_launch_app,
    "kill_app":        _handle_kill_app,
    "switch_app_env":  _handle_switch_app_env,
    "type_credential": _handle_type_credential,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_response(response: dict) -> None:
    """Write a single JSON object to stdout and flush."""
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    sys.stdout.flush()


def _not_implemented_response(op: str, request_id: str | None) -> dict:
    return {
        "ok": False,
        "requestId": request_id,
        "error": {
            "kind": "NOT_IMPLEMENTED",
            "message": f"op not supported: {op}",
            "details": {},
        },
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        # 3.1 — read and parse stdin
        raw = sys.stdin.read()
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"[toolkit_cli] stdin parse error: {exc}", file=sys.stderr)
            sys.exit(2)

        request_id = req.get("requestId")

        # 3.2 — validate required fields
        if "op" not in req or "args" not in req:
            missing = [f for f in ("op", "args") if f not in req]
            _write_response({
                "ok": False,
                "requestId": request_id,
                "error": {
                    "kind": "INTERNAL",
                    "message": f"missing required fields: {missing}",
                    "details": {},
                },
            })
            sys.exit(2)

        op = req["op"]
        args = req["args"]

        # 3.3 / 3.4 — route op
        handler = OP_TABLE.get(op)
        if handler is None:
            result = _not_implemented_response(op, request_id)
        else:
            try:
                result = handler(args)
            except KeyError as exc:
                result = {
                    "ok": False,
                    "error": {
                        "kind": "BAD_TARGET",
                        "message": f"missing required arg: {exc}",
                        "details": {},
                    },
                }

        # 3.5 — attach requestId and write response
        result["requestId"] = request_id
        _write_response(result)
        sys.exit(0)

    except Exception as exc:  # 3.6 — catch-all guard
        print(f"[toolkit_cli] unhandled exception: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        sys.exit(5)


if __name__ == "__main__":  # 3.7
    main()
