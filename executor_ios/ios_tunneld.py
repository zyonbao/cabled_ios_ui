"""ios_tunneld.py — Nuitka multidist entry point for the iOS XPC tunnel daemon.

This thin wrapper exists so the multidist entry's basename is ``ios_tunneld``,
which is the name the frozen app bundle invokes (see slide6_console/tunnel.py).
Nuitka dispatches multidist entry points by the basename of ``sys.argv[0]``, so
the wrapper's filename — not its contents — determines the dispatch name.

All real logic lives in ``executor_ios.tunneld_main``.
"""

from __future__ import annotations

from executor_ios.tunneld_main import main

if __name__ == "__main__":
    main()
