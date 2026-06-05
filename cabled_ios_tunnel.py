"""cabled_ios_tunnel.py — Nuitka multidist entry point for the iOS XPC tunnel daemon.

This thin launcher sits at the repo root (alongside CablediOS.py) so the tunneld
multidist --main does NOT live inside the executor_ios package. Keeping every
--main at the top level means executor_ios/ never becomes a top-level import root,
so executor_ios/secrets.py can never shadow the stdlib ``secrets`` module that
pymobiledevice3 imports.

A multidist --main is compiled as a top-level __main__ with no parent package, so
it must use absolute imports only. The basename "cabled_ios_tunnel" becomes the
multidist dispatch name for the tunneld entry (see packaging/build_macos_app.sh
and slide6_console/tunnel.py). All real logic lives in executor_ios.tunneld_main.
"""

from __future__ import annotations

from executor_ios.tunneld_main import main

if __name__ == "__main__":
    main()
