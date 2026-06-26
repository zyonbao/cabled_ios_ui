#!/usr/bin/env python3
"""
appicon.py — Build the macOS app icon from one full-bleed master.

macOS 26 (Tahoe) applies its own squircle mask + Liquid Glass treatment and
expects a FULL-BLEED master (artwork reaching every edge, no rounded corners,
no margin). Older macOS shows the .icns pixels as-is, so it needs the classic
rounded-rect shape + margin baked in. These are contradictory, so we pick per
the available tooling:

  * actool available (Xcode 26+):  ship BOTH, each system gets its ideal form.
      - Assets.car   full-bleed Liquid Glass, CFBundleIconName  -> macOS 26+.
      - AppIcon.icns ROUNDED + margin + shadow, CFBundleIconFile -> macOS < 26.

  * actool NOT available:  only a single full-bleed .icns (no rounding). macOS
      26 still masks it to a squircle (no gray jail); older macOS shows it with
      square corners. A compromise, but the best a lone .icns can do.

Usage:
    python appicon.py <master.png>                 # AppIcon.icns (+ Assets.car if possible)
    python appicon.py <master.png> -d build/icons  # into a chosen dir
    python appicon.py <master.png> --name MyIcon   # asset/file base name
    python appicon.py <master.png> --keep-icon     # also keep the .icon package

Requires: Pillow; macOS `iconutil` (for .icns). `xcrun actool` from Xcode 26+
is optional — without it, only the full-bleed .icns is produced.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

# --- Apple's macOS icon grid (legacy, rounded .icns) ------------------------
# For a 1024 canvas the rounded body is 824x824 (≈80.5%) with a corner radius
# of ~185 (≈0.2237 of the body). These ratios reproduce the classic look.
LEGACY_BODY_RATIO = 824.0 / 1024.0
LEGACY_CORNER_RATIO = 185.4 / 824.0
SUPERSAMPLE = 4  # supersampling factor for crisp, anti-aliased corners

# Standard macOS iconset matrix (1x and 2x for each base size).
ICONSET_SIZES = (16, 32, 128, 256, 512)
MASTER_SIZE = 1024  # 512@2x — the largest slot in the iconset / .icon layer


def _load_master(path):
    img = Image.open(path).convert("RGBA")
    if img.width != img.height:
        # center-crop to a square so the framing/grid math stays correct
        side = min(img.size)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side))
    return img


def _squircle_mask(size, radius):
    """Return an 'L' mask of a rounded square, anti-aliased via supersampling."""
    s = size * SUPERSAMPLE
    mask = Image.new("L", (s, s), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, s - 1, s - 1), radius=radius * SUPERSAMPLE, fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def _rounded_art(master, size):
    """Rounded artwork inset on the macOS grid with a soft drop shadow (legacy)."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    body = int(round(size * LEGACY_BODY_RATIO))
    art = master.resize((body, body), Image.LANCZOS)
    art.putalpha(_squircle_mask(body, body * LEGACY_CORNER_RATIO))

    offset = (size - body) // 2

    # soft drop shadow, slightly below the body
    sh_alpha = art.split()[3].point(lambda a: int(a * 0.30))
    sh_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    blk = Image.new("RGBA", (body, body), (0, 0, 0, 255))
    blk.putalpha(sh_alpha)
    sh_layer.paste(blk, (offset, offset + int(size * 0.012)))
    shadow = sh_layer.filter(ImageFilter.GaussianBlur(size * 0.018))

    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(art, (offset, offset), art)
    return canvas


def _icns_from_art(art1024, out_path):
    """Build an .icns from a 1024px master image via iconutil."""
    if shutil.which("iconutil") is None:
        sys.exit("iconutil not found — .icns generation requires macOS.")
    tmp = tempfile.mkdtemp()
    try:
        iconset = os.path.join(tmp, "AppIcon.iconset")
        os.makedirs(iconset)
        for s in ICONSET_SIZES:
            for scale, name in ((1, f"icon_{s}x{s}.png"), (2, f"icon_{s}x{s}@2x.png")):
                px = s * scale
                art1024.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out_path], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build_icns(master, out_path, rounded):
    """Build the .icns: `rounded` legacy look for macOS < 26, else full-bleed."""
    art = _rounded_art(master, MASTER_SIZE) if rounded \
        else master.resize((MASTER_SIZE, MASTER_SIZE), Image.LANCZOS)
    _icns_from_art(art, out_path)


