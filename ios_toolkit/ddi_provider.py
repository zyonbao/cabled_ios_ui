"""ddi_provider.py — DeveloperDiskImage source resolution (acquisition tool).

This module is the "where do the image files come from" half of DDI support,
intentionally kept separate from device interaction (``device.py`` only mounts
already-resolved files). It owns:

  * the bundled offline version index (``ddi_image_index.json``),
  * iOS<17 target-version resolution ({major}.{minor} reduction + nearest-lower),
  * local image lookup (Xcode legacy folders / CoreDevice ``iOS_DDI.dmg``),
  * GitHub acquisition with raw-CDN-first and a token-authenticated library
    fallback (``developer_disk_image``).

``resolve_ddi_image`` walks the configured source priority and returns the first
source that yields a mountable file set (a ``ResolvedDDI``); the caller mounts it
and then calls ``ResolvedDDI.cleanup()`` to remove any temp extraction dir.

Note: resolution and mounting are decoupled, so a source that produces files but
then fails to mount is NOT retried against the next source (mount failures are
typically device-side: developer mode off, already mounted, ...). Cross-source
fallback still applies when a source produces no files.
"""

from __future__ import annotations

import json
import logging
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Static-analysis hint for Nuitka (never executed): the GitHub library is
# imported lazily inside the fallback paths, so list it here to guarantee it is
# bundled. Keep in sync with the lazy imports below.
if False:  # noqa: SIM223 - Nuitka static-include hint, not runtime code
    from developer_disk_image.repo import (  # noqa: F401
        DeveloperDiskImageRepository,
    )

# Bundled offline index describing which <17 developer-image versions exist
# upstream (doronz88/DeveloperDiskImage) plus the 17+ personalized image paths.
_DDI_INDEX_PATH = Path(__file__).resolve().parent / "ddi_image_index.json"
_DDI_RAW_BASE_DEFAULT = "https://raw.githubusercontent.com/doronz88/DeveloperDiskImage/main"
_ddi_index_cache: "Optional[dict]" = None
_ddi_index_loaded = False

# Built-in default source config, used when the caller does not pass overrides.
_DDI_DEFAULT_SOURCES = ("local", "github")
_DDI_MODERN_DEFAULT_DIR = "/Library/Developer/CoreDevice/CandidateDDIs"
_DDI_GITHUB_SAVE_DEFAULT_DIR = "~/Library/CablediOS/DDI"


@dataclass
class ResolvedDDI:
    """A mountable DDI file set resolved from one source.

    ``family`` selects the mounter and which fields are populated:
      * "personalized" (iOS 17+): image + build_manifest + trustcache
      * "developer"    (iOS <17): image + signature
    ``temp_dir`` (when set) is a temporary extraction dir the caller MUST remove
    via ``cleanup()`` once the files have been consumed (i.e. after mounting).
    """

    family: str
    source: str
    target: "Optional[str]"
    image: Path
    signature: "Optional[Path]" = None
    build_manifest: "Optional[Path]" = None
    trustcache: "Optional[Path]" = None
    temp_dir: "Optional[str]" = None

    def mount_kwargs(self) -> dict:
        """File kwargs for ``iOSDevice.ddi_mount`` (paths as strings)."""
        if self.family == "personalized":
            return {
                "image": str(self.image),
                "build_manifest": str(self.build_manifest),
                "trustcache": str(self.trustcache),
            }
        return {"image": str(self.image), "signature": str(self.signature)}

    def cleanup(self) -> None:
        """Remove the temp extraction dir, if any (idempotent, never raises)."""
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None


# ---------------------------------------------------------------------------
# Version / index helpers
# ---------------------------------------------------------------------------


def ddi_family(major: int) -> str:
    """iOS 17+ uses personalized images; earlier versions use developer ones."""
    return "personalized" if major >= 17 else "developer"


