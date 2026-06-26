#!/usr/bin/env bash
#
# build_macos_app.sh — Build CablediOS.app with Nuitka (multidist, standalone).
#
# Produces a non-onefile macOS .app bundle that contains BOTH entry points
# (the PySide6 GUI and the iOS XPC tunnel daemon) sharing a single dependency
# tree via Nuitka multidist. The shared deps (pymobiledevice3, cryptography,
# libpython, ...) are therefore packaged only once.
#
# Entry-point dispatch is by sys.argv[0] basename:
#   - GUI:     CablediOS.py        -> basename "CablediOS"
#   - tunneld: cabled_ios_tunnel.py -> basename "cabled_ios_tunnel"
# After the build we add a "cabled_ios_tunnel" executable next to the GUI binary in
# Contents/MacOS/ so slide6_ui/tunnel.py can launch it under elevation.
#
# Why both --main files live at the repo root:
#   A Nuitka multidist --main is compiled as a top-level __main__ and its
#   directory becomes a top-level import root. Keeping every --main at the repo
#   root means ios_toolkit/ never becomes such a root, so ios_toolkit/secrets.py
#   can never shadow the stdlib "secrets" module that pymobiledevice3 imports.
#   (This is why the tunneld --main is cabled_ios_tunnel.py here, not the in-package
#   ios_toolkit/ios_tunneld.py — and why credentials.py could be renamed back to
#   secrets.py.)
#
# Usage:
#   packaging/build_macos_app.sh
#
# The script is idempotent: it cleans its own output dir before each build.
#
# Known limitations (out of scope here):
#   - The app is NOT code-signed or notarized. First launch needs a manual
#     Gatekeeper allow (System Settings > Privacy & Security > Open Anyway).
#   - Nuitka multidist + --macos-create-app-bundle is flagged experimental; if
#     the bundle is not produced, the script falls back to two standalone
#     builds merged into one dist (see build_fallback()).

set -euo pipefail

# --- Paths ------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$REPO_ROOT/build/nuitka"
# Keep Nuitka's cache inside the workspace (survives BUILD_DIR cleanup, and
# avoids depending on a writable ~/Library/Caches).
CACHE_DIR="$REPO_ROOT/build/.nuitka-cache"
export NUITKA_CACHE_DIR="$CACHE_DIR"
APP_NAME="CablediOS"
# Build-time stub packages that shadow heavy interactive-shell libraries Nuitka
# would otherwise pull in (xonsh/pygments/IPython/traitlets/pygnuutils). See
# packaging/stubs/README.md. Prepended to PYTHONPATH for the build only.
STUBS_DIR="$SCRIPT_DIR/stubs"
ICON_SRC="$REPO_ROOT/slide6_ui/AppIcon.png"
ICON_ICNS="$BUILD_DIR/AppIcon.icns"
# GUI entry is a top-level launcher (absolute imports) so multidist does not
# break on relative imports; its basename becomes CFBundleExecutable.
GUI_MAIN="$REPO_ROOT/CablediOS.py"
# tunneld entry is a top-level launcher (repo root) so ios_toolkit/ never becomes
# a top-level import root; its basename becomes the multidist dispatch name.
TUNNELD_MAIN="$REPO_ROOT/cabled_ios_tunnel.py"
PYMOBILEDEVICE3_RES_DIR=""

# Prefer the project venv interpreter (it has the runtime deps installed).
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PY="$REPO_ROOT/.venv/bin/python"
else
    PY="$(command -v python3 || true)"
fi

