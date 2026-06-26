# Build-time stub packages (size optimization)

These are **minimal stand-in packages** that shadow heavy third-party libraries
during the Nuitka build *only*. They are prepended to `PYTHONPATH` by
`packaging/build_macos_app.sh` so Nuitka compiles these tiny modules instead of
the real ones, then never follows into the real (large) packages.

## Why

`pymobiledevice3` hard-imports several interactive-shell libraries at module top
level in code paths the **GUI never executes** (the `xonsh`-based AFC shell, the
`IPython`-based `ServiceConnection.shell()` / `start_ipython_shell()`, and the
crash-report shell). Because they are top-level imports, Nuitka pulls the entire
dependency chain — `xonsh`, `pygments`, `prompt_toolkit`, `traitlets`, `blessed`,
`IPython`, `pygnuutils`, `ply`, … — into the binary (~70 MB of compiled object
code) even though the packaged app only ever uses the *library* service API
(`AfcService`, `WebinspectorService`, `CrashReportsManager`), never the shells.

These stubs satisfy those top-level imports with no-op / passthrough symbols, so:
- `AfcService` and the other service classes import and work normally.
- The interactive shell entry points (which the GUI never calls) raise a clear
  error if ever invoked.

## Symbol surface (keep in sync with pymobiledevice3)

Only the symbols actually imported by app-reachable pymobiledevice3 modules are
provided. If a `pymobiledevice3` upgrade imports a new shell symbol, the build's
launch smoke test will surface an `ImportError`; add the missing symbol here.

| Stub        | Imported by (pymobiledevice3)                              | Symbols                                  |
|-------------|------------------------------------------------------------|------------------------------------------|
| `xonsh`     | `services/afc.py`, `services/crash_reports.py`             | `built_ins.XSH`, `cli_utils.{Annotated,Arg,ArgParserAlias}`, `main.main`, `tools.print_color` |
| `pygments`  | `services/afc.py`, `service_connection.py`, `remote/remotexpc.py` | `highlight`, `formatters.*`, `lexers.*` |
| `pygnuutils`| `services/afc.py`                                          | `ls.{Ls,LsStub}`, `cli.ls.ls`            |
| `IPython`   | `utils.py`                                                 | `start_ipython`                          |
| `traitlets` | `utils.py`                                                 | `config.Config`                          |

These stubs are **build-time only**: running `python CablediOS.py` from the repo
uses the real packages from the venv (this dir is not on the dev `sys.path`).