def parse_major_minor(version: str) -> "Optional[tuple[int, int]]":
    """Reduce a version string to (major, minor); None if unparseable.

    Tolerates trailing build/arch suffixes such as '16.4 (20E247)' or
    '16.4.1 (20E252) arm64e' by reading the leading numeric tokens.
    """
    m = re.match(r"\s*(\d+)(?:\.(\d+))?", version or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def _load_ddi_index() -> "Optional[dict]":
    """Load and cache the bundled DDI version index (None if missing/corrupt)."""
    global _ddi_index_cache, _ddi_index_loaded
    if _ddi_index_loaded:
        return _ddi_index_cache
    _ddi_index_loaded = True
    try:
        _ddi_index_cache = json.loads(_DDI_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # missing / unreadable / malformed → degrade
        logger.warning("ddi index unavailable (%s): %s", _DDI_INDEX_PATH, exc)
        _ddi_index_cache = None
    return _ddi_index_cache


def _nearest_lower_version(versions: "list[str]", major: int, minor: int) -> "Optional[str]":
    """Pick the canonical target among ``versions`` for device {major}.{minor}.

    Exact '{major}.{minor}' wins; otherwise the highest same-major version whose
    minor is <= the device minor (nearest-lower). None when no <= candidate.
    """
    exact = f"{major}.{minor}"
    best: "Optional[tuple[int, str]]" = None
    for ver in versions:
        mm = parse_major_minor(ver)
        if mm is None or mm[0] != major:
            continue
        if ver == exact:
            return exact
        if mm[1] <= minor and (best is None or mm[1] > best[0]):
            best = (mm[1], f"{major}.{mm[1]}")
    return best[1] if best else None


def resolve_target_from_index(major: int, minor: int) -> "Optional[str]":
    """Offline-resolve the <17 target version from the bundled index (or None)."""
    index = _load_ddi_index()
    if not index:
        return None
    versions = index.get("developer_image_versions") or []
    return _nearest_lower_version(versions, major, minor)


# ---------------------------------------------------------------------------
# Default-path helpers
# ---------------------------------------------------------------------------


def _xcode_developer_dir() -> "Optional[str]":
    """Active Xcode Developer dir via ``xcode-select -p`` (None if unavailable)."""
    try:
        out = subprocess.run(
            ["xcode-select", "-p"], check=True, capture_output=True, text=True
        )
        path = out.stdout.strip()
        return path or None
    except Exception:
        return None


def ddi_legacy_default_dir() -> "Optional[str]":
    """Standard Xcode DeviceSupport folder holding per-version (<17) images."""
    dev = _xcode_developer_dir()
    if not dev:
        return None
    return os.path.join(dev, "Platforms/iPhoneOS.platform/DeviceSupport")


# ---------------------------------------------------------------------------
# Local source helpers
# ---------------------------------------------------------------------------


def _find_local_developer_image(legacy_dir: str, target: str) -> "Optional[tuple[Path, Path]]":
    """Locate <17 ``DeveloperDiskImage.dmg`` + ``.signature`` for ``target``.

    Subdirectory names are reduced to '{major}.{minor}' before comparing, so
    Xcode's build/arch-suffixed folders (e.g. '16.4 (20E247)') still match the
    bare ``target`` ('16.4'). No nearest-lower here: target was already resolved.
    """
    base = Path(os.path.expanduser(legacy_dir or ""))
    if not base.is_dir():
        return None
    target_mm = parse_major_minor(target)
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if parse_major_minor(child.name) != target_mm:
            continue
        image = child / "DeveloperDiskImage.dmg"
        signature = child / "DeveloperDiskImage.dmg.signature"
        if image.is_file() and signature.is_file():
            return image, signature
    return None


def _find_ios_ddi_dmg(modern_dir: str) -> "Optional[Path]":
    """Locate the universal ``iOS_DDI.dmg`` (CoreDevice CandidateDDIs) if present."""
    base = Path(os.path.expanduser(modern_dir or ""))
    candidate = base / "iOS_DDI.dmg"
    if candidate.is_file():
        return candidate
    if base.is_dir():
        for found in sorted(base.glob("*.dmg")):
            if found.name == "iOS_DDI.dmg":
                return found
    return None


def _hdiutil_attach(dmg: Path) -> str:
    """Attach a dmg read-only (no Finder) and return its mount point."""
    out = subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", "-plist", str(dmg)],
        check=True, capture_output=True,
    )
    info = plistlib.loads(out.stdout)
    for entity in info.get("system-entities", []):
        mp = entity.get("mount-point")
        if mp:
            return mp
    raise RuntimeError("hdiutil attach produced no mount point")


def _hdiutil_detach(mount_point: str) -> None:
    """Best-effort detach; failures are logged, never raised."""
    try:
        subprocess.run(["hdiutil", "detach", mount_point], check=True, capture_output=True)
    except Exception as exc:
        logger.debug("hdiutil detach failed (%s): %s", mount_point, exc)


def _select_personalized_from_manifest(manifest: Path) -> "tuple[Path, Path]":
    """Resolve the (image, trustcache) pair from a ``BuildManifest.plist``.

    Apple's CoreDevice ``iOS_DDI.dmg`` is a Restore bundle whose images are named
    by build component (e.g. ``022-20692-058.dmg``), not ``Image.dmg``. Each
    ``BuildIdentities`` entry maps ``PersonalizedDMG`` → the DDI image and
    ``LoadableTrustCache`` → its trustcache (paths relative to the manifest dir).
    These are identical across every device identity in a given DDI build, so the
    first identity carrying both is authoritative; the device-specific TSS
    signing is handled later by ``PersonalizedImageMounter`` using this manifest.
    """
    base = manifest.parent
    data = plistlib.loads(manifest.read_bytes())
    for identity in data.get("BuildIdentities", []) or []:
        man = identity.get("Manifest", {}) or {}
        dmg_rel = ((man.get("PersonalizedDMG") or {}).get("Info") or {}).get("Path")
        tc_rel = ((man.get("LoadableTrustCache") or {}).get("Info") or {}).get("Path")
        if dmg_rel and tc_rel:
            image, trustcache = base / dmg_rel, base / tc_rel
            if image.is_file() and trustcache.is_file():
                return image, trustcache
    raise RuntimeError(
        "BuildManifest.plist 未提供可用的 PersonalizedDMG / LoadableTrustCache 组件"
    )


def _extract_personalized_from_dmg(dmg: Path) -> "tuple[Path, Path, Path, str]":
    """Extract the personalized triplet from ``iOS_DDI.dmg`` into a temp dir.

    Attaches the dmg, locates the image / build_manifest / trustcache, copies them
    out to a temporary directory, then always detaches. Supports two layouts:
      * Apple CoreDevice Restore bundle — image+trustcache selected from
        ``BuildManifest.plist`` (``PersonalizedDMG`` / ``LoadableTrustCache``).
      * doronz88 flat layout — ``Image.dmg`` / ``Image.dmg.trustcache``.
    Returns the three copied paths plus the temp dir (caller MUST remove it).
    """
    mount_point = _hdiutil_attach(dmg)
    try:
        root = Path(mount_point)
        build_manifest = next(iter(root.rglob("BuildManifest.plist")), None)
        if not build_manifest:
            raise RuntimeError(f"iOS_DDI.dmg 内未找到 BuildManifest.plist（{mount_point}）")
        # Prefer the manifest-declared component paths (CoreDevice Restore bundle);
        # fall back to the flat Image.dmg layout used by the raw download.
        try:
            image, trustcache = _select_personalized_from_manifest(build_manifest)
        except Exception as exc:
            logger.debug("manifest-based selection failed (%s); trying flat layout", exc)
            image = next(iter(root.rglob("Image.dmg")), None)
            trustcache = next(iter(root.rglob("*.trustcache")), None)
            if not image or not trustcache:
                raise RuntimeError(
                    f"iOS_DDI.dmg 缺少可挂载的镜像/trustcache（{mount_point}）"
                ) from exc
        tmp = Path(tempfile.mkdtemp(prefix="cabledios-ddi-"))
        out_image = tmp / "Image.dmg"
        out_manifest = tmp / "BuildManifest.plist"
        out_trustcache = tmp / "Image.dmg.trustcache"
        shutil.copy2(image, out_image)
        shutil.copy2(build_manifest, out_manifest)
        shutil.copy2(trustcache, out_trustcache)
        logger.info(
            "extracted personalized triplet (image=%s, trustcache=%s)",
            image.name, trustcache.name,
        )
        return out_image, out_manifest, out_trustcache, str(tmp)
    finally:
        _hdiutil_detach(mount_point)


# ---------------------------------------------------------------------------
# GitHub source helpers (raw CDN primary, library fallback)
# ---------------------------------------------------------------------------


def _http_get_bytes(url: str) -> bytes:
    """GET a raw asset; raise on non-200 or empty body."""
    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"raw download failed: HTTP {resp.status_code} ({url})")
    content = resp.content
    if not content:
        raise RuntimeError(f"raw download returned empty body ({url})")
    return content


