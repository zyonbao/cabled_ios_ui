"""errors.py — localize ios_toolkit error envelopes for display.

The logic layer (``ios_toolkit``) is i18n-agnostic: its error envelopes carry a
stable, machine-readable ``code`` plus structured ``details``; ``message`` is an
English debug detail only. This module is the single UI entry point that turns
such an envelope into a localized, user-facing string, so no view renders the
raw English ``message`` directly.

Envelope shape (see openspec capability ``json-cli``)::

    {"ok": False, "error": {"kind": "TIMEOUT", "code": "DDI_MOUNT_TIMEOUT",
                            "message": "<english debug>", "details": {...}}}
"""

from __future__ import annotations

from typing import Any

from .. import i18n


def localize_error(error: "dict[str, Any] | None") -> str:
    """Return a localized message for a toolkit error envelope.

    Resolution order (first hit wins), per the ``slide6-error-localization``
    capability:
      1. ``errors.<code>`` — the fine-grained, code-specific template, filled
         with ``details`` via named placeholders;
      2. ``errors.kind.<kind>`` — a coarse, kind-level fallback;
      3. ``error.message`` — the English debug detail from the logic layer;
      4. ``errors.unknown`` — a generic catch-all.
    """
    if not isinstance(error, dict):
        return i18n.t("errors.unknown")

    details = error.get("details")
    if not isinstance(details, dict):
        details = {}

    code = error.get("code")
    if code:
        key = f"errors.{code}"
        if i18n.has(key):
            return i18n.t(key, **details)

    kind = error.get("kind")
    if kind:
        key = f"errors.kind.{kind}"
        if i18n.has(key):
            return i18n.t(key, **details)

    message = error.get("message")
    if message:
        return str(message)

    return i18n.t("errors.unknown")
