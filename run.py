#!/usr/bin/env python3
"""
ThrowSync - Launcher
Starts the server with auto-restart support for updates.

Update flow:
  1. Server downloads update ZIP and stages in _update_staging/
  2. Server writes .restart flag and exits
  3. This launcher detects .restart, applies staged update, restarts server
"""

import os
import sys
import subprocess
import webbrowser
import time
import threading
import shutil
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8420

PROJECT_ROOT = Path(__file__).parent.resolve()
RESTART_FLAG = PROJECT_ROOT / ".restart"
STAGING_DIR = PROJECT_ROOT / "_update_staging"
BACKUP_DIR = PROJECT_ROOT / "_update_backup"
VERSION_FILE = PROJECT_ROOT / "VERSION"


def activate_venv():
    """Auto-detect and activate venv if it exists."""
    venv_dir = PROJECT_ROOT / "venv"
    if not venv_dir.exists():
        return False

    # Already in venv?
    if sys.prefix != sys.base_prefix:
        return True

    if sys.platform == "win32":
        site_packages = venv_dir / "Lib" / "site-packages"
        bin_dir = venv_dir / "Scripts"
    else:
        # Find the python version dir (e.g. python3.11, python3.13)
        lib_dir = venv_dir / "lib"
        if lib_dir.exists():
            py_dirs = [d for d in lib_dir.iterdir() if d.name.startswith("python")]
            if py_dirs:
                site_packages = py_dirs[0] / "site-packages"
            else:
                return False
        else:
            return False
        bin_dir = venv_dir / "bin"

    if site_packages.exists():
        # Add to sys.path so imports work
        sp = str(site_packages)
        if sp not in sys.path:
            sys.path.insert(0, sp)

        # Update PATH so subprocess calls (pip) use venv python
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        os.environ["VIRTUAL_ENV"] = str(venv_dir)

        print(f"  Python-Umgebung: venv ({site_packages.parent.name})")
        return True

    return False


# Activate venv BEFORE any dependency checks
activate_venv()

# Files/dirs to NEVER delete during update (user data)
KEEP_PATHS = {
    "_update_staging", "_update_backup", ".restart", ".updating",
    "venv", "__pycache__", "backend/__pycache__",
    "backend/config.json", "backend/config.json.bak", "backend/sounds",
}

PRESERVE_PATHS = {
    "backend/config.json", "backend/sounds", "backend/config.json.bak",
}


def get_version():
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return "?.?.?"


def check_dependencies():
    """Check and install missing dependencies."""
    try:
        import fastapi
        import uvicorn
        import aiohttp
        return True
    except ImportError:
        pass

    req_file = PROJECT_ROOT / "requirements.txt"
    venv_dir = PROJECT_ROOT / "venv"
    print("Abhaengigkeiten fehlen, werden installiert...")

    # Try direct pip install first
    for extra_args in [[], ["--break-system-packages"]]:
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-r", str(req_file)] + extra_args,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print("Abhaengigkeiten installiert!")
            return True
        except subprocess.CalledProcessError:
            pass

    # If pip failed (externally-managed), create venv
    if not venv_dir.exists():
        print("  Erstelle virtuelle Umgebung (venv)...")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
            print("  venv erstellt!")
        except subprocess.CalledProcessError:
            print("FEHLER: Konnte venv nicht erstellen!")
            print("   Bitte fuehre aus:  sudo apt install python3-venv")
            sys.exit(1)

    # Install into venv
    if sys.platform == "win32":
        venv_pip = venv_dir / "Scripts" / "pip"
    else:
        venv_pip = venv_dir / "bin" / "pip"

    try:
        subprocess.check_call([str(venv_pip), "install", "-r", str(req_file)])
        print("  Abhaengigkeiten in venv installiert!")
        # Activate the new venv for this session
        activate_venv()
        return True
    except subprocess.CalledProcessError as e:
        print(f"FEHLER: pip install fehlgeschlagen: {e}")

    print("FEHLER: Konnte Abhaengigkeiten nicht installieren!")
    print("   Bitte fuehre zuerst aus:  ./install.sh")
    sys.exit(1)


def open_browser():
    time.sleep(2)
    webbrowser.open(f"http://localhost:{PORT}")