def _resolve_github_developer_image(
    target: "Optional[str]", major: int, minor: int, save_dir: str, token: "Optional[str]"
) -> "Optional[tuple[Path, Path]]":
    """Resolve a <17 developer image from cache → raw CDN → library fallback.

    ``target`` is the index-resolved version (may be None when the device is
    below the bundled index or the index is stale). On raw failure or a None
    target, the ``developer_disk_image`` library pulls the live tree, recomputes
    the nearest-lower target (which may be newer than the bundled index) and
    downloads via the (token-authenticated) blob API.
    """
    base = Path(os.path.expanduser(save_dir or ""))

    def _cached(ver: str) -> "Optional[tuple[Path, Path]]":
        image = base / ver / "DeveloperDiskImage.dmg"
        signature = base / ver / "DeveloperDiskImage.dmg.signature"
        return (image, signature) if image.is_file() and signature.is_file() else None

    def _save(ver: str, image_bytes: bytes, sig_bytes: bytes) -> "tuple[Path, Path]":
        dest = base / ver
        dest.mkdir(parents=True, exist_ok=True)
        image = dest / "DeveloperDiskImage.dmg"
        signature = dest / "DeveloperDiskImage.dmg.signature"
        image.write_bytes(image_bytes)
        signature.write_bytes(sig_bytes)
        return image, signature

    index = _load_ddi_index()
    raw_base = (index or {}).get("raw_base") or _DDI_RAW_BASE_DEFAULT

    # Primary: index target via cache then raw CDN (no api.github.com, no token).
    if target:
        hit = _cached(target)
        if hit:
            logger.info("ddi github: cache hit (developer %s)", target)
            return hit
        try:
            image_bytes = _http_get_bytes(
                f"{raw_base}/DeveloperDiskImages/{target}/DeveloperDiskImage.dmg"
            )
            sig_bytes = _http_get_bytes(
                f"{raw_base}/DeveloperDiskImages/{target}/DeveloperDiskImage.dmg.signature"
            )
            logger.info("ddi github: raw downloaded developer %s", target)
            return _save(target, image_bytes, sig_bytes)
        except Exception as exc:
            logger.warning("ddi github: raw developer %s failed: %s", target, exc)

    # Fallback: live tree (token) → recompute nearest-lower → blob download.
    try:
        from developer_disk_image.repo import DeveloperDiskImageRepository

        logger.info("ddi github: falling back to live tree (token=%s)", bool(token))
        repo = DeveloperDiskImageRepository.create(github_token=token or None)
        live_versions = [
            p.split("/")[1]
            for p in repo._path_urls
            if p.startswith("DeveloperDiskImages/") and p.endswith("/DeveloperDiskImage.dmg")
        ]
        target2 = _nearest_lower_version(live_versions, major, minor)
        if not target2:
            logger.warning("ddi github: live tree has no <= candidate for %s.%s", major, minor)
            return None
        cached = _cached(target2)
        if cached:
            return cached
        ddi = repo.get_developer_disk_image(target2)
        if ddi is None or ddi.image is None:
            return None
        logger.info("ddi github: library downloaded developer %s", target2)
        return _save(target2, ddi.image, ddi.signature)
    except Exception as exc:
        logger.warning("ddi github: developer library fallback failed: %s", exc, exc_info=True)
        return None


