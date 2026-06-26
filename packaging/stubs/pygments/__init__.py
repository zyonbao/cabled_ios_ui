"""Build-time stub for `pygments` (see packaging/stubs/README.md).

`highlight` is used only to colorize terminal/shell output the GUI never shows.
Passthrough returns the source text unchanged (no syntax coloring)."""


def highlight(code, lexer=None, formatter=None, *args, **kwargs):
    return code
