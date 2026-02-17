"""
ThrowSync — Self-Updater
Checks for updates, downloads, stages, and triggers server restart.

Update flow:
  1. Check manifest URL for latest version
  2. Download ZIP to temp
  3. Extract to _update_staging/
  4. On restart trigger: run.py loop swaps staging → live and restarts
"""

MODULE_VERSION = "1.3.2"

import asyncio
import json
import logging
import os
import platform
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

logger = logging.getLogger("updater")

# ─── Paths ───────────────────────────────────────────────────────────────────
try:
    from paths import BUNDLE_DIR, DATA_DIR, VERSION_FILE as _PATHS_VERSION
    PROJECT_ROOT = BUNDLE_DIR
    VERSION_FILE = _PATHS_VERSION
except ImportError:
    PROJECT_ROOT = Path(__file__).parent.parent.resolve()
    VERSION_FILE = PROJECT_ROOT / "VERSION"

STAGING_DIR = PROJECT_ROOT / "_update_staging"
BACKUP_DIR = PROJECT_ROOT / "_update_backup"
RESTART_FLAG = PROJECT_ROOT / ".restart"
UPDATE_LOCK = PROJECT_ROOT / ".updating"

# Default manifest URL — override in config
DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/AnglJack87/throwsync/main/update-manifest.json"

# Files/dirs to NEVER overwrite during update (user data)
PRESERVE_PATHS = {
    "backend/config.json",
    "backend/sounds",
    "backend/config.json.bak",
}

# Files/dirs to NEVER delete during update
KEEP_PATHS = {
    "_update_staging",
    "_update_backup",
    ".restart",
    ".updating",
    "venv",
    "__pycache__",
    "backend/__pycache__",
    "backend/config.json",
    "backend/config.json.bak",
    "backend/sounds",
}


def get_local_version() -> str:
    """Read current installed version."""
    try:
        ver = VERSION_FILE.read_text().strip()
        logger.debug(f"Version from {VERSION_FILE}: {ver}")
        return ver
    except Exception as e:
        logger.warning(f"Could not read VERSION from {VERSION_FILE}: {e}")
        return "0.0.0"


def parse_version(v: str) -> tuple:
    """Parse semver string to comparable tuple."""
    try:
        parts = v.strip().lstrip("v").split(".")
        return tuple(int(x) for x in parts[:3])
    except (ValueError, IndexError):
        return (0, 0, 0)


def is_newer(remote: str, local: str) -> bool:
    """Check if remote version is newer than local."""
    return parse_version(remote) > parse_version(local)


async def check_for_update(manifest_url: str = None) -> dict:
    """
    Check the update manifest for a newer version.
    Returns: {available, local_version, remote_version, download_url, changelog, size}
    """
    url = manifest_url or DEFAULT_MANIFEST_URL
    local_ver = get_local_version()
    result = {
        "available": False,
        "local_version": local_ver,
        "remote_version": None,
        "download_url": None,
        "changelog": "",
        "size": 0,
        "manifest_url": url,
        "error": None,
    }

    try:
        manifest = None
        
        # Try aiohttp first
        if HAS_AIOHTTP:
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            manifest = await resp.json(content_type=None)
                        else:
                            logger.warning(f"aiohttp manifest check HTTP {resp.status}, trying urllib fallback")
            except Exception as e:
                logger.warning(f"aiohttp manifest check failed: {e}, trying urllib fallback")
        
        # Fallback to urllib (works better on some Linux systems)
        if manifest is None:
            manifest = await asyncio.get_event_loop().run_in_executor(None, _urllib_get_json, url)
    
    except asyncio.TimeoutError:
        result["error"] = "Timeout beim Abrufen des Manifests"
        return result
    except Exception as e:
        result["error"] = f"Manifest-Fehler: {str(e)}"
        return result

    if manifest is None:
        result["error"] = "Manifest konnte nicht geladen werden"
        return result

    remote_ver = manifest.get("version", "0.0.0")
    result["remote_version"] = remote_ver
    result["download_url"] = manifest.get("download_url", "")
    result["changelog"] = manifest.get("changelog", "")
    result["size"] = manifest.get("size", 0)
    result["min_python"] = manifest.get("min_python", "3.8")
    result["available"] = is_newer(remote_ver, local_ver)

    return result