def _resolve_github_personalized_image(
    save_dir: str, token: "Optional[str]"
) -> "Optional[tuple[Path, Path, Path]]":
    """Resolve the 17+ personalized triplet from cache → raw CDN → library."""
    base = Path(os.path.expanduser(save_dir or ""))
    image = base / "Image.dmg"
    build_manifest = base / "BuildManifest.plist"
    trustcache = base / "Image.dmg.trustcache"
    if image.is_file() and build_manifest.is_file() and trustcache.is_file():
        logger.info("ddi github: cache hit (personalized)")
        return image, build_manifest, trustcache

    index = _load_ddi_index()
    raw_base = (index or {}).get("raw_base") or _DDI_RAW_BASE_DEFAULT
    rel = "PersonalizedImages/Xcode_iOS_DDI_Personalized"
    base.mkdir(parents=True, exist_ok=True)
    try:
        image.write_bytes(_http_get_bytes(f"{raw_base}/{rel}/Image.dmg"))
        build_manifest.write_bytes(_http_get_bytes(f"{raw_base}/{rel}/BuildManifest.plist"))
        trustcache.write_bytes(_http_get_bytes(f"{raw_base}/{rel}/Image.dmg.trustcache"))
        logger.info("ddi github: raw downloaded personalized triplet")
        return image, build_manifest, trustcache
    except Exception as exc:
        logger.warning("ddi github: raw personalized failed: %s", exc)

    try:
        from developer_disk_image.repo import DeveloperDiskImageRepository

        logger.info("ddi github: personalized library fallback (token=%s)", bool(token))
        repo = DeveloperDiskImageRepository.create(github_token=token or None)
        personalized = repo.get_personalized_disk_image()
        image.write_bytes(personalized.image)
        build_manifest.write_bytes(personalized.build_manifest)
        trustcache.write_bytes(personalized.trustcache)
        return image, build_manifest, trustcache
    except Exception as exc:
        logger.warning("ddi github: personalized library fallback failed: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Public orchestration
# ---------------------------------------------------------------------------


def resolve_ddi_image(
    major: int,
    minor: int,
    *,
    sources: "Optional[list[str]]" = None,
    legacy_dir: "Optional[str]" = None,
    modern_dir: "Optional[str]" = None,
    github_token: "Optional[str]" = None,
    github_save_dir: "Optional[str]" = None,
) -> "Optional[ResolvedDDI]":
    """Resolve a mountable DDI for device {major}.{minor}, honoring source priority.

    Dispatches by major version, resolves a single <17 target from the bundled
    index (shared by local and download; may be None → local skipped, download
    falls back to the live tree), then returns the first source that yields a
    file set. None when no source produces an image. ``github_token`` is never
    logged in clear (only a bool).
    """
    family = ddi_family(major)
    src_list = list(sources) if sources else list(_DDI_DEFAULT_SOURCES)
    eff_legacy = legacy_dir or ddi_legacy_default_dir() or ""
    eff_modern = modern_dir or _DDI_MODERN_DEFAULT_DIR
    eff_save = github_save_dir or _DDI_GITHUB_SAVE_DEFAULT_DIR
    target = resolve_target_from_index(major, minor) if family == "developer" else None
    logger.info(
        "resolve_ddi_image: family=%s target=%s sources=%s has_token=%s",
        family, target, src_list, bool(github_token),
    )

    for source in src_list:
        try:
            if source == "local":
                if family == "personalized":
                    dmg = _find_ios_ddi_dmg(eff_modern)
                    if dmg:
                        img, bm, tc, tmp = _extract_personalized_from_dmg(dmg)
                        logger.info("resolve_ddi_image: local iOS_DDI.dmg %s", dmg)
                        return ResolvedDDI(
                            family, source, target, img,
                            build_manifest=bm, trustcache=tc, temp_dir=tmp,
                        )
                elif target:
                    found = _find_local_developer_image(eff_legacy, target)
                    if found:
                        logger.info("resolve_ddi_image: local developer %s", found[0])
                        return ResolvedDDI(family, source, target, found[0], signature=found[1])
            elif source == "github":
                if family == "personalized":
                    found = _resolve_github_personalized_image(eff_save, github_token)
                    if found:
                        return ResolvedDDI(
                            family, source, target, found[0],
                            build_manifest=found[1], trustcache=found[2],
                        )
                else:
                    found = _resolve_github_developer_image(
                        target, major, minor, eff_save, github_token
                    )
                    if found:
                        return ResolvedDDI(family, source, target, found[0], signature=found[1])
            else:
                logger.debug("resolve_ddi_image: unknown source %r, skipping", source)
                continue
            logger.info("resolve_ddi_image: source %s produced no image", source)
        except Exception as exc:  # try the next source
            logger.warning(
                "resolve_ddi_image: source %s failed: %s", source, exc, exc_info=True
            )
    logger.info("resolve_ddi_image: no source produced an image (family=%s)", family)
    return None
