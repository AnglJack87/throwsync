#!/usr/bin/env python3
"""
ThrowSync — Build Script
Creates a standalone binary using PyInstaller.

Usage:
    python build.py              # Build for current platform
    python build.py --clean      # Clean + rebuild

Output:
    dist/throwsync               # Linux/Mac binary
    dist/throwsync.exe           # Windows binary

Requirements:
    pip install pyinstaller
"""

import os
import sys
import shutil
import platform
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"

# Platform detection
SYSTEM = platform.system().lower()  # linux, darwin, windows
ARCH = platform.machine().lower()   # x86_64, aarch64, arm64

PLATFORM_NAMES = {
    ("linux", "x86_64"): "linux-x64",
    ("linux", "aarch64"): "linux-arm64",
    ("darwin", "x86_64"): "macos-x64",
    ("darwin", "arm64"): "macos-arm64",
    ("windows", "amd64"): "win-x64",
    ("windows", "x86_64"): "win-x64",
}

PLATFORM_TAG = PLATFORM_NAMES.get((SYSTEM, ARCH), f"{SYSTEM}-{ARCH}")


def check_pyinstaller():
    try:
        import PyInstaller
        print(f"  PyInstaller {PyInstaller.__version__}")
        return True
    except ImportError:
        print("  PyInstaller nicht installiert!")
        print("  → pip install pyinstaller")
        return False


def clean():
    """Remove previous build artifacts."""
    for d in [BUILD_DIR, DIST_DIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  Entfernt: {d}")
    spec = PROJECT_ROOT / "throwsync.spec"
    if spec.exists():
        spec.unlink()


def build():
    """Build the binary with PyInstaller."""
    import PyInstaller.__main__

    # Separator for --add-data (: on Linux/Mac, ; on Windows)
    sep = ";" if SYSTEM == "windows" else ":"

    # Version
    version = (PROJECT_ROOT / "VERSION").read_text().strip()
    print(f"  Version: {version}")
    print(f"  Platform: {PLATFORM_TAG}")
    print(f"  Python: {sys.version}")

    # Entry point
    entry = str(BACKEND_DIR / "main.py")

    # Data files to bundle (read-only, extracted to sys._MEIPASS)
    add_data = [
        f"{FRONTEND_DIR / 'index.html'}{sep}frontend",
        f"{PROJECT_ROOT / 'VERSION'}{sep}.",
    ]

    # Hidden imports (modules that PyInstaller might miss)
    hidden = [
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "aiohttp",
        "certifi",
        "multidict",
        "yarl",
        "async_timeout",
        "aiosignal",
        "frozenlist",
    ]

    # Backend modules to include
    backend_modules = [
        "autodarts_client", "device_manager", "wled_client",
        "config_manager", "event_defaults", "caller_defaults",
        "updater", "esp_flasher", "paths",
    ]

    args = [
        entry,
        "--name", "throwsync",
        "--onefile",
        "--console",  # Keep console for logging
        "--noconfirm",
        # Add all backend modules as --hidden-import
        *[f"--hidden-import={m}" for m in hidden],
        # Add paths so PyInstaller finds backend modules
        "--paths", str(BACKEND_DIR),
        # Add data files
        *[f"--add-data={d}" for d in add_data],
        # Output
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
    ]

    print(f"\n  Building...")
    print(f"  {'='*50}")

    PyInstaller.__main__.run(args)

    # Check output
    binary_name = "throwsync.exe" if SYSTEM == "windows" else "throwsync"
    binary_path = DIST_DIR / binary_name

    if binary_path.exists():
        size_mb = binary_path.stat().st_size / (1024 * 1024)
        print(f"\n  {'='*50}")
        print(f"  ✓ Binary erstellt: {binary_path}")
        print(f"  ✓ Größe: {size_mb:.1f} MB")
        print(f"  ✓ Platform: {PLATFORM_TAG}")

        # Rename with platform tag for release
        release_name = f"throwsync-{version}-{PLATFORM_TAG}{'.exe' if SYSTEM == 'windows' else ''}"
        release_path = DIST_DIR / release_name
        shutil.copy2(binary_path, release_path)
        print(f"  ✓ Release: {release_path}")

        print(f"\n  Zum Starten:")
        if SYSTEM == "windows":
            print(f"    {release_path}")
        else:
            print(f"    chmod +x {release_path}")
            print(f"    ./{release_name}")
        print(f"\n  Config/Sounds Ordner werden beim ersten Start neben dem Binary erstellt.")
    else:
        print(f"\n  ✗ Build fehlgeschlagen! Binary nicht gefunden.")
        sys.exit(1)


def main():
    print()
    print("  ┌──────────────────────────────────┐")
    print("  │   ThrowSync — Binary Builder      │")
    print("  └──────────────────────────────────┘")
    print()

    if not check_pyinstaller():
        sys.exit(1)

    if "--clean" in sys.argv:
        print("\n  Cleaning...")
        clean()

    # Always clean before build
    clean()

    print(f"\n  Building for {PLATFORM_TAG}...")
    build()


if __name__ == "__main__":
    main()