def apply_staged_update():
    """Apply staged update files before restart."""
    staged = STAGING_DIR / "files"
    if not staged.exists() or not staged.is_dir():
        print("  Kein staged Update gefunden — starte ohne Update")
        return False

    old_ver = get_version()
    print(f"\n  Update wird installiert (von v{old_ver})...")

    try:
        # Create backup of current installation
        if BACKUP_DIR.exists():
            shutil.rmtree(BACKUP_DIR)
        BACKUP_DIR.mkdir(parents=True)

        for item in PROJECT_ROOT.iterdir():
            rel = item.name
            if rel in KEEP_PATHS or rel.startswith(".") or rel.startswith("_"):
                continue
            dest = BACKUP_DIR / rel
            try:
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            except Exception as e:
                print(f"  Backup-Warnung: {rel}: {e}")

        print("  Backup erstellt")

        # Copy staged files over current installation
        for item in staged.iterdir():
            rel = item.name
            dest = PROJECT_ROOT / rel

            # Check preserve list
            skip = False
            if str(rel) in PRESERVE_PATHS:
                skip = True
            elif item.is_dir():
                for preserve in PRESERVE_PATHS:
                    if preserve.startswith(rel + "/") or preserve == rel:
                        if dest.exists() and dest.is_dir():
                            _merge_dir(item, dest)
                            skip = True
                            break

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

        # Cleanup staging
        shutil.rmtree(STAGING_DIR, ignore_errors=True)

        new_ver = get_version()
        print(f"  Update installiert: v{old_ver} -> v{new_ver}")
        return True

    except Exception as e:
        print(f"\n  UPDATE FEHLGESCHLAGEN: {e}")
        print("  Versuche Rollback...")
        try:
            _rollback()
            print("  Rollback erfolgreich")
        except Exception as rb:
            print(f"  Rollback fehlgeschlagen: {rb}")
        return False


def _merge_dir(src, dest):
    """Merge source dir into destination, preserving user files."""
    for item in src.iterdir():
        rel_path = str(dest.relative_to(PROJECT_ROOT) / item.name)
        dest_item = dest / item.name
        if rel_path in PRESERVE_PATHS:
            continue
        if item.is_dir():
            if dest_item.exists():
                _merge_dir(item, dest_item)
            else:
                shutil.copytree(item, dest_item)
        else:
            shutil.copy2(item, dest_item)


def _rollback():
    """Restore from backup."""
    if not BACKUP_DIR.exists():
        raise RuntimeError("Kein Backup vorhanden")
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


def run_server():
    """Run the server. Returns True if restart was requested."""
    backend_dir = PROJECT_ROOT / "backend"

    if not backend_dir.is_dir():
        print(f"FEHLER: Backend-Ordner nicht gefunden: {backend_dir}")
        sys.exit(1)

    os.chdir(str(backend_dir))

    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    # Clear cached modules so updated code gets loaded on restart
    mods_to_reload = [m for m in list(sys.modules.keys()) if m in (
        "main", "updater", "event_defaults", "caller_defaults",
        "device_manager", "wled_client", "autodarts_client",
        "esp_flasher", "config_manager",
    )]
    for m in mods_to_reload:
        del sys.modules[m]

    # Pre-check: try importing main
    try:
        import importlib
        importlib.import_module("main")
    except Exception as e:
        print(f"\n{'='*50}")
        print(f"  FEHLER beim Laden des Servers!")
        print(f"{'='*50}")
        print(f"  {type(e).__name__}: {e}")
        print(f"  Python {sys.version}")
        import traceback
        traceback.print_exc()
        print()
        input("Druecke Enter zum Beenden...")
        sys.exit(1)

    print(f"  Server startet auf http://localhost:{PORT}")
    print(f"  Erreichbar im Netzwerk unter http://<deine-ip>:{PORT}")
    print(f"  Druecke Strg+C zum Beenden")
    print()

    import uvicorn
    try:
        uvicorn.run("main:app", host=HOST, port=PORT, reload=False, log_level="info")
    except (KeyboardInterrupt, SystemExit):
        pass

    return RESTART_FLAG.exists()


def main():
    version = get_version()
    restart_count = 0
    max_restarts = 5

    while True:
        print()
        print("    +------------------------------------------+")
        print(f"    |     THROWSYNC v{version:<13s}|")
        print("    |     WLED + Autodarts + Caller + ESP Flasher     |")
        print("    +------------------------------------------+")
        print()

        if restart_count == 0:
            check_dependencies()
            threading.Thread(target=open_browser, daemon=True).start()

        should_restart = run_server()

        if not should_restart:
            print("\nServer beendet.")
            break

        restart_count += 1
        if restart_count > max_restarts:
            print("\n  Zu viele Neustarts — breche ab")
            RESTART_FLAG.unlink(missing_ok=True)
            break

        reason = "update"
        try:
            reason = RESTART_FLAG.read_text().strip()
        except Exception:
            pass
        RESTART_FLAG.unlink(missing_ok=True)

        print(f"\n  Neustart angefordert (Grund: {reason})")

        if reason == "update":
            apply_staged_update()

        version = get_version()
        print(f"\n  Server startet neu (v{version})...")
        print()
        time.sleep(1)


if __name__ == "__main__":
    main()
