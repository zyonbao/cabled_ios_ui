"""Stub of xonsh.cli_utils.

`Annotated` and `Arg` appear in method parameter annotations in
pymobiledevice3's afc.py / crash_reports.py, which (without
`from __future__ import annotations`) are evaluated at function-definition time
— i.e. at import. So `Arg(...)` must be callable here. The shell methods that
actually use these are never run by the GUI."""

from typing import Annotated  # re-exported; Annotated[str, Arg(...)] must work


class Arg:
    def __init__(self, *args, **kwargs):
        pass


class ArgParserAlias:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return None