def build_icon_package(master, pkg_dir):
    """Author a minimal Icon Composer .icon package from a full-bleed master.

    The master is used as a single opaque, full-bleed layer; actool/macOS 26
    apply the squircle mask and Liquid Glass materials on top. No official
    icon.json schema is published, but actool accepts this minimal form.
    """
    assets = os.path.join(pkg_dir, "Assets")
    os.makedirs(assets, exist_ok=True)
    master.convert("RGB").resize((MASTER_SIZE, MASTER_SIZE), Image.LANCZOS).save(
        os.path.join(assets, "icon.png"))
    manifest = {
        "fill": "automatic",
        "groups": [{"layers": [{"image-name": "icon.png", "name": "icon"}]}],
        "supported-platforms": {"circles": ["watchOS"], "squares": "shared"},
    }
    with open(os.path.join(pkg_dir, "icon.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)


def actool_available():
    if shutil.which("xcrun") is None:
        return False
    try:
        subprocess.run(["xcrun", "--find", "actool"], check=True,
                       capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError:
        return False


def build_assets_car(master, out_path, name="AppIcon", keep_icon_dir=None):
    """Compile a full-bleed master into an Assets.car for macOS 26 via actool."""
    tmp = tempfile.mkdtemp()
    try:
        pkg = os.path.join(keep_icon_dir or tmp, f"{name}.icon")
        build_icon_package(master, pkg)
        compile_dir = os.path.join(tmp, "out")
        os.makedirs(compile_dir)
        subprocess.run([
            "xcrun", "actool", pkg, "--compile", compile_dir,
            "--output-partial-info-plist", os.path.join(tmp, "partial.plist"),
            "--app-icon", name, "--include-all-app-icons",
            "--enable-on-demand-resources", "NO",
            "--development-region", "en",
            "--target-device", "mac",
            "--minimum-deployment-target", "26.0",
            "--platform", "macosx",
        ], check=True, capture_output=True, text=True)
        car = os.path.join(compile_dir, "Assets.car")
        if not os.path.isfile(car):
            return False
        shutil.copy2(car, out_path)
        return True
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"actool failed:\n{exc.stderr}\n")
        return False
    except Exception as exc:  # best-effort: an Assets.car failure must not kill the .icns
        sys.stderr.write(f"Assets.car generation failed: {exc}\n")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(
        description="Build the macOS app icon: full-bleed Assets.car (macOS 26) + rounded .icns (older), or a lone full-bleed .icns when actool is unavailable.")
    ap.add_argument("source", help="full-bleed square master image (PNG)")
    ap.add_argument("-d", "--out-dir", help="output directory (default: alongside source)")
    ap.add_argument("--name", default="AppIcon", help="asset / file base name (default: AppIcon)")
    ap.add_argument("--keep-icon", action="store_true",
                    help="also keep the generated <name>.icon package in the output dir")
    args = ap.parse_args()

    # Exit-code contract (callers rely on this):
    #   0  -> the .icns was produced. Assets.car is best-effort: present only when
    #         actool is available; its absence is NOT an error. Inspect the output
    #         files to know which were created.
    #   1  -> a real failure producing the required .icns (bad source, iconutil
    #         missing/failed). Diagnostics are written to stderr.
    if not os.path.isfile(args.source):
        sys.exit(f"error: source not found: {args.source}")
    try:
        master = _load_master(args.source)
    except Exception as exc:
        sys.exit(f"error: cannot read source image {args.source}: {exc}")

    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.source))
    os.makedirs(out_dir, exist_ok=True)
    icns_path = os.path.join(out_dir, f"{args.name}.icns")

    # macOS 26: full-bleed Liquid Glass via Assets.car (best-effort; needs actool).
    have_actool = actool_available()
    car_ok = False
    if have_actool:
        car_path = os.path.join(out_dir, "Assets.car")
        keep_dir = out_dir if args.keep_icon else None
        car_ok = build_assets_car(master, car_path, name=args.name, keep_icon_dir=keep_dir)
        if car_ok:
            print(f"wrote {car_path}  (macOS 26+ → CFBundleIconName={args.name})")
            if args.keep_icon:
                print(f"kept  {os.path.join(out_dir, args.name + '.icon')}")
        else:
            sys.stderr.write("warning: actool present but Assets.car generation failed (see above); .icns only.\n")

    # The .icns is REQUIRED. With Assets.car covering macOS 26, bake the rounded
    # legacy look old macOS expects; otherwise fall back to a lone full-bleed
    # .icns (macOS 26 masks it to a squircle; older macOS shows square corners).
    try:
        build_icns(master, icns_path, rounded=car_ok)
    except Exception as exc:
        sys.exit(f"error: failed to build {icns_path}: {exc}")
    kind = "rounded, macOS < 26" if car_ok else "full-bleed, no rounding"
    print(f"wrote {icns_path}  ({kind} → CFBundleIconFile={args.name})")

    if car_ok:
        print("\nInfo.plist keys to set:")
        print(f"  CFBundleIconName = {args.name}     # macOS 26+  (full-bleed asset in Assets.car)")
        print(f"  CFBundleIconFile = {args.name}     # macOS < 26 (rounded .icns)")
        print("Place both files in Contents/Resources, then (re-)sign the bundle.")
    elif not have_actool:
        sys.stderr.write(
            "note: `xcrun actool` (Xcode 26+) not found, so no Assets.car was built.\n"
            "      macOS 26 will mask the full-bleed .icns to a squircle (no Liquid\n"
            "      Glass layers); older macOS shows it with square corners.\n")


if __name__ == "__main__":
    main()
