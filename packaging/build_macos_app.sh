#!/usr/bin/env bash
#
# build_macos_app.sh — Build CablediOS.app with Nuitka (two-pass standalone).
#
# Strategy: build the GUI app bundle and the tunneld binary separately, then
# copy the tunneld binary into the app bundle.
#
#   Pass 1 — GUI app bundle (CablediOS.app):
#     Entry:  CablediOS.py  (absolute-import launcher for slide6_console.app)
#     Includes: executor_ios, slide6_console, pymobiledevice3, PySide6
#
#   Pass 2 — tunneld standalone binary (ios_tunneld.dist/ios_tunneld):
#     Entry:  executor_ios/ios_tunneld.py
#     Includes: pymobiledevice3 only (NOT --include-package=executor_ios)
#
# Why two passes?
#   The tunneld binary must NOT bundle executor_ios/secrets.py.  That file is
#   a package-private credential helper that shares its base name with the
#   stdlib "secrets" module.  Nuitka's frozen importer can resolve a bare
#   `import secrets` to the user module instead of stdlib, breaking
#   pymobiledevice3 (which calls secrets.token_hex).  By letting Nuitka follow
#   only the actual import graph from ios_tunneld.py (-> tunneld_main ->
#   pymobiledevice3), secrets.py is never bundled and the collision cannot
#   occur.  The GUI pass still uses --include-package=executor_ios because the
#   GUI needs executor_ios.secrets for the type_credential capability.
#
# Usage:
#   packaging/build_macos_app.sh
#
# The script is idempotent: it cleans its own output dir before each build.
#
# Known limitations (out of scope here):
#   - The app is NOT code-signed or notarized. First launch needs a manual
#     Gatekeeper allow (System Settings > Privacy & Security > Open Anyway).

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
# GUI entry: top-level launcher with absolute imports (avoids relative-import
# issues when compiled as a top-level __main__ by Nuitka).
GUI_MAIN="$REPO_ROOT/CablediOS.py"
# Tunneld entry: basename "ios_tunneld" must match the binary name looked up
# by slide6_console/tunnel.py inside the frozen app bundle.
TUNNELD_MAIN="$REPO_ROOT/executor_ios/ios_tunneld.py"

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

    if iconutil -c icns "$iconset" -o "$ICON_ICNS" >/dev/null 2>&1; then
        ICON_FLAG="--macos-app-icon=$ICON_ICNS"
        log "Generated icon: $ICON_ICNS"
    else
        warn "iconutil failed; building with the default icon."
    fi
}

# --- Pass 1: GUI app bundle -------------------------------------------------
build_gui() {
    log "Pass 1/2: building GUI app bundle (this can take several minutes)…"
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
        --assume-yes-for-downloads \
        --output-dir="$BUILD_DIR" \
        "$GUI_MAIN"
}

# --- Pass 2: tunneld binary (no executor_ios package) -----------------------
build_tunneld() {
    log "Pass 2/2: building tunneld binary…"
    # IMPORTANT: do NOT add --include-package=executor_ios here.
    # Nuitka will include executor_ios.tunneld_main by following the import
    # graph from ios_tunneld.py.  The rest of the executor_ios package
    # (including secrets.py) must stay out of this binary so it cannot shadow
    # the stdlib secrets module that pymobiledevice3 depends on.
    "$PY" -m nuitka \
        --standalone \
        --include-package=pymobiledevice3 \
        --assume-yes-for-downloads \
        --output-dir="$BUILD_DIR" \
        "$TUNNELD_MAIN"
}

# --- Locate the produced .app bundle ----------------------------------------
find_app_bundle() {
    # Nuitka may name the bundle after the first main or the app name; pick
    # the most recently produced .app under the output dir.
    find "$BUILD_DIR" -maxdepth 2 -name '*.app' -type d 2>/dev/null \
        | head -n1
}

# --- Merge tunneld binary into the GUI app bundle ---------------------------
merge_tunneld() {
    local app="$1"
    local macos_dir="$app/Contents/MacOS"
    local tunneld_dist="$BUILD_DIR/ios_tunneld.dist"

    [[ -d "$tunneld_dist" ]] || die "tunneld dist not found at $tunneld_dist."

    local tunneld_bin
    tunneld_bin="$(find "$tunneld_dist" -maxdepth 1 -type f -perm -111 -name 'ios_tunneld*' | head -n1)"
    [[ -n "$tunneld_bin" ]] || die "tunneld executable not found in $tunneld_dist."

    log "Merging tunneld into app bundle…"

    # Copy tunneld binary as ios_tunneld (the name tunnel.py looks up).
    cp -f "$tunneld_bin" "$macos_dir/ios_tunneld"
    chmod +x "$macos_dir/ios_tunneld"

    # Overlay any additional shared libs the tunneld build needed that are not
    # already present in the GUI bundle (rsync --ignore-existing is safe here
    # because both builds use the same environment).
    rsync -a --ignore-existing \
        --exclude "$(basename "$tunneld_bin")" \
        "$tunneld_dist"/ "$macos_dir"/ 2>/dev/null || true

    log "Tunneld installed: Contents/MacOS/ios_tunneld"
}

# --- Verify the produced bundle ---------------------------------------------
verify_bundle() {
    local app="$1"
    [[ -d "$app" ]] || die "App bundle missing: $app"
    [[ -e "$app/Contents/MacOS/ios_tunneld" ]] || die "ios_tunneld entry missing in $app."
    log "Verified: $app/Contents/MacOS/ios_tunneld present."
    if [[ -n "$ICON_FLAG" ]]; then
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
    build_gui

    local app
    app="$(find_app_bundle)"
    [[ -n "$app" ]] || die "GUI app bundle was not produced."

    build_tunneld
    merge_tunneld "$app"

    # Rename the bundle to the desired product name (renaming the .app dir
    # does not affect CFBundleExecutable, so the GUI binary still works).
    local final_app="$BUILD_DIR/$APP_NAME.app"
    if [[ "$app" != "$final_app" ]]; then
        rm -rf "$final_app"
        mv "$app" "$final_app"
        app="$final_app"
    fi

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
