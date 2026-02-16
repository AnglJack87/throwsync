"""
ESP Flasher - Flash, backup, and restore WLED firmware.
Supports:
  - OTA (Over-The-Air) updates via WiFi for controllers like Gledopto GL-C-008WL
  - Serial USB flashing for bare ESP32/ESP8266 boards
  - Firmware download from WLED GitHub releases
  - Chip detection and firmware validation
"""

import asyncio
import logging
import os
import json
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime

import aiohttp

logger = logging.getLogger("esp-flasher")


# Known controller profiles
CONTROLLER_PROFILES = {
    "gledopto_gl-c-008wl": {
        "name": "Gledopto GL-C-008WL",
        "chip": "esp8266",
        "flash_method": "ota",
        "has_usb": False,
        "max_ics": 800,
        "voltage": "5-24V",
        "supported_strips": ["WS2812B", "WS2811", "SK6812", "SM16703P"],
        "notes": "WLED ist vorinstalliert. Updates NUR per OTA (WiFi). "
                 "NIEMALS ESP32-Firmware flashen — Controller wird zerstört!",
        "firmware_filter": "esp8266",
    },
    "esp32_generic": {
        "name": "ESP32 (Generic)",
        "chip": "esp32",
        "flash_method": "serial",
        "has_usb": True,
        "firmware_filter": "esp32",
        "notes": "Standard ESP32 DevKit. Flash per USB-Serial.",
    },
    "esp32s3_supermini": {
        "name": "ESP32-S3 SuperMini",
        "chip": "esp32s3",
        "flash_method": "serial",
        "has_usb": True,
        "firmware_filter": "esp32s3",
        "notes": "ESP32-S3 mit USB-C. Flash per USB.",
    },
    "esp32c3": {
        "name": "ESP32-C3",
        "chip": "esp32c3",
        "flash_method": "serial",
        "has_usb": True,
        "firmware_filter": "esp32c3",
        "notes": "ESP32-C3 Mini. Flash per USB.",
    },
    "esp8266_d1mini": {
        "name": "ESP8266 D1 Mini / NodeMCU",
        "chip": "esp8266",
        "flash_method": "serial",
        "has_usb": True,
        "firmware_filter": "esp8266",
        "notes": "ESP8266 mit USB. Flash per USB-Serial.",
    },
    "esp8266_ota_generic": {
        "name": "ESP8266 Controller (WiFi/OTA)",
        "chip": "esp8266",
        "flash_method": "ota",
        "has_usb": False,
        "firmware_filter": "esp8266",
        "notes": "ESP8266-basierter Controller ohne USB. Updates NUR per OTA (WiFi).",
    },
}


