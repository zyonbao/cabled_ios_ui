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
# Contents/MacOS/ so slide6_console/tunnel.py can launch it under elevation.
#
# Why both --main files live at the repo root:
#   A Nuitka multidist --main is compiled as a top-level __main__ and its
#   directory becomes a top-level import root. Keeping every --main at the repo
#   root means executor_ios/ never becomes such a root, so executor_ios/secrets.py
#   can never shadow the stdlib "secrets" module that pymobiledevice3 imports.
#   (This is why the tunneld --main is cabled_ios_tunnel.py here, not the in-package
#   executor_ios/ios_tunneld.py — and why credentials.py could be renamed back to
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
ICON_SRC="$REPO_ROOT/slide6_console/AppIcon.png"
ICON_ICNS="$BUILD_DIR/AppIcon.icns"
# GUI entry is a top-level launcher (absolute imports) so multidist does not
# break on relative imports; its basename becomes CFBundleExecutable.
GUI_MAIN="$REPO_ROOT/CablediOS.py"
# tunneld entry is a top-level launcher (repo root) so executor_ios/ never becomes
# a top-level import root; its basename becomes the multidist dispatch name.
TUNNELD_MAIN="$REPO_ROOT/cabled_ios_tunnel.py"

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
        || die "PySide6 is not installed for $PY. Install with: $PY -m pip install -r slide6_console/requirements.txt"
    "$PY" -c "import pymobiledevice3" 2>/dev/null \
        || die "pymobiledevice3 is not installed for $PY. Install with: $PY -m pip install -r executor_ios/requirements.txt"

    command -v iconutil >/dev/null 2>&1 || warn "iconutil not found; icon generation may fail."
    command -v sips >/dev/null 2>&1 || warn "sips not found; icon generation may fail."

    log "Interpreter: $PY"
    log "Nuitka:      $("$PY" -m nuitka --version 2>/dev/null | head -n1)"
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
#   --python-flag=-O             Python -O mode: strip assert statements and set
#       __debug__ = False. Equivalent to running `python -O`.
#   --deployment                 Disable Nuitka's developer-aid checks (e.g.
#       "-c" guard, sys.path probes) that would never fire in a deployed app.
#       Removes a small amount of startup overhead.
COMMON_FLAGS=(
    --python-flag=no_docstrings
    --python-flag=-O
    --deployment
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
        --include-package=executor_ios \
        --include-package=slide6_console \
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
        --include-package=executor_ios \
        --include-package=slide6_console \
        "${COMMON_FLAGS[@]}" \
        "$GUI_MAIN" >&2

    log "Fallback 2/3: building tunneld binary…"
    "$PY" -m nuitka \
        --standalone \
        --include-package=pymobiledevice3 \
        --include-package=executor_ios \
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

# --- Verify the produced bundle ---------------------------------------------
verify_bundle() {
    local app="$1"
    [[ -d "$app" ]] || die "App bundle missing: $app"
    [[ -e "$app/Contents/MacOS/cabled_ios_tunnel" ]] || die "cabled_ios_tunnel entry missing in $app."
    log "Verified: $app/Contents/MacOS/cabled_ios_tunnel present."
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
    verify_bundle "$app"

    log "Done."
    printf '\n\033[1;32mBuilt:\033[0m %s\n' "$app"
    cat <<EOF

First launch is blocked by Gatekeeper because the app is not signed/notarized.
To allow it:
  - Right-click $APP_NAME.app > Open, then confirm, OR
  - System Settings > Privacy & Security > "Open Anyway", OR
  - Remove the quarantine attribute:
      xattr -dr com.apple.quarantine "$app"
EOF
}

main "$@"
