#!/usr/bin/env python3
"""gen_ddi_index.py — regenerate the bundled DDI image index.

Fetches the doronz88/DeveloperDiskImage repository file tree once (via the
GitHub git-trees API) and writes a static JSON index of the available images
to ``ios_toolkit/ddi_image_index.json``. The runtime (``device.py``) consumes
this bundled index to decide—offline, without any GitHub API call—whether a
needed iOS<17 developer image version exists and to perform nearest-lower
matching, then downloads the chosen file directly from the raw CDN.

This is a build/dev-time tool, not shipped logic. Run it to refresh the index
when new OS versions are published upstream:

    GITHUB_TOKEN=... .venv/bin/python ios_toolkit/tools/gen_ddi_index.py

A token is optional (raises the anonymous 60/hour limit) and is only used for
this one tree query; it is never stored in the output.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = "doronz88/DeveloperDiskImage"
REF = "main"
TREE_URL = f"https://api.github.com/repos/{REPO}/git/trees/{REF}?recursive=true"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{REF}"
OUTPUT = Path(__file__).resolve().parent.parent / "ddi_image_index.json"

_DEV_DIR = "DeveloperDiskImages"
_PERSONALIZED_DIR = "PersonalizedImages/Xcode_iOS_DDI_Personalized"


def _paths_via_api(token: str | None) -> list[str]:
    headers = {
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github+json",
        "User-Agent": "cabledios-gen-ddi-index",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(TREE_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if data.get("truncated"):
        raise RuntimeError("GitHub tree response was truncated; cannot build a complete index")
    return [n["path"] for n in data["tree"] if n.get("type") == "blob"]


def _paths_via_git() -> list[str]:
    """List repo paths without the GitHub API and without downloading blobs.

    A partial (blob:none) bare clone fetches only the commit + tree objects, so
    ``git ls-tree`` can enumerate every path while the large .dmg blobs are
    never transferred. This avoids the api.github.com rate limit entirely.
    """
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1",
             f"https://github.com/{REPO}.git", tmp],
            check=True, capture_output=True, text=True,
        )
        out = subprocess.run(
            ["git", "-C", tmp, "ls-tree", "-r", "--name-only", "HEAD"],
            check=True, capture_output=True, text=True,
        )
    return [line for line in out.stdout.splitlines() if line]


def _list_paths(token: str | None) -> list[str]:
    try:
        return _paths_via_api(token)
    except Exception as exc:  # noqa: BLE001 — fall back to git on any API failure
        print(f"GitHub API unavailable ({exc}); falling back to git partial clone…",
              file=sys.stderr)
        return _paths_via_git()


def _version_key(ver: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in ver.split("."))
    except ValueError:
        return (0,)


def build_index(token: str | None) -> dict:
    paths = _list_paths(token)

    # iOS<17 developer images: DeveloperDiskImages/<version>/DeveloperDiskImage.dmg(.signature)
    dev: dict[str, dict] = {}
    for p in paths:
        parts = p.split("/")
        if len(parts) == 3 and parts[0] == _DEV_DIR:
            ver, fname = parts[1], parts[2]
            if fname == "DeveloperDiskImage.dmg":
                dev.setdefault(ver, {})["dmg"] = p
            elif fname == "DeveloperDiskImage.dmg.signature":
                dev.setdefault(ver, {})["signature"] = p
    # Keep only versions that have both the image and its signature.
    dev = {v: f for v, f in dev.items() if "dmg" in f and "signature" in f}
    dev = dict(sorted(dev.items(), key=lambda kv: _version_key(kv[0])))

    # iOS17+ universal personalized image (version-less).
    personalized = {
        "image": f"{_PERSONALIZED_DIR}/Image.dmg",
        "build_manifest": f"{_PERSONALIZED_DIR}/BuildManifest.plist",
        "trustcache": f"{_PERSONALIZED_DIR}/Image.dmg.trustcache",
    }
    have_personalized = all(rel in paths for rel in personalized.values())

    return {
        "source": f"https://github.com/{REPO}",
        "ref": REF,
        "raw_base": RAW_BASE,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "developer_image_versions": list(dev.keys()),
        "developer_images": dev,
        "personalized_image": personalized if have_personalized else None,
    }


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or None
    index = build_index(token)
    OUTPUT.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(index['developer_image_versions'])} developer versions, "
          f"personalized={'yes' if index['personalized_image'] else 'no'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
