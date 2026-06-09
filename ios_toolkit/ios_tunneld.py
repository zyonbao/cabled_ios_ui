"""ios_tunneld.py — development-only launcher for the iOS XPC tunnel daemon.

The Nuitka multidist tunneld --main now lives at the repo root in
``cabled_ios_tunnel.py`` (so ios_toolkit/ never becomes a top-level import root
and ``secrets.py`` cannot shadow the stdlib ``secrets`` module). This in-package
module is kept only as a convenience launcher for non-packaged (development) runs.

IMPORTANT: start it as a module, e.g. ``python -m ios_toolkit.ios_tunneld`` (or
``python -m ios_toolkit.tunneld_main``). Do NOT run it by file path
(``python ios_toolkit/ios_tunneld.py``): that puts ios_toolkit/ on sys.path[0]
and ``secrets.py`` would shadow the stdlib ``secrets`` that pymobiledevice3 needs.

All real logic lives in ``ios_toolkit.tunneld_main``.
"""

from __future__ import annotations

from ios_toolkit.tunneld_main import main

if __name__ == "__main__":
    main()