def _urllib_get_json(url: str) -> dict:
    """Fetch JSON via urllib (synchronous fallback for manifest check)."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except (ImportError, Exception):
        pass  # Use system certs
    req = urllib.request.Request(url, headers={"User-Agent": "ThrowSync-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        return json.loads(resp.read().decode())


def _urllib_download(url: str, dest_path: str, progress_callback=None) -> int:
    """Download file via urllib (synchronous fallback). Returns bytes downloaded."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except (ImportError, Exception):
        pass
    req = urllib.request.Request(url, headers={"User-Agent": "ThrowSync-Updater/1.0"})
    downloaded = 0
    with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total > 0:
                    pct = int(downloaded / total * 100)
                    progress_callback(pct, downloaded, total)
    return downloaded


async def download_and_stage(download_url: str, progress_callback=None) -> dict:
    """
    Download update ZIP and extract to staging directory.
    Returns: {success, message, staged_version}
    """
    if UPDATE_LOCK.exists():
        return {"success": False, "message": "Update läuft bereits"}

    # Create lock
    UPDATE_LOCK.write_text(str(os.getpid()))

    try:
        # Clean old staging
        if STAGING_DIR.exists():
            shutil.rmtree(STAGING_DIR)
        STAGING_DIR.mkdir(parents=True)

        # Download ZIP
        logger.info(f"Downloading update from {download_url}")
        tmp_zip = STAGING_DIR / "update.zip"
        downloaded = 0

        # Try aiohttp first (async with progress)
        aio_success = False
        if HAS_AIOHTTP:
            try:
                timeout = aiohttp.ClientTimeout(total=300)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(download_url) as resp:
                        if resp.status == 200:
                            total = int(resp.headers.get("Content-Length", 0))
                            with open(tmp_zip, "wb") as f:
                                async for chunk in resp.content.iter_chunked(65536):
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if progress_callback and total > 0:
                                        pct = int(downloaded / total * 100)
                                        await progress_callback(pct, downloaded, total)
                            aio_success = True
                        else:
                            logger.warning(f"aiohttp download HTTP {resp.status}, trying urllib fallback")
            except Exception as e:
                logger.warning(f"aiohttp download failed: {e}, trying urllib fallback")

        # Fallback to urllib (handles GitHub redirects better on some Linux)
        if not aio_success:
            try:
                logger.info("Using urllib fallback for download...")
                def sync_progress(pct, dl, tot):
                    # Can't await in sync callback, skip WS progress
                    pass
                downloaded = await asyncio.get_event_loop().run_in_executor(
                    None, _urllib_download, download_url, str(tmp_zip), sync_progress
                )
                if progress_callback:
                    await progress_callback(100, downloaded, downloaded)
            except Exception as e:
                return {"success": False, "message": f"Download fehlgeschlagen: {str(e)}"}

        logger.info(f"Downloaded {downloaded} bytes")

        # Verify ZIP
        if not zipfile.is_zipfile(tmp_zip):
            return {"success": False, "message": "Heruntergeladene Datei ist kein gültiges ZIP"}

        # Extract ZIP
        extract_dir = STAGING_DIR / "extracted"
        extract_dir.mkdir()

        with zipfile.ZipFile(tmp_zip) as zf:
            zf.extractall(extract_dir)

        # Find the actual project root inside ZIP
        # ZIP might contain a top-level directory like "throwsync-1.2.0/"
        entries = list(extract_dir.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            # Single top-level dir — use its contents
            inner = entries[0]
        else:
            inner = extract_dir

        # Move extracted files to staging root
        staged = STAGING_DIR / "files"
        if inner != extract_dir:
            shutil.move(str(inner), str(staged))
        else:
            staged.mkdir()
            for item in extract_dir.iterdir():
                if item.name != "extracted":
                    shutil.move(str(item), str(staged / item.name))

        # Read staged version
        staged_version_file = staged / "VERSION"
        staged_ver = "unknown"
        if staged_version_file.exists():
            staged_ver = staged_version_file.read_text().strip()

        # Cleanup
        tmp_zip.unlink(missing_ok=True)
        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)

        logger.info(f"Update staged: v{staged_ver} in {staged}")
        return {
            "success": True,
            "message": f"Update v{staged_ver} bereit zur Installation",
            "staged_version": staged_ver,
        }

    except Exception as e:
        logger.error(f"Update download/staging failed: {e}")
        return {"success": False, "message": f"Fehler: {str(e)}"}
    finally:
        UPDATE_LOCK.unlink(missing_ok=True)


