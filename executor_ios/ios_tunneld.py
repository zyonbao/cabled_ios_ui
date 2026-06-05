"""ios_tunneld.py — development-only launcher for the iOS XPC tunnel daemon.

The Nuitka multidist tunneld --main now lives at the repo root in
``cabled_ios_tunnel.py`` (so executor_ios/ never becomes a top-level import root
and ``secrets.py`` cannot shadow the stdlib ``secrets`` module). This in-package
module is kept only as a convenience launcher for non-packaged (development) runs.

IMPORTANT: start it as a module, e.g. ``python -m executor_ios.ios_tunneld`` (or
``python -m executor_ios.tunneld_main``). Do NOT run it by file path
(``python executor_ios/ios_tunneld.py``): that puts executor_ios/ on sys.path[0]
and ``secrets.py`` would shadow the stdlib ``secrets`` that pymobiledevice3 needs.

All real logic lives in ``executor_ios.tunneld_main``.
"""

from __future__ import annotations

from executor_ios.tunneld_main import main

if __name__ == "__main__":
    main()