log()  { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# --- Pre-flight checks ------------------------------------------------------
preflight() {
    [[ "$(uname -s)" == "Darwin" ]] || die "This script must run on macOS."
    [[ -n "$PY" && -x "$PY" ]] || die "No usable Python interpreter found (looked for .venv/bin/python and python3)."

    "$PY" -c "import nuitka" 2>/dev/null \
        || die "Nuitka is not installed for $PY. Install with: $PY -m pip install -r packaging/requirements-build.txt"
    "$PY" -c "import PySide6" 2>/dev/null \
        || die "PySide6 is not installed for $PY. Install with: $PY -m pip install -r slide6_ui/requirements.txt"
    "$PY" -c "import pymobiledevice3" 2>/dev/null \
        || die "pymobiledevice3 is not installed for $PY. Install with: $PY -m pip install -r ios_toolkit/requirements.txt"
    "$PY" -c "import pillow_heif" 2>/dev/null \
        || die "pillow-heif is not installed for $PY (needed for album HEIC decoding). Install with: $PY -m pip install -r slide6_ui/requirements.txt"

    command -v iconutil >/dev/null 2>&1 || warn "iconutil not found; icon generation may fail."
    command -v sips >/dev/null 2>&1 || warn "sips not found; icon generation may fail."

    PYMOBILEDEVICE3_RES_DIR="$("$PY" -c 'import pathlib, pymobiledevice3; print(pathlib.Path(pymobiledevice3.__file__).resolve().parent / "resources")')"
    [[ -d "$PYMOBILEDEVICE3_RES_DIR" ]] || die "pymobiledevice3 resources directory not found: $PYMOBILEDEVICE3_RES_DIR"
    [[ -f "$PYMOBILEDEVICE3_RES_DIR/webinspector/find_nodes.js" ]] || die "pymobiledevice3 Web Inspector resource missing: $PYMOBILEDEVICE3_RES_DIR/webinspector/find_nodes.js"

    log "Interpreter: $PY"
    log "Nuitka:      $("$PY" -m nuitka --version 2>/dev/null | head -n1)"
    log "pymobiledevice3 resources: $PYMOBILEDEVICE3_RES_DIR"
}

# --- Icon generation (PNG -> .icns) -----------------------------------------
# Returns 0 and sets ICON_FLAG when an icns is produced; otherwise leaves
# ICON_FLAG empty so the build proceeds with the default icon.
ICON_FLAG=""
generate_icon() {
    if [[ ! -f "$ICON_SRC" ]]; then
        warn "App icon not found at $ICON_SRC; building with the default icon."
        return 0
    fi
    if ! command -v sips >/dev/null 2>&1 || ! command -v iconutil >/dev/null 2>&1; then
        warn "sips/iconutil unavailable; building with the default icon."
        return 0
    fi

    local iconset="$BUILD_DIR/AppIcon.iconset"
    rm -rf "$iconset"
    mkdir -p "$iconset"

    # Standard macOS iconset matrix (1x and 2x for each base size).
    local sizes=(16 32 128 256 512)
    for s in "${sizes[@]}"; do
        sips -z "$s" "$s"           "$ICON_SRC" --out "$iconset/icon_${s}x${s}.png"     >/dev/null
        sips -z $((s * 2)) $((s * 2)) "$ICON_SRC" --out "$iconset/icon_${s}x${s}@2x.png" >/dev/null
    done

    # Capture iconutil's real error instead of discarding it.  A misleading
    # "Invalid Iconset" here is most often an environment issue (e.g. iconutil
    # cannot reach the system IconServices daemon when run inside a sandbox),
    # NOT a problem with the iconset itself, so surface the message to help
    # diagnosis rather than silently falling back to the default icon.
    local iconutil_err
    if iconutil_err="$(iconutil -c icns "$iconset" -o "$ICON_ICNS" 2>&1)"; then
        ICON_FLAG="--macos-app-icon=$ICON_ICNS"
        log "Generated icon: $ICON_ICNS"
    else
        warn "iconutil failed; building with the default icon."
        [[ -n "$iconutil_err" ]] && warn "iconutil: $iconutil_err"
    fi
}

# Common Nuitka flags that shrink the binary and improve startup.
#
#   --python-flag=no_docstrings  Remove all docstring constants from compiled
#       code.  pymobiledevice3 has extensive docs; this is the single biggest
#       safe size win (~5-15 % reduction of the main binary).
#   --deployment                 Disable Nuitka's developer-aid checks (e.g.
#       "-c" guard, sys.path probes) that would never fire in a deployed app.
#       Removes a small amount of startup overhead.
#
# NOTE: do NOT add `--python-flag=-O` (or `--python-flag=no_asserts`).
#   `-O` strips every `assert` statement, and pymobiledevice3 puts wire-protocol
#   side effects *inside* asserts (e.g. os_trace.syslog() consumes the one-byte
#   `\x02` record separator via `assert await recvall(1) == b"\x02"`; collect()/
#   create_archive() likewise read framing bytes inside asserts). Stripping them
#   desyncs the stream framing — the oslog stream then returns a single giant,
#   mis-parsed entry (raw bytes, pid=0). The plain `python CablediOS.py` run
#   keeps asserts, which is why it works; the packaged app must do the same.
#   --nofollow-import-to=jedi,parso  Drop the Jedi static-analysis engine and
#       its parser. pymobiledevice3 hard-imports IPython (utils.py) and xonsh
#       (afc.py, crash_reports.py) at module top level, so those must stay — but
#       Jedi is only IPython's *optional* tab-completion backend, guarded by
#       `try: import jedi ... except: JEDI_INSTALLED = False`
#       (IPython/core/completer.py). This app never opens an IPython/xonsh shell,
#       so excluding Jedi is safe and saves ~28 MB (≈14 MB compiled into the
#       binary + ≈14.5 MB of bundled grammar/typeshed data). parso has no other
#       importer, so it drops with Jedi.
#   --nofollow-import-to=pymobiledevice3.cli,prompt_toolkit
#       --include-package=pymobiledevice3 (below) force-compiles the WHOLE package,
#       including the click-based CLI command tree the GUI never imports (verified:
#       loading every pymobiledevice3 module the app actually uses never pulls in
#       cli). The CLI is reached only via `python -m pymobiledevice3`, never by the
#       app. cli/webinspector.py is the sole importer of prompt_toolkit (~13 MB),
#       so excluding cli already orphans it; prompt_toolkit is listed explicitly as
#       a belt-and-suspenders guard against future pymobiledevice3 changes. Other
#       pymobiledevice3 modules (services, restore, irecv, bonjour, osu, …) are
#       genuinely reachable and intentionally kept.
#   --nofollow-import-to=psutil._pslinux,psutil._psbsd,psutil._pssunos,...
#       psutil picks its backend at runtime (`if LINUX: from . import _pslinux`),
#       but Nuitka can't evaluate the platform guard so it compiles EVERY backend.
#       On macOS only _psosx/_psposix run, so the Linux/BSD/SunOS/AIX/Windows
#       backends (~2 MB) are dead code.
# NOTE: --lto=yes was tried and REVERTED — it made the binary ~10 MB *larger*
# (183 → 193 MB) and roughly doubled build time. LTO's aggressive cross-module
# inlining duplicates code across the many call sites in this large codebase,
# outweighing its dead-code elimination. Net loss here; do not re-add.
COMMON_FLAGS=(
    --python-flag=no_docstrings
    --deployment
    --nofollow-import-to=jedi,parso,pymobiledevice3.cli,prompt_toolkit,psutil._pslinux,psutil._psbsd,psutil._pssunos,psutil._psaix,psutil._pswindows
    --assume-yes-for-downloads
    --output-dir="$BUILD_DIR"
)

# --- Primary build: multidist standalone app bundle -------------------------
run_nuitka_multidist() {
    log "Running Nuitka multidist build (this can take several minutes)…"
    # shellcheck disable=SC2086 -- ICON_FLAG is intentionally word-split (may be empty)
    "$PY" -m nuitka \
        --standalone \
        --macos-create-app-bundle \
        --macos-app-name="$APP_NAME" \
        $ICON_FLAG \
        --enable-plugin=pyside6 \
        --include-package=pymobiledevice3 \
        --include-package=ios_toolkit \
        --include-data-dir="$PYMOBILEDEVICE3_RES_DIR=pymobiledevice3/resources" \
        --include-data-files="$REPO_ROOT/ios_toolkit/ddi_image_index.json=ios_toolkit/ddi_image_index.json" \
        --include-package=slide6_ui \
        --include-data-dir="$REPO_ROOT/slide6_ui/languages=slide6_ui/languages" \
        --include-package=pillow_heif \
        --include-package=PIL \
        "${COMMON_FLAGS[@]}" \
        --main="$GUI_MAIN" \
        --main="$TUNNELD_MAIN"
}

# --- Post-process: dedup versioned dylib pairs ------------------------------
# Nuitka copies symlinks as full files.  Pairs like libcrypto.dylib /
# libcrypto.3.dylib end up as identical copies.  Replace the shorter-named
# entry with a symlink to its versioned counterpart so each physical file is
# stored only once.
dedup_dylibs() {
    local macos_dir="$1"
    log "Deduplicating versioned dylib pairs in MacOS/…"
    local saved=0
    # Find files whose name without a leading version looks like an existing
    # shorter sibling: e.g. libcrypto.3.dylib -> libcrypto.dylib.
    while IFS= read -r versioned; do
        local base
        base="$(basename "$versioned")"
        # Extract the unversioned name: remove the first numeric component.
        # libcrypto.3.dylib  -> libcrypto.dylib
        # libsqlite3.0.dylib -> libsqlite3.dylib
        local unversioned_base
        unversioned_base="$(echo "$base" | sed -E 's/\.[0-9]+(\.[0-9]+)*\.dylib$/.dylib/')"
        [[ "$unversioned_base" == "$base" ]] && continue   # no version removed
        local unversioned="$macos_dir/$unversioned_base"
        [[ -f "$unversioned" ]] || continue
        # Only replace when both files are byte-identical.
        if cmp -s "$versioned" "$unversioned"; then
            local sz
            sz="$(stat -f%z "$unversioned")"
            rm "$unversioned"
            ln -s "$base" "$unversioned"
            saved=$(( saved + sz ))
            log "  symlinked: $unversioned_base -> $base  (saved $(( sz / 1024 )) KB)"
        fi
    done < <(find "$macos_dir" -maxdepth 1 -name '*.dylib' -type f | sort)
    log "Dylib dedup done (saved ~$(( saved / 1024 )) KB total)."
}

# --- Locate the produced .app bundle ----------------------------------------
find_app_bundle() {
    # Nuitka may name the bundle after the first main ("CablediOS.app") or the
    # app name; pick the most recently produced .app under the output dir.
    find "$BUILD_DIR" -maxdepth 2 -name '*.app' -type d 2>/dev/null \
        | head -n1
}

# --- Read CFBundleExecutable (the GUI dispatch binary) ----------------------
bundle_executable() {
    local app="$1"
    /usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "$app/Contents/Info.plist" 2>/dev/null
}

# --- Add the cabled_ios_tunnel dispatch entry next to the GUI binary ----------
add_tunneld_entry() {
    local app="$1"
    local macos_dir="$app/Contents/MacOS"
    local gui_bin
    gui_bin="$(bundle_executable "$app")"
    [[ -n "$gui_bin" && -x "$macos_dir/$gui_bin" ]] \
        || die "Could not resolve the GUI binary (CFBundleExecutable) in $app."

    # A relative symlink keeps the bundle relocatable; the multidist binary
    # dispatches to the tunneld entry because argv[0] basename is "cabled_ios_tunnel".
    ln -sf "$gui_bin" "$macos_dir/cabled_ios_tunnel"
    log "Linked tunneld entry: Contents/MacOS/cabled_ios_tunnel -> $gui_bin"
}

# --- Fallback: two standalone builds merged into one dist -------------------
# Build the GUI app bundle and the tunneld binary separately, then overlay the
# tunneld dist onto the app's Contents/MacOS so they share one dependency tree.
# Echoes the resulting .app path on success.
build_fallback() {
    warn "Falling back to two standalone builds merged into one bundle."

    log "Fallback 1/3: building GUI app bundle…"
    # shellcheck disable=SC2086
    "$PY" -m nuitka \
        --standalone \
        --macos-create-app-bundle \
        --macos-app-name="$APP_NAME" \
        $ICON_FLAG \
        --enable-plugin=pyside6 \
        --include-package=pymobiledevice3 \
        --include-package=ios_toolkit \
        --include-data-dir="$PYMOBILEDEVICE3_RES_DIR=pymobiledevice3/resources" \
        --include-data-files="$REPO_ROOT/ios_toolkit/ddi_image_index.json=ios_toolkit/ddi_image_index.json" \
        --include-package=slide6_ui \
        --include-data-dir="$REPO_ROOT/slide6_ui/languages=slide6_ui/languages" \
        --include-package=pillow_heif \
        --include-package=PIL \
        "${COMMON_FLAGS[@]}" \
        "$GUI_MAIN" >&2

    log "Fallback 2/3: building tunneld binary…"
    "$PY" -m nuitka \
        --standalone \
        --include-package=pymobiledevice3 \
        --include-package=ios_toolkit \
        --include-data-dir="$PYMOBILEDEVICE3_RES_DIR=pymobiledevice3/resources" \
        "${COMMON_FLAGS[@]}" \
        "$TUNNELD_MAIN" >&2

    local app tunneld_dist tunneld_bin macos_dir
    app="$(find_app_bundle)"
    [[ -n "$app" ]] || die "Fallback: GUI app bundle was not produced."
    tunneld_dist="$BUILD_DIR/cabled_ios_tunnel.dist"
    [[ -d "$tunneld_dist" ]] || die "Fallback: tunneld dist was not produced at $tunneld_dist."

    macos_dir="$app/Contents/MacOS"
    log "Fallback 3/3: overlaying tunneld dist into ${macos_dir} ..."
    # Overlay everything except the tunneld entry binary; shared libs are
    # identical (same build env), new files (none expected) are added.
    tunneld_bin="$(find "$tunneld_dist" -maxdepth 1 -type f -perm -111 -name 'cabled_ios_tunnel*' | head -n1)"
    [[ -n "$tunneld_bin" ]] || die "Fallback: tunneld executable not found in $tunneld_dist."
    rsync -a --ignore-existing \
        --exclude "$(basename "$tunneld_bin")" \
        "$tunneld_dist"/ "$macos_dir"/ >&2
    cp -f "$tunneld_bin" "$macos_dir/cabled_ios_tunnel"
    chmod +x "$macos_dir/cabled_ios_tunnel"

    echo "$app"
}

# --- Prune Qt modules the app never imports ---------------------------------
# The Nuitka pyside6 plugin bundles a few Qt frameworks the GUI never uses. The
# code only imports QtCore/QtGui/QtWidgets. Two frameworks are dead weight:
#   - QtNetwork  : Qt's own HTTP/SSL stack. All networking here goes through
#                  pymobiledevice3 / requests, never Qt — so its framework,
#                  Python binding and TLS backend plugins are unused.
#   - QtPdf      : pulled only by the imageformats/libqpdf plugin (renders a PDF
#                  as an image). The album shows photos, never PDFs.
# Verified safe by launch test: the app starts and pairs devices without them.
# NOTE: deleting bundle files invalidates the code seal — codesign_app re-signs
# (ad-hoc) afterward, which is mandatory or arm64 macOS SIGKILLs the app.
prune_unused_qt() {
    local app="$1"
    local macos_dir="$app/Contents/MacOS"
    log "Pruning unused Qt modules (QtNetwork, QtPdf)…"
    local before after
    before="$(du -sk "$app" | cut -f1)"
    rm -f  "$macos_dir/QtPdf"     "$macos_dir/PySide6/QtPdf.so"
    rm -f  "$macos_dir/PySide6/qt-plugins/imageformats/libqpdf.dylib"
    rm -f  "$macos_dir/QtNetwork" "$macos_dir/PySide6/QtNetwork.so"
    rm -rf "$macos_dir/PySide6/qt-plugins/tls"
    after="$(du -sk "$app" | cut -f1)"
    # Safety guard: warn (do not fail) if a surviving Mach-O still links a
    # removed framework, which would mean the prune list is too aggressive.
    local cand refs
    for cand in QtPdf QtNetwork; do
        refs="$(find "$macos_dir" -maxdepth 3 \( -name 'Qt*' -o -name '*.so' -o -name '*.dylib' \) -type f \
            -exec sh -c 'otool -L "$1" 2>/dev/null | grep -q "/'"$cand"'\\." && basename "$1"' _ {} \; 2>/dev/null)"
        [[ -n "$refs" ]] && warn "Removed $cand but still referenced by:$(echo "$refs" | tr '\n' ' ')"
    done
    log "Qt prune done (saved ~$(( (before - after) / 1024 )) MB)."
}

# --- Prune the unused AVIF image codec --------------------------------------
# Pillow 11 ships a native AVIF plugin (PIL/_avif.so) that links libavif
# (~3 MB). The app only ever decodes HEIC (via pillow_heif → libheif, which does
# NOT depend on libavif) plus the usual JPEG/PNG; it never opens AVIF. PIL's
# AvifImagePlugin imports _avif under try/except ImportError and just sets
# SUPPORTED=False when it (or libavif) is missing, so dropping both degrades
# gracefully. Verified by launch test. (NOTE: re-signed afterward by codesign_app.)
prune_unused_avif() {
    local app="$1"
    local macos_dir="$app/Contents/MacOS"
    [[ -f "$macos_dir/PIL/_avif.so" || -n "$(echo "$macos_dir"/libavif*)" ]] || return 0
    log "Pruning unused AVIF codec (libavif, PIL/_avif.so)…"
    local before after
    before="$(du -sk "$app" | cut -f1)"
    rm -f "$macos_dir"/libavif* "$macos_dir/PIL/_avif.so"
    after="$(du -sk "$app" | cut -f1)"
    # Guard: warn if anything surviving still links libavif (it shouldn't).
    local refs
    refs="$(find "$macos_dir" -maxdepth 2 \( -name '*.so' -o -name '*.dylib' \) -type f \
        -exec sh -c 'otool -L "$1" 2>/dev/null | grep -q libavif && basename "$1"' _ {} \; 2>/dev/null)"
    [[ -n "$refs" ]] && warn "Removed libavif but still referenced by:$(echo "$refs" | tr '\n' ' ')"
    log "AVIF prune done (saved ~$(( (before - after) / 1024 )) MB)."
}

# --- Strip symbols from the compiled binary and native libs -----------------
# Nuitka/clang leave symbol tables in the (large) main binary and in the bundled
# .dylib/.so files. `strip -x` removes local (non-global) symbols only, keeping
# the external/global symbols dynamic linking needs — safe for both the main
# executable and shared libraries. Must run BEFORE code-signing (stripping a
# signed binary invalidates its signature). Per-file failures are tolerated so a
# single odd library never aborts the build.
strip_bundle() {
    local app="$1"
    local macos_dir="$app/Contents/MacOS"
    command -v strip >/dev/null 2>&1 || { warn "strip not found; skipping symbol strip."; return 0; }
    log "Stripping local symbols from binary and native libs…"
    local before after
    before="$(du -sk "$app" | cut -f1)"
    # The main executable plus every Mach-O dylib/so under MacOS/.
    while IFS= read -r f; do
        strip -x "$f" 2>/dev/null || true
    done < <(find "$macos_dir" -type f \( -name '*.dylib' -o -name '*.so' -o -perm -111 \) ! -type l)
    after="$(du -sk "$app" | cut -f1)"
    log "Symbol strip done (saved ~$(( (before - after) / 1024 )) MB)."
}

# --- Optional: code-sign with hardened runtime + entitlements ---------------
# Unsigned by default (first launch needs a manual Gatekeeper allow). Set
# CODESIGN_IDENTITY to a signing identity to sign the bundle with
# packaging/entitlements.plist. Signing + hardened runtime is what makes the
# macOS native file panel reliable, after which
# slide6_ui/common/file_dialogs.USE_NATIVE_FILE_DIALOG can be flipped to True.
#   List identities:  security find-identity -v -p codesigning
#   Example:          CODESIGN_IDENTITY="Developer ID Application: NAME (TEAMID)" \
#                         packaging/build_macos_app.sh
ENTITLEMENTS="$SCRIPT_DIR/entitlements.plist"
codesign_app() {
    local app="$1"
    if [[ -z "${CODESIGN_IDENTITY:-}" ]]; then
        # Our post-processing (dedup_dylibs, prune_unused_qt, strip_bundle) edits
        # files inside the bundle, which invalidates the ad-hoc seal Nuitka
        # applied. On Apple Silicon an invalid seal makes the kernel SIGKILL the
        # app on launch (it dies silently with no output). Re-seal it ad-hoc so
        # it launches; this still needs the usual first-launch Gatekeeper allow.
        if command -v codesign >/dev/null 2>&1; then
            log "CODESIGN_IDENTITY not set; re-sealing bundle with an ad-hoc signature."
            codesign --force --deep -s - "$app" >/dev/null 2>&1 \
                || warn "Ad-hoc re-sign failed; the app may be SIGKILL'd on launch."
        else
            warn "codesign not found; bundle left with an invalidated seal (may be SIGKILL'd on launch)."
        fi
        return 0
    fi
    [[ -f "$ENTITLEMENTS" ]] || die "Entitlements file not found: $ENTITLEMENTS"
    command -v codesign >/dev/null 2>&1 || die "codesign not found (install Xcode command line tools)."
    log "Code-signing with hardened runtime: $CODESIGN_IDENTITY"
    # --deep signs nested dylibs/binaries; --options runtime enables the
    # hardened runtime that the entitlements complement.
    codesign --force --deep --options runtime \
        --entitlements "$ENTITLEMENTS" \
        --sign "$CODESIGN_IDENTITY" "$app"
    if codesign --verify --strict --verbose=2 "$app" 2>&1; then
        log "Code-sign verification passed."
    else
        warn "Code-sign verification reported issues; check the output above."
    fi
    log "Signed. You can now set USE_NATIVE_FILE_DIALOG=True and (optionally) notarize."
}

# --- Verify the produced bundle ---------------------------------------------
verify_bundle() {
    local app="$1"
    [[ -d "$app" ]] || die "App bundle missing: $app"
    [[ -e "$app/Contents/MacOS/cabled_ios_tunnel" ]] || die "cabled_ios_tunnel entry missing in $app."
    log "Verified: $app/Contents/MacOS/cabled_ios_tunnel present."
    [[ -f "$app/Contents/MacOS/pymobiledevice3/resources/webinspector/find_nodes.js" ]] \
        || die "Web Inspector resource missing in app bundle: $app/Contents/MacOS/pymobiledevice3/resources/webinspector/find_nodes.js"
    log "Verified: Web Inspector resource bundled."

    # Confirm the stubs shadowed the heavy shell libs (no real xonsh/pygments/
    # prompt_toolkit got compiled in). A leak here means the stub surface drifted
    # from pymobiledevice3 and the size win was silently lost.
    if [[ -d "$STUBS_DIR" ]]; then
        local macos_dir="$app/Contents/MacOS"
        local leaked=""
        # Real xonsh ships xonsh/parsers; real pygments ships pygments/lexers as a
        # package dir; the stubs ship neither as a directory tree.
        [[ -d "$macos_dir/xonsh/parsers" ]]        && leaked="$leaked xonsh"
        [[ -d "$macos_dir/prompt_toolkit" ]]       && leaked="$leaked prompt_toolkit"
        [[ -d "$macos_dir/pygments/lexers" ]]      && leaked="$leaked pygments"
        if [[ -n "$leaked" ]]; then
            warn "Shell-dep stubbing leaked — real packages bundled:$leaked. Check packaging/stubs/ against the current pymobiledevice3."
        else
            log "Verified: shell deps stubbed (no real xonsh/pygments/prompt_toolkit bundled)."
        fi
    fi
    if [[ -n "$ICON_FLAG" ]]; then
        # Use a glob expansion (globs do not expand inside [[ ... ]]).
        if compgen -G "$app/Contents/Resources/*.icns" >/dev/null; then
            log "Verified: app icon embedded."
        else
            warn "App icon not found in Resources (Nuitka may name it differently)."
        fi
    fi
}

# --- Main -------------------------------------------------------------------
main() {
    preflight

    # Shadow the interactive-shell libraries with build-time stubs so Nuitka
    # compiles those (tiny) instead of the real packages. pymobiledevice3
    # top-level-imports xonsh/pygments/IPython/traitlets/pygnuutils in shell code
    # paths the packaged GUI never runs (AfcShell, ServiceConnection.shell(),
    # start_ipython_shell). See packaging/stubs/README.md. Avoids ~70 MB of dead
    # compiled object code. Done after preflight so its import checks see the
    # real packages.
    if [[ -d "$STUBS_DIR" ]]; then
        export PYTHONPATH="$STUBS_DIR${PYTHONPATH:+:$PYTHONPATH}"
        log "Shadowing shell deps with build-time stubs: $STUBS_DIR"
    else
        warn "Stub dir not found ($STUBS_DIR); building with full shell deps (larger binary)."
    fi

    log "Cleaning output dir: $BUILD_DIR"
    # macOS (Finder/Spotlight) can recreate .DS_Store mid-deletion, making a
    # single `rm -rf` exit non-zero ("Directory not empty"). Retry a few times
    # and tolerate the race rather than aborting the whole build.
    local attempt
    for attempt in 1 2 3; do
        rm -rf "$BUILD_DIR" 2>/dev/null || true
        [[ -d "$BUILD_DIR" ]] || break
        sleep 1
    done
    [[ -d "$BUILD_DIR" ]] && warn "Could not fully clean $BUILD_DIR; continuing."
    mkdir -p "$BUILD_DIR" "$CACHE_DIR"

    generate_icon

    local app
    if run_nuitka_multidist && [[ -n "$(find_app_bundle)" ]]; then
        app="$(find_app_bundle)"
        add_tunneld_entry "$app"
    else
        # Multidist did not yield an app bundle; the fallback builds + merges
        # both standalone dists and adds the cabled_ios_tunnel entry itself.
        app="$(build_fallback)"
    fi

    # Rename the bundle to the desired product name (renaming the .app dir does
    # not affect CFBundleExecutable, so dispatch still works).
    local final_app="$BUILD_DIR/$APP_NAME.app"
    if [[ "$app" != "$final_app" ]]; then
        rm -rf "$final_app"
        mv "$app" "$final_app"
        app="$final_app"
    fi

    dedup_dylibs "$app/Contents/MacOS"
    prune_unused_qt "$app"
    prune_unused_avif "$app"
    strip_bundle "$app"
    verify_bundle "$app"
    # codesign_app re-seals the bundle (ad-hoc when unsigned); MUST run last, after
    # all post-processing that edits bundle files, or arm64 macOS SIGKILLs the app.
    codesign_app "$app"

    log "Done."
    printf '\n\033[1;32mBuilt:\033[0m %s\n' "$app"
    # Use plain printf (not a heredoc) for the trailing guidance: under bash 3.2
    # + `set -u` a heredoc that expands a function-local variable can spuriously
    # report it as unbound, which previously made the script exit 1 even though
    # the bundle built successfully.
    printf '\n%s\n' "First launch is blocked by Gatekeeper because the app is not signed/notarized."
    printf '%s\n' "To allow it:"
    printf '%s\n' "  - Right-click ${APP_NAME}.app > Open, then confirm, OR"
    printf '%s\n' "  - System Settings > Privacy & Security > \"Open Anyway\", OR"
    printf '%s\n' "  - Remove the quarantine attribute:"
    printf '%s\n' "      xattr -dr com.apple.quarantine \"${app}\""
}

main "$@"