def apply_staged_update() -> dict:
    """
    Apply a staged update by swapping files.
    Called by run.py BEFORE restarting the server.
    Returns: {success, message}
    """
    staged = STAGING_DIR / "files"
    if not staged.exists() or not staged.is_dir():
        return {"success": False, "message": "Kein staged Update gefunden"}

    try:
        # Create backup of current installation
        if BACKUP_DIR.exists():
            shutil.rmtree(BACKUP_DIR)
        BACKUP_DIR.mkdir(parents=True)

        # Backup current files (excluding preserved/special dirs)
        for item in PROJECT_ROOT.iterdir():
            rel = item.name
            if rel in KEEP_PATHS or rel.startswith(".") or rel.startswith("_"):
                continue
            dest = BACKUP_DIR / rel
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        logger.info(f"Backup created in {BACKUP_DIR}")

        # Copy staged files over current installation
        for item in staged.iterdir():
            rel = item.name
            dest = PROJECT_ROOT / rel

            # Check preserve list
            skip = False
            if item.is_dir():
                for preserve in PRESERVE_PATHS:
                    if preserve.startswith(rel + "/") or preserve == rel:
                        # Merge directory — copy new files but don't delete existing preserved ones
                        if dest.exists() and dest.is_dir():
                            _merge_dir(item, dest, PRESERVE_PATHS, rel)
                            skip = True
                            break
            elif str(rel) in PRESERVE_PATHS:
                skip = True

            if skip:
                continue

            # Remove existing and replace
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()

            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        logger.info("Staged files applied successfully")

        # Cleanup staging
        shutil.rmtree(STAGING_DIR, ignore_errors=True)

        return {"success": True, "message": "Update erfolgreich installiert"}

    except Exception as e:
        logger.error(f"Failed to apply update: {e}")
        # Try rollback
        try:
            rollback_update()
        except Exception as rb_err:
            logger.error(f"Rollback also failed: {rb_err}")
        return {"success": False, "message": f"Update fehlgeschlagen: {str(e)}"}


def _merge_dir(src: Path, dest: Path, preserve: set, prefix: str):
    """Merge source dir into destination, preserving specified paths."""
    for item in src.iterdir():
        rel_path = f"{prefix}/{item.name}"
        dest_item = dest / item.name

        if rel_path in preserve:
            continue  # Don't touch preserved files

        if item.is_dir():
            if dest_item.exists():
                _merge_dir(item, dest_item, preserve, rel_path)
            else:
                shutil.copytree(item, dest_item)
        else:
            shutil.copy2(item, dest_item)


def rollback_update() -> dict:
    """Restore from backup after failed update."""
    if not BACKUP_DIR.exists():
        return {"success": False, "message": "Kein Backup vorhanden"}

    try:
        for item in BACKUP_DIR.iterdir():
            dest = PROJECT_ROOT / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        logger.info("Rollback completed")
        return {"success": True, "message": "Rollback erfolgreich"}
    except Exception as e:
        return {"success": False, "message": f"Rollback fehlgeschlagen: {str(e)}"}


def trigger_restart():
    """Write restart flag so run.py loop picks it up."""
    RESTART_FLAG.write_text("update")
    logger.info("Restart flag written — server will restart")


def get_update_status() -> dict:
    """Get current update system status."""
    staged = STAGING_DIR / "files"
    staged_ver = None
    if staged.exists():
        vf = staged / "VERSION"
        if vf.exists():
            staged_ver = vf.read_text().strip()

    return {
        "local_version": get_local_version(),
        "update_staged": staged.exists(),
        "staged_version": staged_ver,
        "updating": UPDATE_LOCK.exists(),
        "restart_pending": RESTART_FLAG.exists(),
        "backup_available": BACKUP_DIR.exists(),
        "platform": platform.system(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }


def cleanup():
    """Remove staging, backup and lock files."""
    for p in [STAGING_DIR, UPDATE_LOCK]:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)
