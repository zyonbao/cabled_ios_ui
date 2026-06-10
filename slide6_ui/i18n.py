"""i18n.py — lightweight internationalization for the slide6_ui desktop app.

Design (see openspec change add-ui-i18n):
- Catalogs live in ``slide6_ui/languages/<lang>.json`` as nested JSON; leaves are
  display-text templates keyed by dotted semantic keys (e.g. ``dev_tools.ddi.mounted``).
- ``zh-CN`` is the canonical full key set and the fallback language; ``en-US`` must
  stay structurally aligned with it.
- The language is chosen once at startup (restart-to-apply); there is no runtime
  retranslation. ``init()`` flattens the chosen catalog plus the zh-CN fallback.
- ``t(key, **kwargs)`` returns the current-language template, falling back to zh-CN
  and finally to the key itself; named placeholders are filled via ``str.format``.

This module intentionally has NO dependency on any other ``slide6_ui`` submodule so
it can be imported during early startup without circular-import risk.
"""

from __future__ import annotations

import json
import logging
import string
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Kept in sync with main_window._SETTINGS_ORG / _SETTINGS_APP. Duplicated here on
# purpose so i18n stays free of slide6_ui imports (main_window imports i18n).
_SETTINGS_ORG = "ios_ui_ta_proxy"
_SETTINGS_APP = "slide6_console"
LANGUAGE_KEY = "settings/language"

DEFAULT_LANGUAGE = "zh-CN"
SUPPORTED_LANGUAGES = ("zh-CN", "en-US")
# Human-readable labels for the language picker (label -> code).
LANGUAGE_LABELS = (("简体中文", "zh-CN"), ("English", "en-US"))

_LANGUAGES_DIR = Path(__file__).resolve().parent / "languages"

# Module-level singleton state, populated by init().
_current_language = DEFAULT_LANGUAGE
_catalog: dict[str, str] = {}
_fallback: dict[str, str] = {}
_initialized = False


def _flatten(data: "dict[str, Any]", prefix: str = "") -> "dict[str, str]":
    """Flatten a nested catalog dict into ``{dotted.key: template}``."""
    out: dict[str, str] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{dotted}."))
        else:
            out[dotted] = str(value)
    return out


def _load_catalog(lang: str) -> "dict[str, str]":
    """Load and flatten ``languages/<lang>.json``; return {} on any failure."""
    path = _LANGUAGES_DIR / f"{lang}.json"
    try:
        with path.open("r", encoding="utf-8") as fh:
            return _flatten(json.load(fh))
    except FileNotFoundError:
        logger.warning("i18n catalog not found: %s", path)
    except (OSError, ValueError) as exc:
        logger.error("i18n failed to load catalog %s: %s", path, exc)
    return {}


def _resolve_language(lang: "str | None") -> str:
    """Resolve the effective language: explicit arg > QSettings > default."""
    if lang is None:
        try:
            from PySide6.QtCore import QSettings

            settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
            lang = settings.value(LANGUAGE_KEY, DEFAULT_LANGUAGE, type=str)
        except Exception:  # pragma: no cover - QSettings unavailable (headless tests)
            lang = DEFAULT_LANGUAGE
    if lang not in SUPPORTED_LANGUAGES:
        if lang:
            logger.warning("i18n unsupported language %r, falling back to %s", lang, DEFAULT_LANGUAGE)
        lang = DEFAULT_LANGUAGE
    return lang


def init(lang: "str | None" = None) -> str:
    """Initialize i18n once at startup. Returns the effective language code."""
    global _current_language, _catalog, _fallback, _initialized
    _current_language = _resolve_language(lang)
    _fallback = _load_catalog(DEFAULT_LANGUAGE)
    _catalog = _fallback if _current_language == DEFAULT_LANGUAGE else _load_catalog(_current_language)
    _initialized = True
    logger.info(
        "i18n initialized: language=%s entries=%d fallback=%d",
        _current_language, len(_catalog), len(_fallback),
    )
    return _current_language


def current_language() -> str:
    """Return the effective language code (after init)."""
    return _current_language


def t(key: str, /, **kwargs: Any) -> str:
    """Return the localized template for ``key``, formatted with ``kwargs``.

    Lookup order: current language -> zh-CN fallback -> the key itself. When
    ``kwargs`` are supplied, named placeholders are filled via ``str.format``;
    a formatting failure (missing/mismatched placeholder) logs a warning and
    returns the unformatted template rather than raising.
    """
    if not _initialized:
        # Lazy init keeps standalone imports / tests from crashing.
        init()
    template = _catalog.get(key)
    if template is None:
        template = _fallback.get(key)
    if template is None:
        logger.warning("i18n missing key: %s", key)
        return key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning("i18n format failed for %r: %s", key, exc)
        return template


def has(key: str) -> bool:
    """Return True if ``key`` exists in the current language or zh-CN fallback.

    Lets callers (e.g. error-code localization) distinguish "key resolves to a
    real template" from ``t()``'s key-echo behavior before deciding to fall back.
    """
    if not _initialized:
        init()
    return key in _catalog or key in _fallback


def _placeholders(template: str) -> "set[str]":
    """Return the set of named placeholders used by a format template."""
    names: set[str] = set()
    for _literal, field_name, _spec, _conv in string.Formatter().parse(template):
        if field_name:
            # Keep only the top-level name (strip ``.attr`` / ``[idx]`` access).
            base = field_name.replace("[", ".").split(".", 1)[0]
            names.add(base)
    return names


def validate() -> "list[str]":
    """Cross-check zh-CN and en-US catalogs; return a list of problem strings.

    Checks performed:
    - key set alignment (keys missing from / extra in en-US relative to zh-CN);
    - placeholder-name consistency for every shared key.
    An empty list means the catalogs are consistent.
    """
    zh = _load_catalog("zh-CN")
    en = _load_catalog("en-US")
    problems: list[str] = []

    missing = sorted(set(zh) - set(en))
    extra = sorted(set(en) - set(zh))
    for key in missing:
        problems.append(f"missing in en-US: {key}")
    for key in extra:
        problems.append(f"extra in en-US (not in zh-CN): {key}")

    for key in sorted(set(zh) & set(en)):
        zh_ph = _placeholders(zh[key])
        en_ph = _placeholders(en[key])
        if zh_ph != en_ph:
            problems.append(
                f"placeholder mismatch for {key}: zh-CN={sorted(zh_ph)} en-US={sorted(en_ph)}"
            )
    return problems