class ESPFlasher:
    """Handles ESP flashing via OTA (WiFi) and Serial (USB)."""

    WLED_RELEASES_API = "https://api.github.com/repos/Aircoookie/WLED/releases"
    FIRMWARE_DIR = Path("firmware")
    BACKUP_DIR = Path("backups")

    def __init__(self):
        self.FIRMWARE_DIR.mkdir(exist_ok=True)
        self.BACKUP_DIR.mkdir(exist_ok=True)

    # ─── Controller Profiles ─────────────────────────────────────────────────

    def get_controller_profiles(self) -> dict:
        """Get all known controller profiles."""
        return CONTROLLER_PROFILES

    # ─── Serial Port Detection ───────────────────────────────────────────────

    def list_ports(self) -> list:
        """List available serial ports for USB-connected boards."""
        try:
            import serial.tools.list_ports
            ports = []
            for port in serial.tools.list_ports.comports():
                ports.append({
                    "port": port.device,
                    "description": port.description,
                    "manufacturer": port.manufacturer or "Unknown",
                    "vid_pid": f"{port.vid:04X}:{port.pid:04X}" if port.vid else "N/A",
                    "serial_number": port.serial_number or "N/A",
                })
            return ports
        except ImportError:
            logger.warning("pyserial not installed")
            return []
        except Exception as e:
            logger.error(f"Error listing ports: {e}")
            return []

    # ─── Firmware Management ─────────────────────────────────────────────────

    async def get_available_firmwares(self, chip_filter: str = None) -> list:
        """Fetch available WLED firmware releases from GitHub."""
        firmwares = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.WLED_RELEASES_API,
                    params={"per_page": 15},
                    headers={"Accept": "application/vnd.github.v3+json"}
                ) as resp:
                    if resp.status == 200:
                        releases = await resp.json()
                        for release in releases:
                            version = release.get("tag_name", "")
                            name = release.get("name", version)
                            prerelease = release.get("prerelease", False)

                            assets = []
                            for asset in release.get("assets", []):
                                filename = asset.get("name", "")
                                if not filename.endswith(".bin"):
                                    continue

                                chip = self._detect_chip(filename)
                                is_ota = self._is_ota_binary(filename)

                                # Apply chip filter
                                if chip_filter and chip != chip_filter:
                                    continue

                                assets.append({
                                    "filename": filename,
                                    "url": asset.get("browser_download_url", ""),
                                    "size": asset.get("size", 0),
                                    "chip": chip,
                                    "is_ota": is_ota,
                                    "variant": self._detect_variant(filename),
                                })

                            if assets:
                                firmwares.append({
                                    "version": version,
                                    "name": name,
                                    "prerelease": prerelease,
                                    "date": release.get("published_at", ""),
                                    "assets": assets,
                                })
        except Exception as e:
            logger.error(f"Error fetching firmware list: {e}")

        # Add local firmware files
        for f in self.FIRMWARE_DIR.glob("*.bin"):
            chip = self._detect_chip(f.name)
            if chip_filter and chip != chip_filter:
                continue
            firmwares.append({
                "version": "local",
                "name": f.name,
                "prerelease": False,
                "date": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "assets": [{
                    "filename": f.name,
                    "url": "",
                    "size": f.stat().st_size,
                    "chip": chip,
                    "is_ota": self._is_ota_binary(f.name),
                    "variant": self._detect_variant(f.name),
                    "local_path": str(f),
                }],
                "local": True,
            })

        return firmwares

    def _detect_chip(self, filename: str) -> str:
        """Detect chip type from firmware filename."""
        fl = filename.lower()
        if "esp32s3" in fl: return "esp32s3"
        if "esp32s2" in fl: return "esp32s2"
        if "esp32c3" in fl: return "esp32c3"
        if "esp32" in fl and "esp8266" not in fl: return "esp32"
        if "esp8266" in fl or "esp01" in fl or "esp02" in fl or "d1_mini" in fl: return "esp8266"
        # WLED naming convention: files without esp32 prefix are usually esp8266
        if "wled" in fl and "esp32" not in fl: return "esp8266"
        return "unknown"

    def _is_ota_binary(self, filename: str) -> bool:
        """Check if this is an OTA-compatible binary (no bootloader)."""
        fl = filename.lower()
        # OTA binaries usually don't contain "factory" or "0x" flash addresses
        # and are generally smaller
        if "ota" in fl:
            return True
        if "factory" in fl or "0x0" in fl:
            return False
        # ESP8266 WLED binaries are typically OTA-compatible
        if self._detect_chip(filename) == "esp8266":
            return True
        return False

    def _detect_variant(self, filename: str) -> str:
        """Detect firmware variant from filename."""
        fl = filename.lower()
        chip = self._detect_chip(filename)
        extras = []
        if "audioreactive" in fl or "sound" in fl: extras.append("Sound")
        if "ethernet" in fl: extras.append("Ethernet")
        if "xl" in fl: extras.append("XL")

        label = chip.upper()
        if extras:
            label += f" ({', '.join(extras)})"
        return label

    async def download_firmware(self, version: str, filename: str = None,
                                chip_filter: str = None) -> dict:
        """Download a specific firmware file."""
        firmwares = await self.get_available_firmwares(chip_filter)
        for fw in firmwares:
            if fw["version"] == version:
                for asset in fw["assets"]:
                    if filename and asset["filename"] == filename:
                        return await self._download_file(asset["url"], asset["filename"])
                    elif not filename and asset.get("url"):
                        return await self._download_file(asset["url"], asset["filename"])
        return {"success": False, "error": "Firmware not found"}

    async def _download_file(self, url: str, filename: str) -> dict:
        """Download a file from URL."""
        try:
            filepath = self.FIRMWARE_DIR / filename
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        with open(filepath, "wb") as f:
                            f.write(await resp.read())
                        return {
                            "success": True,
                            "path": str(filepath),
                            "filename": filename,
                            "size": filepath.stat().st_size,
                        }
            return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─── OTA Flashing (WiFi) ────────────────────────────────────────────────

    async def flash_ota(self, device_ip: str, firmware_path: str,
                        progress_callback: Optional[Callable] = None) -> dict:
        """
        Flash firmware via OTA (WiFi) to a WLED device.
        This is the method for Gledopto and other WiFi-only controllers.
        Uses the WLED /update endpoint.
        """
        if not os.path.exists(firmware_path):
            msg = {"success": False, "error": "Firmware-Datei nicht gefunden", "stage": "error"}
            if progress_callback: await progress_callback(msg)
            return msg

        # Validate chip compatibility
        filename = os.path.basename(firmware_path)
        chip = self._detect_chip(filename)

        try:
            # Step 1: Check device is reachable
            if progress_callback:
                await progress_callback({
                    "stage": "checking", "progress": 5,
                    "message": f"Prüfe Verbindung zu {device_ip}..."
                })

            async with aiohttp.ClientSession() as session:
                # Get device info to verify chip type
                try:
                    async with session.get(
                        f"http://{device_ip}/json/info",
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        if resp.status == 200:
                            info = await resp.json()
                            device_arch = info.get("arch", "").lower()
                            device_ver = info.get("ver", "unknown")
                            device_name = info.get("name", device_ip)

                            logger.info(f"Device: {device_name}, Version: {device_ver}, Arch: {device_arch}")

                            # ── SAFETY CHECK: Chip compatibility ──
                            if device_arch and chip != "unknown":
                                if "esp8266" in device_arch and chip != "esp8266":
                                    msg = {
                                        "success": False,
                                        "stage": "error",
                                        "error": f"⛔ STOPP! Dein Controller ist ein ESP8266, "
                                                 f"aber die Firmware ist für {chip.upper()}! "
                                                 f"Falsche Firmware zerstört den Controller!"
                                    }
                                    if progress_callback: await progress_callback(msg)
                                    return msg
                                if "esp32" in device_arch and chip == "esp8266":
                                    msg = {
                                        "success": False,
                                        "stage": "error",
                                        "error": f"⛔ STOPP! Dein Controller ist ein ESP32, "
                                                 f"aber die Firmware ist für ESP8266!"
                                    }
                                    if progress_callback: await progress_callback(msg)
                                    return msg
                        else:
                            msg = {"success": False, "error": f"Gerät antwortet nicht richtig (HTTP {resp.status})", "stage": "error"}
                            if progress_callback: await progress_callback(msg)
                            return msg
                except aiohttp.ClientError:
                    msg = {"success": False, "error": f"Gerät {device_ip} nicht erreichbar", "stage": "error"}
                    if progress_callback: await progress_callback(msg)
                    return msg

                # Step 2: Upload firmware via OTA
                if progress_callback:
                    await progress_callback({
                        "stage": "uploading", "progress": 20,
                        "message": f"Lade Firmware hoch zu {device_name}..."
                    })

                firmware_size = os.path.getsize(firmware_path)

                with open(firmware_path, "rb") as f:
                    data = aiohttp.FormData()
                    data.add_field('update',
                                   f,
                                   filename=filename,
                                   content_type='application/octet-stream')

                    try:
                        async with session.post(
                            f"http://{device_ip}/update",
                            data=data,
                            timeout=aiohttp.ClientTimeout(total=120)
                        ) as resp:
                            response_text = await resp.text()

                            if resp.status == 200 and "Update" in response_text:
                                if progress_callback:
                                    await progress_callback({
                                        "stage": "restarting", "progress": 90,
                                        "message": "Firmware hochgeladen! Gerät startet neu..."
                                    })

                                # Wait for device to reboot
                                await asyncio.sleep(8)

                                # Verify device came back online
                                for attempt in range(10):
                                    try:
                                        async with session.get(
                                            f"http://{device_ip}/json/info",
                                            timeout=aiohttp.ClientTimeout(total=3)
                                        ) as check:
                                            if check.status == 200:
                                                new_info = await check.json()
                                                new_ver = new_info.get("ver", "?")
                                                if progress_callback:
                                                    await progress_callback({
                                                        "stage": "complete", "progress": 100,
                                                        "message": f"✅ Update erfolgreich! Neue Version: {new_ver}"
                                                    })
                                                return {
                                                    "success": True,
                                                    "message": f"OTA Update erfolgreich! Version: {new_ver}",
                                                    "old_version": device_ver,
                                                    "new_version": new_ver,
                                                }
                                    except Exception:
                                        pass
                                    await asyncio.sleep(2)

                                # Device didn't come back but update was accepted
                                if progress_callback:
                                    await progress_callback({
                                        "stage": "complete", "progress": 100,
                                        "message": "Firmware hochgeladen. Gerät startet neu — prüfe manuell!"
                                    })
                                return {"success": True, "message": "Firmware uploaded, device rebooting"}

                            else:
                                msg = {
                                    "success": False, "stage": "error",
                                    "error": f"Upload fehlgeschlagen: {response_text[:200]}"
                                }
                                if progress_callback: await progress_callback(msg)
                                return msg

                    except asyncio.TimeoutError:
                        msg = {"success": False, "stage": "error", "error": "Upload Timeout — Gerät reagiert nicht"}
                        if progress_callback: await progress_callback(msg)
                        return msg

        except Exception as e:
            msg = {"success": False, "stage": "error", "error": str(e)}
            if progress_callback: await progress_callback(msg)
            return msg

    # ─── Serial Flashing (USB) ──────────────────────────────────────────────

    async def flash_serial(self, port: str, firmware_path: str, chip: str = "esp32",
                           erase_first: bool = True,
                           progress_callback: Optional[Callable] = None) -> dict:
        """Flash firmware via serial (USB) using esptool."""
        if not os.path.exists(firmware_path):
            msg = {"success": False, "error": "Firmware-Datei nicht gefunden", "stage": "error"}
            if progress_callback: await progress_callback(msg)
            return msg

        baud = "921600" if chip != "esp8266" else "460800"

        try:
            if progress_callback:
                await progress_callback({"stage": "starting", "progress": 0, "message": "Starte Flash..."})

            if erase_first:
                if progress_callback:
                    await progress_callback({"stage": "erasing", "progress": 10, "message": "Lösche Flash..."})

                proc = await asyncio.create_subprocess_exec(
                    "esptool.py", "--port", port, "--baud", baud, "erase_flash",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    error = stderr.decode() or stdout.decode()
                    msg = {"success": False, "error": f"Löschen fehlgeschlagen: {error}", "stage": "error"}
                    if progress_callback: await progress_callback(msg)
                    return msg

            if progress_callback:
                await progress_callback({"stage": "flashing", "progress": 30, "message": "Schreibe Firmware..."})

            # Flash address depends on chip
            flash_addr = "0x0"

            cmd = [
                "esptool.py", "--port", port, "--baud", baud,
                "--chip", chip if chip != "esp8266" else "esp8266",
                "write_flash", "-z", flash_addr, firmware_path
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode() + stderr.decode()

            if proc.returncode == 0:
                if progress_callback:
                    await progress_callback({"stage": "complete", "progress": 100, "message": "Flash erfolgreich! Gerät startet neu..."})
                return {"success": True, "message": "Flash successful", "output": output}
            else:
                msg = {"success": False, "error": f"Flash fehlgeschlagen: {output}", "stage": "error"}
                if progress_callback: await progress_callback(msg)
                return msg

        except FileNotFoundError:
            msg = {"success": False, "error": "esptool.py nicht gefunden. Installiere mit: pip install esptool", "stage": "error"}
            if progress_callback: await progress_callback(msg)
            return msg
        except Exception as e:
            msg = {"success": False, "error": str(e), "stage": "error"}
            if progress_callback: await progress_callback(msg)
            return msg

    # ─── Backup (Serial only) ───────────────────────────────────────────────

    async def backup(self, port: str, chip: str = "esp32",
                     progress_callback: Optional[Callable] = None) -> dict:
        """Backup current firmware from device via serial."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.BACKUP_DIR / f"backup_{chip}_{timestamp}.bin"
            flash_size = "0x400000" if chip != "esp8266" else "0x100000"  # 4MB vs 1MB

            if progress_callback:
                await progress_callback({"stage": "reading", "progress": 10, "message": "Lese Flash..."})

            baud = "921600" if chip != "esp8266" else "460800"
            proc = await asyncio.create_subprocess_exec(
                "esptool.py", "--port", port, "--baud", baud,
                "read_flash", "0x0", flash_size, str(backup_file),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                if progress_callback:
                    await progress_callback({"stage": "complete", "progress": 100, "message": "Backup fertig!"})
                return {
                    "success": True, "path": str(backup_file),
                    "filename": backup_file.name, "size": backup_file.stat().st_size,
                }
            else:
                return {"success": False, "error": f"Backup fehlgeschlagen: {(stderr or stdout).decode()}"}
        except FileNotFoundError:
            return {"success": False, "error": "esptool.py nicht gefunden"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def restore(self, port: str, backup_path: str, chip: str = "esp32",
                      progress_callback: Optional[Callable] = None) -> dict:
        """Restore a backup via serial."""
        return await self.flash_serial(port, backup_path, chip, True, progress_callback)

    def get_backups(self) -> list:
        """List available backups."""
        backups = []
        for f in sorted(self.BACKUP_DIR.glob("*.bin"), reverse=True):
            backups.append({
                "filename": f.name, "path": str(f),
                "size": f.stat().st_size,
                "date": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return backups

    # ─── WLED Version Check ──────────────────────────────────────────────────

    async def check_device_version(self, device_ip: str) -> Optional[dict]:
        """Check current WLED version on a device via HTTP."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"http://{device_ip}/json/info") as resp:
                    if resp.status == 200:
                        info = await resp.json()
                        return {
                            "version": info.get("ver", "unknown"),
                            "arch": info.get("arch", "unknown"),
                            "name": info.get("name", device_ip),
                            "led_count": info.get("leds", {}).get("count", 0),
                            "free_heap": info.get("freeheap", 0),
                            "uptime": info.get("uptime", 0),
                            "build": info.get("vid", 0),
                        }
        except Exception:
            pass
        return None
