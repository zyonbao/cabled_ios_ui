"""CablediOS.py — Nuitka multidist GUI entry point for the desktop console.

A multidist --main is compiled as a top-level __main__ with no parent package,
so it must NOT use relative imports. This thin launcher imports the package
absolutely and delegates to slide6_console.app.main(), keeping the real GUI code
(which uses intra-package relative imports) importable as part of its package.

The basename "CablediOS" becomes the app bundle's CFBundleExecutable and the
multidist dispatch name for the GUI entry (see packaging/build_macos_app.sh).
"""

from __future__ import annotations

from slide6_console.app import main

if __name__ == "__main__":
    main()
