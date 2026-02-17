"""
ThrowSync — Path Resolution
Handles paths for both PyInstaller binary and normal Python execution.

PyInstaller bundles read-only files into sys._MEIPASS (temp dir).
User data (config, sounds, firmware) lives next to the executable.
"""
MODULE_VERSION = "1.0.0"

import sys
from pathlib import Path

# ── Detect execution mode ──
FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    # Running as PyInstaller binary
    BUNDLE_DIR = Path(sys._MEIPASS)           # Bundled read-only files
    DATA_DIR = Path(sys.executable).parent    # Writable dir next to binary
else:
    # Running as Python script (dev mode)
    BUNDLE_DIR = Path(__file__).parent.parent  # project root (throwsync/)
    DATA_DIR = Path(__file__).parent           # backend/ dir (where config.json lives)

# ── Read-only paths (bundled) ──
FRONTEND_DIR = BUNDLE_DIR / "frontend"
FRONTEND_HTML = FRONTEND_DIR / "index.html"
VERSION_FILE = BUNDLE_DIR / "VERSION"

# ── Writable paths (user data) ──
CONFIG_FILE = DATA_DIR / "config.json"
SOUNDS_DIR = DATA_DIR / "sounds"
CLIPS_DIR = DATA_DIR / "clips"
FIRMWARE_DIR = DATA_DIR / "firmware"

# Ensure writable dirs exist
SOUNDS_DIR.mkdir(exist_ok=True)
CLIPS_DIR.mkdir(exist_ok=True)
FIRMWARE_DIR.mkdir(exist_ok=True)


def get_version() -> str:
    """Read version from bundled VERSION file."""
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return "?.?.?"
