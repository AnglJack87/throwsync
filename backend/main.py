"""
ThrowSync - Main Application
A comprehensive WLED + Autodarts management tool for ESP32 LED strips.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from event_defaults import DEFAULT_EVENT_MAPPINGS, get_merged_events
from caller_defaults import CALLER_SOUND_EVENTS, CALLER_CATEGORIES, DEFAULT_CALLER_CONFIG, get_merged_caller

from device_manager import DeviceManager
from wled_client import WLEDClient
from autodarts_client import AutodartsClient
from esp_flasher import ESPFlasher
from config_manager import ConfigManager
from updater import (
    check_for_update, download_and_stage, trigger_restart,
    get_update_status, get_local_version, cleanup as updater_cleanup,
    DEFAULT_MANIFEST_URL, rollback_update,
)
import time as _time
from paths import FROZEN, BUNDLE_DIR, DATA_DIR, FRONTEND_HTML, SOUNDS_DIR, FIRMWARE_DIR, get_version as get_app_version

# Module version imports
from autodarts_client import MODULE_VERSION as AUTODARTS_VERSION
from device_manager import MODULE_VERSION as DEVICE_MGR_VERSION
from wled_client import MODULE_VERSION as WLED_VERSION
from caller_defaults import MODULE_VERSION as CALLER_VERSION
from event_defaults import MODULE_VERSION as EVENTS_VERSION
from updater import MODULE_VERSION as UPDATER_VERSION
from esp_flasher import MODULE_VERSION as FLASHER_VERSION

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("throwsync")

# Global instances
config_manager = ConfigManager(str(DATA_DIR / "config.json"))
device_manager = DeviceManager(config_manager)
autodarts_client = AutodartsClient(config_manager, device_manager)
esp_flasher = ESPFlasher()

# WebSocket connections for live UI updates
ws_connections: list[WebSocket] = []

# Event log (in-memory, last 200 events)
event_log: list = []
EVENT_LOG_MAX = 200


async def broadcast_ws(msg: dict):
    """Broadcast a message to all connected WebSocket clients."""
    dead = []
    for ws in ws_connections:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_connections.remove(ws)


async def log_event(event_name: str, board_name: str = "", details: dict = None):
    """Log an event and broadcast it to connected clients."""
    import time
    entry = {
        "timestamp": time.time(),
        "event": event_name,
        "board": board_name,
        "details": details or {},
    }
    event_log.append(entry)
    if len(event_log) > EVENT_LOG_MAX:
        event_log.pop(0)
    await broadcast_ws({"type": "event_fired", "entry": entry})


async def broadcast_caller_sound(sounds: list, event_name: str = "", data: dict = None):
    """Broadcast caller sound play command to all connected UI clients.
    Resolves sound file assignments from saved config before sending."""
    caller_cfg = config_manager.get("caller_config", {})
    if not caller_cfg.get("enabled", False):
        return
    # Check config-level filters
    if not caller_cfg.get("ambient_sounds", True):
        sounds = [s for s in sounds if not s.get("key", "").startswith("caller_ambient_")]
    if not caller_cfg.get("checkout_call", True):
        sounds = [s for s in sounds if not s.get("key", "").startswith("caller_checkout_") and s.get("key") != "caller_you_require"]
    # Filter throw sounds based on call_every_dart mode
    dart_mode = caller_cfg.get("call_every_dart", 0)
    if event_name == "throw":
        if dart_mode == 0:
            # Don't call individual darts at all
            sounds = [s for s in sounds if not s.get("type", "").startswith("dart_")]
        elif dart_mode == 1:
            # Score only (e.g. "60")
            sounds = [s for s in sounds if s.get("type") in ("dart_score", None)]
        elif dart_mode == 2:
            # Field name (e.g. "Triple 20") — prefer specific, fallback to generic
            dart_names = [s for s in sounds if s.get("type") == "dart_name"]
            dart_fallback = [s for s in sounds if s.get("type") == "dart_name_fallback"]
            other = [s for s in sounds if not s.get("type", "").startswith("dart_")]
            sounds = (dart_names or dart_fallback) + other
        elif dart_mode == 3:
            # Effect sounds
            dart_effects = [s for s in sounds if s.get("type") == "dart_effect"]
            dart_fallback = [s for s in sounds if s.get("type") == "dart_effect_fallback"]
            other = [s for s in sounds if not s.get("type", "").startswith("dart_")]
            sounds = (dart_effects or dart_fallback) + other
    # Score after turn: only call round score if enabled
    if event_name == "player_change" and not caller_cfg.get("call_score_after_turn", True):
        sounds = [s for s in sounds if not s.get("key", "").startswith("caller_score_")]
    if not sounds:
        return
    # Resolve sound files from saved assignments
    saved = config_manager.get("caller_sounds", {})
    merged = get_merged_caller(saved)
    resolved = []
    for s in sounds:
        key = s.get("key", "")
        entry = merged.get(key, {})
        if entry.get("enabled", True) and entry.get("sound"):
            resolved.append({
                "key": key,
                "sound": entry["sound"],
                "volume": entry.get("volume", 1.0),
                "priority": s.get("priority", 1),
            })
    if not resolved:
        return
    global_vol = caller_cfg.get("volume", 0.8)
    logger.debug(f"Caller play: {[r['key'] for r in resolved]}")
    await broadcast_ws({
        "type": "caller_play",
        "sounds": resolved,
        "event": event_name,
        "data": data or {},
        "volume": global_vol,
    })


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    logger.info("Starting ThrowSync...")
    config_manager.load()
    # Ensure sounds directory exists (uses paths.py)
    SOUNDS_DIR.mkdir(exist_ok=True)
    await device_manager.start()
    # Wire up event logging callback
    autodarts_client.event_callback = log_event
    # Wire up caller broadcast callback
    autodarts_client.caller_callback = broadcast_caller_sound
    # Auto-connect all enabled boards
    if config_manager.get("boards", []):
        asyncio.create_task(autodarts_client.connect_all())
    yield
    logger.info("Shutting down...")
    await autodarts_client.disconnect()
    await device_manager.stop()
    config_manager.save()


app = FastAPI(title="ThrowSync", version="1.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── WebSocket for live updates ───────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_connections.append(ws)
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            # Handle incoming commands from frontend
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_connections.remove(ws)


# ─── Device Management ────────────────────────────────────────────────────────

@app.get("/api/devices")
async def get_devices():
    """Get all managed WLED devices with their current status."""
    devices = await device_manager.get_all_devices()
    return {"devices": devices}


@app.post("/api/devices")
async def add_device(data: dict):
    """Add a new WLED device by IP address."""
    ip = data.get("ip", "").strip()
    name = data.get("name", "").strip()
    led_count = data.get("led_count", 0)
    if not ip:
        raise HTTPException(400, "IP address required")
    device = await device_manager.add_device(ip, name, led_count)
    if device:
        await broadcast_ws({"type": "device_added", "device": device})
        return {"success": True, "device": device}
    raise HTTPException(400, "Could not connect to WLED device at this IP")


@app.post("/api/devices/{device_id}/led-count")
async def set_led_count(device_id: str, data: dict):
    """Set LED count for a device and push to WLED."""
    led_count = data.get("led_count", 0)
    result = await device_manager.set_led_count(device_id, led_count)
    if result:
        return {"success": True}
    raise HTTPException(400, "Konnte LED-Anzahl nicht setzen")


@app.delete("/api/devices/{device_id}")
async def remove_device(device_id: str):
    """Remove a device from management."""
    success = device_manager.remove_device(device_id)
    if success:
        await broadcast_ws({"type": "device_removed", "device_id": device_id})
        return {"success": True}
    raise HTTPException(404, "Device not found")


@app.post("/api/devices/{device_id}/identify")
async def identify_device(device_id: str):
    """Flash a device briefly to identify it physically."""
    success = await device_manager.identify_device(device_id)
    return {"success": success}


@app.get("/api/devices/{device_id}/state")
async def get_device_state(device_id: str):
    """Get full WLED state of a device."""
    state = await device_manager.get_device_state(device_id)
    if state is None:
        raise HTTPException(404, "Device not found or offline")
    return state


@app.post("/api/devices/{device_id}/state")
async def set_device_state(device_id: str, data: dict):
    """Set WLED state on a device."""
    success = await device_manager.set_device_state(device_id, data)
    return {"success": success}


@app.get("/api/devices/{device_id}/info")
async def get_device_info(device_id: str):
    """Get detailed WLED info of a device."""
    info = await device_manager.get_device_info(device_id)
    if info is None:
        raise HTTPException(404, "Device not found or offline")
    return info


@app.get("/api/devices/discover")
async def discover_devices():
    """Scan the network for WLED devices."""
    devices = await device_manager.discover_devices()
    return {"discovered": devices}


# ─── LED Segment & Effect Control ─────────────────────────────────────────────

@app.get("/api/devices/{device_id}/segments")
async def get_segments(device_id: str):
    """Get all LED segments of a device."""
    segments = await device_manager.get_segments(device_id)
    return {"segments": segments}


@app.post("/api/devices/{device_id}/segments")
async def set_segments(device_id: str, data: dict):
    """Configure LED segments on a device."""
    success = await device_manager.set_segments(device_id, data.get("segments", []))
    return {"success": success}


@app.get("/api/effects")
async def get_effects():
    """Get list of available WLED effects."""
    return {"effects": WLEDClient.KNOWN_EFFECTS}


@app.get("/api/palettes")
async def get_palettes():
    """Get list of available WLED color palettes."""
    return {"palettes": WLEDClient.KNOWN_PALETTES}


@app.post("/api/devices/{device_id}/color")
async def set_color(device_id: str, data: dict):
    """Set color on a device or segment."""
    success = await device_manager.set_color(
        device_id,
        data.get("color", [255, 255, 255]),
        data.get("segment", None),
        data.get("brightness", None)
    )
    return {"success": success}


@app.post("/api/devices/{device_id}/effect")
async def set_effect(device_id: str, data: dict):
    """Set an effect on a device or segment."""
    success = await device_manager.set_effect(
        device_id,
        data.get("effect_id", 0),
        data.get("speed", 128),
        data.get("intensity", 128),
        data.get("palette", 0),
        data.get("segment", None)
    )
    return {"success": success}


@app.post("/api/devices/{device_id}/individual")
async def set_individual_leds(device_id: str, data: dict):
    """Set individual LED colors."""
    success = await device_manager.set_individual_leds(
        device_id,
        data.get("leds", {})  # {led_index: [r,g,b], ...}
    )
    return {"success": success}


# ─── Autodarts Integration (Multi-Board) ─────────────────────────────────────

@app.get("/api/autodarts/status")
async def autodarts_status():
    """Get status of all Autodarts boards."""
    return {
        "any_connected": autodarts_client.connected,
        "boards": autodarts_client.get_all_boards_status(),
    }


@app.get("/api/autodarts/boards")
async def get_boards():
    """Get all configured boards with status."""
    return {"boards": autodarts_client.get_all_boards_status()}


@app.post("/api/autodarts/boards")
async def add_board(data: dict):
    """Add or update a board configuration."""
    logger.info(f"Board speichern: keys={list(data.keys())}, board_id={data.get('board_id','?')}, user={data.get('account_username','?')}, pw_len={len(data.get('account_password',''))}")
    boards = config_manager.get("boards", [])
    board_id = data.get("board_id", "")
    if not board_id:
        raise HTTPException(400, "Board ID required")

    # Update existing or add new
    existing = next((i for i, b in enumerate(boards) if b.get("board_id") == board_id), None)
    
    # Get password: from request, or preserve existing
    new_password = data.get("account_password", "")
    if not new_password and existing is not None:
        new_password = boards[existing].get("account_password", "")
    
    board_config = {
        "board_id": board_id,
        "name": data.get("name", f"Board {board_id[:8]}"),
        "account_username": data.get("account_username", "") or data.get("account_email", ""),
        "account_password": new_password,
        "assigned_devices": data.get("assigned_devices", []),
        "enabled": data.get("enabled", True),
        "auto_reconnect": data.get("auto_reconnect", True),
    }

    if existing is not None:
        boards[existing] = board_config
    else:
        boards.append(board_config)

    config_manager.set("boards", boards)
    config_manager.save()
    
    # Verify save worked
    saved = config_manager.get("boards", [])
    saved_board = next((b for b in saved if b.get("board_id") == board_id), None)
    pw_saved = bool(saved_board.get("account_password", "")) if saved_board else False
    logger.info(f"Board {board_id[:8]}... SAVED: password_set={pw_saved}, total_boards={len(saved)}")
    
    await broadcast_ws({"type": "boards_updated"})
    return {"success": True}


@app.delete("/api/autodarts/boards/{board_id}")
async def remove_board(board_id: str):
    """Remove a board configuration."""
    await autodarts_client.disconnect_board(board_id)
    boards = config_manager.get("boards", [])
    boards = [b for b in boards if b.get("board_id") != board_id]
    config_manager.set("boards", boards)
    config_manager.save()
    await broadcast_ws({"type": "boards_updated"})
    return {"success": True}


@app.post("/api/autodarts/boards/{board_id}/connect")
async def connect_board(board_id: str):
    """Connect a specific board."""
    boards = config_manager.get("boards", [])
    bc = next((b for b in boards if b.get("board_id") == board_id), None)
    if not bc:
        raise HTTPException(404, "Board not found")
    await autodarts_client.connect_board(bc)
    return {"success": True}


@app.post("/api/autodarts/boards/{board_id}/disconnect")
async def disconnect_board(board_id: str):
    """Disconnect a specific board."""
    await autodarts_client.disconnect_board(board_id)
    return {"success": True}


@app.post("/api/autodarts/boards/{board_id}/devices")
async def assign_devices_to_board(board_id: str, data: dict):
    """Assign ESP devices to a board."""
    boards = config_manager.get("boards", [])
    for i, b in enumerate(boards):
        if b.get("board_id") == board_id:
            boards[i]["assigned_devices"] = data.get("device_ids", [])
            break
    else:
        raise HTTPException(404, "Board not found")

    config_manager.set("boards", boards)
    config_manager.save()

    # Update live connection
    if board_id in autodarts_client.boards:
        autodarts_client.boards[board_id].assigned_devices = data.get("device_ids", [])

    return {"success": True}


@app.post("/api/autodarts/connect-all")
async def autodarts_connect_all():
    """Connect all enabled boards."""
    asyncio.create_task(autodarts_client.connect_all())
    return {"success": True}


@app.post("/api/autodarts/disconnect-all")
async def autodarts_disconnect_all():
    """Disconnect all boards."""
    await autodarts_client.disconnect()
    return {"success": True}


@app.get("/api/autodarts/events")
async def get_autodarts_events():
    """Get all events: defaults + any saved customizations."""
    saved = config_manager.get("event_mappings", {})
    return {"events": get_merged_events(saved)}


@app.post("/api/autodarts/events")
async def set_autodarts_events(data: dict):
    """Save Autodarts event → LED effect mappings."""
    config_manager.set("event_mappings", data.get("events", {}))
    config_manager.save()
    autodarts_client.reload_mappings()
    return {"success": True}


@app.post("/api/autodarts/test-event")
async def test_autodarts_event(data: dict):
    """Simulate an Autodarts event to test LED effects.
    Works even without board configuration by sending directly to all devices."""
    event_name = data.get("event", "")
    board_id = data.get("board_id", None)

    # Get event mapping
    saved = config_manager.get("event_mappings", {})
    mappings = get_merged_events(saved)
    mapping = mappings.get(event_name)

    if not mapping:
        return {"success": False, "error": f"Event '{event_name}' nicht gefunden"}

    # Try board-based first (if boards exist)
    if autodarts_client.boards:
        await autodarts_client.simulate_event(event_name, board_id)
    else:
        # No boards configured → send directly to ALL devices
        effect = mapping.get("effect", {})
        chain = mapping.get("chain", None)
        duration = mapping.get("duration", 0)

        state = {"on": True}
        seg = {}
        for key in ("fx", "sx", "ix", "pal", "col"):
            if key in effect:
                seg[key] = effect[key]
        if seg:
            state["seg"] = [seg]
        if "bri" in effect:
            state["bri"] = effect["bri"]

        devices = await device_manager.get_all_devices()
        online_devices = [d for d in devices if d.get("online")]
        if not online_devices:
            return {"success": False, "error": "Keine Geraete online"}

        for dev in online_devices:
            await device_manager.set_device_state(dev["id"], state)

        # Revert after duration
        if duration > 0:
            async def revert():
                import asyncio
                await asyncio.sleep(duration)
                idle = mappings.get("idle", {}).get("effect", {})
                idle_state = {"on": True}
                idle_seg = {}
                for key in ("fx", "sx", "ix", "pal", "col"):
                    if key in idle:
                        idle_seg[key] = idle[key]
                if idle_seg:
                    idle_state["seg"] = [idle_seg]
                if "bri" in idle:
                    idle_state["bri"] = idle["bri"]
                for dev in online_devices:
                    await device_manager.set_device_state(dev["id"], idle_state)
            import asyncio
            asyncio.create_task(revert())

    await log_event(event_name, board_id or "direct-test", {"source": "manual_test"})
    return {"success": True}


# ─── Event Log ────────────────────────────────────────────────────────────────

@app.get("/api/event-log")
async def get_event_log():
    """Get recent event log entries."""
    return {"log": event_log[-100:]}


@app.post("/api/event-log/clear")
async def clear_event_log():
    """Clear the event log."""
    event_log.clear()
    return {"success": True}


# ─── Bulk Edit Events ────────────────────────────────────────────────────────

@app.post("/api/autodarts/events/bulk")
async def bulk_edit_events(data: dict):
    """Apply changes to multiple events at once."""
    event_keys = data.get("keys", [])
    changes = data.get("changes", {})
    current = config_manager.get("event_mappings", {})

    for key in event_keys:
        if key not in current:
            continue
        for change_key, change_val in changes.items():
            if change_key == "effect":
                # Merge effect properties instead of replacing whole effect
                if "effect" not in current[key]:
                    current[key]["effect"] = {}
                current[key]["effect"].update(change_val)
            else:
                current[key][change_key] = change_val

    config_manager.set("event_mappings", current)
    config_manager.save()
    autodarts_client.reload_mappings()
    return {"success": True, "updated": len(event_keys)}


# ─── ESP32/ESP8266 Flashing (OTA + Serial) ───────────────────────────────────

# Cache for latest WLED version
_latest_firmware_cache = {"version": None, "checked_at": 0, "assets": []}


@app.get("/api/firmware/check")
async def check_firmware_updates():
    """Check all devices for available firmware updates."""
    import time
    cache = _latest_firmware_cache

    # Refresh cache if older than 10 minutes
    if time.time() - cache["checked_at"] > 600 or not cache["version"]:
        firmwares = await esp_flasher.get_available_firmwares()
        # Get latest stable release
        stable = [f for f in firmwares if not f.get("prerelease") and f["version"] != "local"]
        if stable:
            latest = stable[0]
            cache["version"] = latest["version"]
            cache["assets"] = latest["assets"]
            cache["checked_at"] = time.time()
            cache["name"] = latest.get("name", latest["version"])

    if not cache["version"]:
        return {"latest": None, "devices": []}

    # Compare each device
    devices = await device_manager.get_all_devices()
    result = []
    for dev in devices:
        dev_ver = dev.get("version", "unknown")
        latest_ver = cache["version"].lstrip("v")
        dev_ver_clean = dev_ver.lstrip("v") if dev_ver != "unknown" else ""

        needs_update = False
        if dev_ver_clean and dev_ver_clean != "unknown":
            try:
                # Compare version tuples
                dev_parts = [int(x) for x in dev_ver_clean.split(".")]
                lat_parts = [int(x) for x in latest_ver.split(".")]
                needs_update = dev_parts < lat_parts
            except (ValueError, AttributeError):
                needs_update = dev_ver_clean != latest_ver

        result.append({
            "id": dev["id"],
            "name": dev["name"],
            "ip": dev["ip"],
            "current_version": dev_ver,
            "online": dev.get("online", False),
            "needs_update": needs_update,
        })

    # Also get chip info for each online device
    for r in result:
        if r["online"]:
            info = await device_manager.get_device_info(r["id"])
            if info:
                r["arch"] = info.get("arch", "unknown")
                r["platform"] = info.get("platform", info.get("arch", "unknown"))

    return {
        "latest": {"version": cache["version"], "name": cache.get("name", "")},
        "devices": result,
    }


@app.post("/api/devices/{device_id}/update-firmware")
async def update_device_firmware(device_id: str):
    """One-click firmware update with strict chip verification."""
    # Get device info
    info = await device_manager.get_device_info(device_id)
    if not info:
        raise HTTPException(404, "Geraet nicht erreichbar")

    device_arch = info.get("arch", "").lower()
    device_platform = info.get("platform", "").lower()
    device_ver = info.get("ver", "unknown")
    device_name = info.get("name", "WLED")

    device_ip = None
    for d in await device_manager.get_all_devices():
        if d["id"] == device_id:
            device_ip = d["ip"]
            break
    if not device_ip:
        raise HTTPException(404, "Geraet nicht gefunden")

    # Determine chip type from device arch — STRICT detection, NO guessing
    chip = None
    arch_combined = f"{device_arch} {device_platform}".lower()
    logger.info(f"Firmware update for '{device_name}' ({device_ip}): arch='{device_arch}', platform='{device_platform}'")

    if "esp8266" in arch_combined or "8266" in arch_combined:
        chip = "esp8266"
    elif "esp32s3" in arch_combined or "32s3" in arch_combined:
        chip = "esp32s3"
    elif "esp32s2" in arch_combined or "32s2" in arch_combined:
        chip = "esp32s2"
    elif "esp32c3" in arch_combined or "32c3" in arch_combined:
        chip = "esp32c3"
    elif "esp32" in arch_combined or "32" in arch_combined:
        chip = "esp32"

    if not chip:
        raise HTTPException(400,
            f"Chip-Typ konnte nicht erkannt werden (arch: '{device_arch}'). "
            f"Bitte manuell ueber die Firmware-Seite updaten um den richtigen Chip auszuwaehlen.")

    logger.info(f"Detected chip type: {chip} for device '{device_name}'")

    # Get latest firmware for this chip
    firmwares = await esp_flasher.get_available_firmwares(chip)
    stable = [f for f in firmwares if not f.get("prerelease") and f["version"] != "local"]
    if not stable:
        raise HTTPException(404, f"Keine {chip.upper()}-Firmware gefunden")

    latest = stable[0]
    # Prefer OTA binary for the right chip
    ota_assets = [a for a in latest["assets"] if a.get("is_ota") and a.get("chip") == chip]
    if not ota_assets:
        ota_assets = [a for a in latest["assets"] if a.get("chip") == chip]
    if not ota_assets:
        raise HTTPException(404, f"Keine passende {chip.upper()} OTA-Firmware in {latest['version']} gefunden")

    asset = ota_assets[0]
    logger.info(f"Selected firmware: {asset['filename']} ({chip}) for '{device_name}'")

    # Download firmware
    dl_result = await esp_flasher.download_firmware(
        latest["version"], asset["filename"], chip
    )
    if not dl_result.get("success"):
        raise HTTPException(500, f"Download fehlgeschlagen: {dl_result.get('error', '?')}")

    # Flash OTA
    result = await esp_flasher.flash_ota(device_ip, dl_result["path"])
    return result

@app.get("/api/flash/profiles")
async def get_controller_profiles():
    """Get known controller profiles (Gledopto, ESP32, etc.)."""
    return {"profiles": esp_flasher.get_controller_profiles()}


@app.get("/api/flash/ports")
async def get_serial_ports():
    """List available serial ports for USB flashing."""
    ports = esp_flasher.list_ports()
    return {"ports": ports}


@app.get("/api/flash/firmwares")
async def get_firmwares(chip: str = None):
    """Get available WLED firmware versions, optionally filtered by chip."""
    firmwares = await esp_flasher.get_available_firmwares(chip)
    return {"firmwares": firmwares}


@app.post("/api/flash/download")
async def download_firmware(data: dict):
    """Download a WLED firmware binary."""
    version = data.get("version", "")
    filename = data.get("filename", None)
    chip_filter = data.get("chip_filter", None)
    result = await esp_flasher.download_firmware(version, filename, chip_filter)
    return result


@app.post("/api/flash/ota")
async def flash_ota(data: dict):
    """Flash firmware via OTA (WiFi) — for Gledopto and WiFi-only controllers."""
    device_ip = data.get("device_ip", "")
    firmware_path = data.get("firmware_path", "")
    if not device_ip or not firmware_path:
        raise HTTPException(400, "device_ip and firmware_path required")

    async def progress_callback(progress: dict):
        await broadcast_ws({"type": "flash_progress", **progress})

    asyncio.create_task(
        esp_flasher.flash_ota(device_ip, firmware_path, progress_callback)
    )
    return {"success": True, "message": "OTA Flash gestartet"}


@app.post("/api/flash/serial")
async def flash_serial(data: dict):
    """Flash firmware via serial (USB) — for ESP boards with USB port."""
    port = data.get("port", "")
    firmware_path = data.get("firmware_path", "")
    chip = data.get("chip", "esp32")
    erase_first = data.get("erase_first", True)
    if not port or not firmware_path:
        raise HTTPException(400, "port and firmware_path required")

    async def progress_callback(progress: dict):
        await broadcast_ws({"type": "flash_progress", **progress})

    asyncio.create_task(
        esp_flasher.flash_serial(port, firmware_path, chip, erase_first, progress_callback)
    )
    return {"success": True, "message": "Serial Flash gestartet"}


@app.post("/api/flash/backup")
async def backup_flash(data: dict):
    """Backup current firmware via serial."""
    port = data.get("port", "")
    chip = data.get("chip", "esp32")

    async def progress_callback(progress: dict):
        await broadcast_ws({"type": "backup_progress", **progress})

    result = await esp_flasher.backup(port, chip, progress_callback)
    return result


@app.post("/api/flash/restore")
async def restore_flash(data: dict):
    """Restore a backed up firmware via serial."""
    port = data.get("port", "")
    backup_path = data.get("backup_path", "")
    chip = data.get("chip", "esp32")

    async def progress_callback(progress: dict):
        await broadcast_ws({"type": "restore_progress", **progress})

    asyncio.create_task(
        esp_flasher.restore(port, backup_path, chip, progress_callback)
    )
    return {"success": True, "message": "Restore gestartet"}


@app.get("/api/flash/check-version/{device_ip:path}")
async def check_device_version(device_ip: str):
    """Check WLED version on a device via WiFi."""
    info = await esp_flasher.check_device_version(device_ip)
    if info:
        return info
    raise HTTPException(404, "Gerät nicht erreichbar")


@app.post("/api/flash/upload-firmware")
async def upload_firmware(file: UploadFile = File(...)):
    """Upload a custom firmware binary."""
    firmware_dir = Path("firmware")
    firmware_dir.mkdir(exist_ok=True)
    path = firmware_dir / file.filename
    with open(path, "wb") as f:
        content = await file.read()
        f.write(content)
    return {"success": True, "path": str(path), "filename": file.filename}


# ─── Presets & Profiles ──────────────────────────────────────────────────────

@app.get("/api/presets")
async def get_presets():
    """Get all saved presets."""
    return {"presets": config_manager.get("presets", [])}


@app.post("/api/presets")
async def save_preset(data: dict):
    """Save a new preset."""
    presets = config_manager.get("presets", [])
    presets.append(data)
    config_manager.set("presets", presets)
    config_manager.save()
    return {"success": True}


@app.delete("/api/presets/{index}")
async def delete_preset(index: int):
    """Delete a preset by index."""
    presets = config_manager.get("presets", [])
    if 0 <= index < len(presets):
        presets.pop(index)
        config_manager.set("presets", presets)
        config_manager.save()
        return {"success": True}
    raise HTTPException(404, "Preset not found")


@app.post("/api/presets/{index}/apply")
async def apply_preset(index: int):
    """Apply a preset to its target devices."""
    presets = config_manager.get("presets", [])
    if 0 <= index < len(presets):
        preset = presets[index]
        for device_config in preset.get("devices", []):
            device_id = device_config.get("device_id")
            state = device_config.get("state", {})
            await device_manager.set_device_state(device_id, state)
        return {"success": True}
    raise HTTPException(404, "Preset not found")


# ─── Profiles (Szenen) ────────────────────────────────────────────────────────

@app.get("/api/profiles")
async def get_profiles():
    """Get all saved profiles and the active one."""
    profiles = config_manager.get("profiles_list", [
        {"id": "default", "name": "Standard", "icon": "🎯", "description": "Voreingestelltes Profil"},
        {"id": "tournament", "name": "Turnier", "icon": "🏆", "description": "Dezent, nur Score-Highlights"},
        {"id": "party", "name": "Party", "icon": "🎉", "description": "Alles bunt und laut"},
        {"id": "training", "name": "Training", "icon": "📊", "description": "Nur Checkout-Hinweise"},
    ])
    active = config_manager.get("active_profile", "default")
    return {"profiles": profiles, "active": active}


@app.post("/api/profiles/activate")
async def activate_profile(data: dict):
    """Switch the active profile. Loads that profile's event mappings."""
    profile_id = data.get("id", "default")
    config_manager.set("active_profile", profile_id)
    profile_events = config_manager.get(f"profile_events_{profile_id}", None)
    if profile_events:
        config_manager.set("event_mappings", profile_events)
    config_manager.save()
    autodarts_client.reload_mappings()
    return {"success": True, "active": profile_id}


@app.post("/api/profiles/save")
async def save_profile(data: dict):
    """Save current event config to a profile."""
    profile_id = data.get("id", "")
    current_events = config_manager.get("event_mappings", {})
    config_manager.set(f"profile_events_{profile_id}", current_events)
    profiles = config_manager.get("profiles_list", [])
    existing = next((p for p in profiles if p["id"] == profile_id), None)
    if existing:
        existing.update({k: data[k] for k in ("name", "icon", "description") if k in data})
    else:
        profiles.append({
            "id": profile_id, "name": data.get("name", profile_id),
            "icon": data.get("icon", "🎯"), "description": data.get("description", ""),
        })
    config_manager.set("profiles_list", profiles)
    config_manager.save()
    return {"success": True}


@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """Delete a profile."""
    if profile_id == "default":
        raise HTTPException(400, "Standard-Profil kann nicht geloescht werden")
    profiles = config_manager.get("profiles_list", [])
    profiles = [p for p in profiles if p["id"] != profile_id]
    config_manager.set("profiles_list", profiles)
    if config_manager.get("active_profile") == profile_id:
        config_manager.set("active_profile", "default")
    config_manager.save()
    return {"success": True}


# ─── Player Colors ────────────────────────────────────────────────────────────

@app.get("/api/player-colors")
async def get_player_colors():
    """Get player color configuration."""
    default_colors = {
        "enabled": True,
        "mode": "turn",
        "players": [
            {"name": "Spieler 1", "color": [0, 120, 255], "enabled": True},
            {"name": "Spieler 2", "color": [255, 50, 0], "enabled": True},
            {"name": "Spieler 3", "color": [0, 200, 80], "enabled": True},
            {"name": "Spieler 4", "color": [255, 200, 0], "enabled": True},
        ],
        "brightness": 100, "effect_fx": 0,
    }
    return config_manager.get("player_colors", default_colors)


@app.post("/api/player-colors")
async def set_player_colors(data: dict):
    config_manager.set("player_colors", data)
    config_manager.save()
    return {"success": True}


# ─── Segment Zones ────────────────────────────────────────────────────────────

@app.get("/api/segments")
async def get_segment_zones():
    """Get segment zone configuration (percent-based for any LED count)."""
    default = {
        "enabled": False,
        "zones": [
            {"name": "Oben", "start_pct": 0, "end_pct": 25, "color": [255, 255, 255]},
            {"name": "Rechts", "start_pct": 25, "end_pct": 50, "color": [255, 255, 255]},
            {"name": "Unten", "start_pct": 50, "end_pct": 75, "color": [255, 255, 255]},
            {"name": "Links", "start_pct": 75, "end_pct": 100, "color": [255, 255, 255]},
        ],
    }
    return config_manager.get("segment_zones", default)


@app.post("/api/segments")
async def set_segment_zones(data: dict):
    config_manager.set("segment_zones", data)
    config_manager.save()
    return {"success": True}


# ─── Brightness Schedule ──────────────────────────────────────────────────────

@app.get("/api/schedule")
async def get_schedule():
    default = {
        "enabled": False,
        "entries": [
            {"time": "08:00", "brightness": 200, "label": "Morgens"},
            {"time": "18:00", "brightness": 255, "label": "Spielzeit"},
            {"time": "22:00", "brightness": 80, "label": "Nachtmodus"},
            {"time": "00:00", "brightness": 30, "label": "Spaet nachts"},
        ],
        "transition_minutes": 5,
    }
    return config_manager.get("brightness_schedule", default)


@app.post("/api/schedule")
async def set_schedule(data: dict):
    config_manager.set("brightness_schedule", data)
    config_manager.save()
    return {"success": True}


# ─── Favorite Effects ─────────────────────────────────────────────────────────

@app.get("/api/favorites")
async def get_favorites():
    return {"favorites": config_manager.get("favorite_effects", [])}


@app.post("/api/favorites")
async def save_favorite(data: dict):
    favorites = config_manager.get("favorite_effects", [])
    fav = {
        "id": data.get("id", f"fav_{len(favorites)+1}_{int(__import__('time').time())}"),
        "name": data.get("name", "Mein Effekt"),
        "effect": data.get("effect", {}),
        "duration": data.get("duration", 2.0),
    }
    existing_idx = next((i for i, f in enumerate(favorites) if f["id"] == fav["id"]), None)
    if existing_idx is not None:
        favorites[existing_idx] = fav
    else:
        favorites.append(fav)
    config_manager.set("favorite_effects", favorites)
    config_manager.save()
    return {"success": True, "favorite": fav}


@app.delete("/api/favorites/{fav_id}")
async def delete_favorite(fav_id: str):
    favorites = config_manager.get("favorite_effects", [])
    favorites = [f for f in favorites if f.get("id") != fav_id]
    config_manager.set("favorite_effects", favorites)
    config_manager.save()
    return {"success": True}


# ─── Configuration ────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    """Get full application configuration."""
    cfg = config_manager.get_all()
    # Mask sensitive fields in boards
    if "boards" in cfg:
        for board in cfg["boards"]:
            if "account_password" in board:
                board["password_set"] = bool(board["account_password"])
                del board["account_password"]
            if "api_key" in board:
                del board["api_key"]
    # Legacy: mask old autodarts api_key
    if "autodarts" in cfg and "api_key" in cfg["autodarts"]:
        cfg["autodarts"]["api_key_set"] = bool(cfg["autodarts"]["api_key"])
        cfg["autodarts"]["api_key"] = "***" if cfg["autodarts"]["api_key"] else ""
    return cfg


@app.post("/api/config")
async def set_config(data: dict):
    """Update application configuration."""
    for key, value in data.items():
        config_manager.set(key, value)
    config_manager.save()
    return {"success": True}


@app.post("/api/config/export")
async def export_config():
    """Export full configuration as JSON."""
    return config_manager.get_all()


@app.post("/api/config/import")
async def import_config(data: dict):
    """Import configuration from JSON."""
    config_manager.import_config(data)
    return {"success": True}


# ─── Caller / Sound System ────────────────────────────────────────────────────
# SOUNDS_DIR imported from paths.py

@app.get("/api/caller/config")
async def get_caller_config():
    """Get caller configuration and settings."""
    cfg = config_manager.get("caller_config", {})
    # Merge with defaults
    result = {**DEFAULT_CALLER_CONFIG, **cfg}
    return result


@app.post("/api/caller/config")
async def set_caller_config(data: dict):
    """Update caller configuration."""
    cfg = config_manager.get("caller_config", {})
    cfg.update(data)
    config_manager.set("caller_config", cfg)
    config_manager.save()
    return {"success": True}


@app.get("/api/caller/sounds")
async def get_caller_sounds():
    """Get all caller sound events with their assignments."""
    saved = config_manager.get("caller_sounds", {})
    merged = get_merged_caller(saved)
    return {
        "sounds": merged,
        "categories": CALLER_CATEGORIES,
    }


@app.post("/api/caller/sounds")
async def set_caller_sounds(data: dict):
    """Update caller sound assignments. Accepts partial updates."""
    saved = config_manager.get("caller_sounds", {})
    for key, val in data.items():
        if key.startswith("caller_") and isinstance(val, dict):
            if key not in saved:
                saved[key] = {}
            saved[key].update(val)
    config_manager.set("caller_sounds", saved)
    config_manager.save()
    return {"success": True}


@app.post("/api/caller/sounds/bulk")
async def bulk_set_caller_sounds(data: dict):
    """Bulk update caller sound assignments."""
    event_keys = data.get("events", [])
    updates = data.get("updates", {})
    saved = config_manager.get("caller_sounds", {})
    count = 0
    for key in event_keys:
        if key not in saved:
            saved[key] = {}
        saved[key].update(updates)
        count += 1
    config_manager.set("caller_sounds", saved)
    config_manager.save()
    return {"success": True, "updated": count}


@app.post("/api/caller/upload")
async def upload_caller_sound(file: UploadFile = File(...)):
    """Upload a sound file (.mp3, .wav, .ogg, .m4a)."""
    SOUNDS_DIR.mkdir(exist_ok=True)
    allowed = {".mp3", ".wav", ".ogg", ".m4a", ".webm", ".flac"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Nicht erlaubt: {ext}. Erlaubt: {', '.join(allowed)}")
    # Sanitize filename
    import re
    safe_name = re.sub(r'[^\w\-.]', '_', file.filename)
    dest = SOUNDS_DIR / safe_name
    # Avoid overwrite: add counter
    counter = 1
    while dest.exists():
        stem = Path(safe_name).stem
        dest = SOUNDS_DIR / f"{stem}_{counter}{ext}"
        counter += 1
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(400, "Datei zu groß (max. 10MB)")
    with open(dest, "wb") as f:
        f.write(content)
    logger.info(f"Sound uploaded: {dest.name} ({len(content)} bytes)")
    return {"success": True, "filename": dest.name, "size": len(content)}


@app.get("/api/caller/files")
async def list_caller_files():
    """List all uploaded sound files."""
    SOUNDS_DIR.mkdir(exist_ok=True)
    files = []
    for f in sorted(SOUNDS_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in {".mp3", ".wav", ".ogg", ".m4a", ".webm", ".flac"}:
            files.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "ext": f.suffix.lower(),
            })
    return {"files": files}


@app.delete("/api/caller/files/{filename}")
async def delete_caller_file(filename: str):
    """Delete an uploaded sound file."""
    filepath = SOUNDS_DIR / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    filepath.unlink()
    logger.info(f"Sound deleted: {filename}")
    return {"success": True}


@app.get("/sounds/{filename}")
async def serve_sound_file(filename: str):
    """Serve a sound file for playback."""
    filepath = SOUNDS_DIR / filename
    if not filepath.exists():
        raise HTTPException(404, "Sound not found")
    media_types = {
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
        ".m4a": "audio/mp4", ".webm": "audio/webm", ".flac": "audio/flac",
    }
    mt = media_types.get(filepath.suffix.lower(), "application/octet-stream")
    return FileResponse(filepath, media_type=mt)


@app.post("/api/caller/test")
async def test_caller_sound(data: dict):
    """Test-play a caller sound by broadcasting to connected clients."""
    sound_key = data.get("key", "")
    if not sound_key:
        raise HTTPException(400, "key required")
    saved = config_manager.get("caller_sounds", {})
    merged = get_merged_caller(saved)
    sound_entry = merged.get(sound_key, {})
    if not sound_entry.get("sound"):
        raise HTTPException(404, f"Kein Sound zugewiesen für {sound_key}")
    vol = config_manager.get("caller_config", {}).get("volume", 0.8)
    entry_vol = sound_entry.get("volume", 1.0)
    await broadcast_ws({
        "type": "caller_play",
        "sounds": [{"key": sound_key, "sound": sound_entry["sound"], "volume": entry_vol}],
        "event": "test",
        "data": {},
        "volume": vol,
    })
    return {"success": True, "playing": sound_key}


@app.post("/api/caller/test-scenario")
async def test_caller_scenario(data: dict):
    """Simulate a full game event through the real caller pipeline.
    This uses the same _determine_caller_sounds logic as the live system,
    then sends through broadcast_caller_sound for proper filtering + playback.
    """
    scenario = data.get("scenario", "")
    params = data.get("params", {})

    # Build the sound list exactly like autodarts_client._determine_caller_sounds
    sounds = []

    if scenario == "throw":
        number = params.get("number", 20)
        multiplier = params.get("multiplier", 1)
        ring = params.get("ring", "")
        dart_score = number * multiplier
        if multiplier == 2 and number == 25:
            field_key, effect_key, generic_key = "caller_bullseye", "caller_effect_bullseye", "caller_double"
        elif number == 25 and multiplier == 1:
            field_key, effect_key, generic_key = "caller_bull", "caller_effect_bull", "caller_single"
        elif dart_score == 0 or ring == "Miss":
            field_key, effect_key, generic_key = "caller_miss", "caller_effect_miss", None
        else:
            prefix = {1: "s", 2: "d", 3: "t"}.get(multiplier, "s")
            field_key = f"caller_{prefix}{number}"
            effect_key = f"caller_effect_{prefix}{number}"
            gen_name = {1: "single", 2: "double", 3: "triple"}.get(multiplier, "single")
            generic_key = f"caller_{gen_name}"

        sounds.append({"key": field_key, "priority": 1, "type": "dart_name"})
        if generic_key:
            sounds.append({"key": generic_key, "priority": 2, "type": "dart_name_fallback"})
        sounds.append({"key": effect_key, "priority": 1, "type": "dart_effect"})
        if generic_key:
            gen_effect = f"caller_effect_{generic_key.split('_')[-1]}"
            sounds.append({"key": gen_effect, "priority": 2, "type": "dart_effect_fallback"})
        if dart_score >= 0:
            sounds.append({"key": f"caller_score_{min(dart_score, 180)}", "priority": 1, "type": "dart_score"})

    elif scenario == "round_score":
        score = params.get("score", 60)
        score_key = f"caller_score_{min(score, 180)}"
        sounds.append({"key": score_key, "priority": 1})
        if score >= 180:
            sounds.append({"key": "caller_ambient_180", "priority": 2})
        elif score >= 140:
            sounds.append({"key": "caller_ambient_140_plus", "priority": 2})
        elif score >= 100:
            sounds.append({"key": "caller_ambient_ton_plus", "priority": 2})
        elif score == 26:
            sounds.append({"key": "caller_ambient_score_26", "priority": 2})
        elif 0 < score < 20:
            sounds.append({"key": "caller_ambient_low_score", "priority": 2})
        elif score == 0:
            sounds.append({"key": "caller_ambient_score_0", "priority": 2})
        sounds.append({"key": "caller_player_change", "priority": 3})

    elif scenario == "game_on":
        sounds.append({"key": "caller_game_on", "priority": 1})

    elif scenario == "game_won":
        sounds.append({"key": "caller_game_won", "priority": 1})
        sounds.append({"key": "caller_ambient_gameshot", "priority": 2})

    elif scenario == "match_won":
        sounds.append({"key": "caller_match_won", "priority": 1})
        sounds.append({"key": "caller_ambient_matchshot", "priority": 2})

    elif scenario == "busted":
        sounds.append({"key": "caller_busted", "priority": 1})
        sounds.append({"key": "caller_ambient_busted", "priority": 2})

    elif scenario == "checkout":
        rest = params.get("rest", 170)
        sounds.append({"key": "caller_you_require", "priority": 1})
        sounds.append({"key": f"caller_checkout_{min(max(rest, 2), 170)}", "priority": 2})
        sounds.append({"key": "caller_ambient_checkout_possible", "priority": 3})

    elif scenario == "board_takeout":
        sounds.append({"key": "caller_takeout", "priority": 1})

    elif scenario == "board_ready":
        sounds.append({"key": "caller_board_ready", "priority": 1})

    else:
        raise HTTPException(400, f"Unbekanntes Szenario: {scenario}")

    if not sounds:
        return {"success": False, "message": "Keine Sounds für dieses Szenario"}

    # Map scenario to event_name for broadcast_caller_sound filtering
    event_map = {
        "throw": "throw", "round_score": "player_change",
        "game_on": "game_on", "game_won": "game_won", "match_won": "match_won",
        "busted": "busted", "checkout": "checkout_possible",
        "board_takeout": "board_event", "board_ready": "board_event",
    }
    event_name = event_map.get(scenario, scenario)

    # Send through real pipeline (respects enabled, mode, filters)
    await broadcast_caller_sound(sounds, event_name, params)

    return {
        "success": True,
        "scenario": scenario,
        "event_name": event_name,
        "sounds_sent": [s["key"] for s in sounds],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# UPDATE SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/update/status")
async def api_update_status():
    """Get current update system status and local version."""
    return get_update_status()


@app.get("/api/update/check")
async def api_update_check():
    """Check if a newer version is available."""
    manifest_url = config_manager.get("update_manifest_url", DEFAULT_MANIFEST_URL)
    result = await check_for_update(manifest_url)
    return result


@app.post("/api/update/download")
async def api_update_download():
    """Download and stage the latest update."""
    manifest_url = config_manager.get("update_manifest_url", DEFAULT_MANIFEST_URL)
    info = await check_for_update(manifest_url)
    if not info.get("available"):
        return {"success": False, "message": "Kein Update verfügbar", "info": info}
    download_url = info.get("download_url")
    if not download_url:
        raise HTTPException(400, "Keine Download-URL im Manifest")

    # Progress via WebSocket
    async def progress_cb(pct, downloaded, total):
        await broadcast_ws({
            "type": "update_progress",
            "percent": pct,
            "downloaded": downloaded,
            "total": total,
        })

    result = await download_and_stage(download_url, progress_callback=progress_cb)
    if result.get("success"):
        await broadcast_ws({"type": "update_staged", "version": result.get("staged_version")})
    return result


@app.post("/api/update/install")
async def api_update_install():
    """Apply staged update and restart server."""
    status = get_update_status()
    if not status.get("update_staged"):
        raise HTTPException(400, "Kein Update zum Installieren bereit")

    # Signal restart
    trigger_restart()

    await broadcast_ws({
        "type": "update_restarting",
        "message": "Server startet neu mit Update...",
        "version": status.get("staged_version"),
    })

    # Give WebSocket time to deliver the message
    await asyncio.sleep(1)

    logger.info("Update install requested — triggering server shutdown for restart")

    # Graceful shutdown
    import signal
    os.kill(os.getpid(), signal.SIGTERM)

    return {"success": True, "message": "Server startet neu..."}


@app.post("/api/update/rollback")
async def api_update_rollback():
    """Rollback to previous version from backup."""
    result = rollback_update()
    if result.get("success"):
        trigger_restart()
        await asyncio.sleep(0.5)
        import signal
        os.kill(os.getpid(), signal.SIGTERM)
    return result


@app.post("/api/update/config")
async def api_update_config(data: dict):
    """Update the manifest URL and auto-check settings."""
    if "manifest_url" in data:
        config_manager.set("update_manifest_url", data["manifest_url"])
    if "auto_check" in data:
        config_manager.set("update_auto_check", data["auto_check"])
    if "auto_check_interval" in data:
        config_manager.set("update_auto_check_interval", data["auto_check_interval"])
    config_manager.save()
    return {"success": True}


@app.get("/api/update/config")
async def api_get_update_config():
    """Get update configuration."""
    return {
        "manifest_url": config_manager.get("update_manifest_url", DEFAULT_MANIFEST_URL),
        "auto_check": config_manager.get("update_auto_check", True),
        "auto_check_interval": config_manager.get("update_auto_check_interval", 3600),
    }


# ─── Module System ───────────────────────────────────────────────────────────

@app.get("/api/modules")
async def get_modules():
    """Get all modules with version, status, and description."""
    caller_cfg = config_manager.get("caller_config", {})
    boards = config_manager.get("boards", [])
    board_statuses = autodarts_client.get_all_boards_status()
    any_connected = autodarts_client.connected
    devices = await device_manager.get_all_devices()
    online_devices = [d for d in devices if d.get("online")]
    events_cfg = config_manager.get("event_mappings_custom", {})
    merged_events = get_merged_events(events_cfg)
    enabled_events = sum(1 for e in merged_events.values() if e.get("enabled"))

    return {"modules": [
        {
            "id": "autodarts",
            "name": "Autodarts Connector",
            "icon": "◎",
            "version": AUTODARTS_VERSION,
            "description": "WebSocket-Verbindung zu Autodarts Boards",
            "running": any_connected,
            "can_toggle": True,
            "detail": f"{len([b for b in board_statuses if b.get('connected')])}/"
                      f"{len(boards)} Boards verbunden",
        },
        {
            "id": "wled",
            "name": "WLED Controller",
            "icon": "◆",
            "version": DEVICE_MGR_VERSION,
            "sub_version": WLED_VERSION,
            "description": "LED-Strip Steuerung über WLED-Geräte",
            "running": len(online_devices) > 0,
            "can_toggle": True,
            "detail": f"{len(online_devices)}/{len(devices)} Geräte online",
        },
        {
            "id": "caller",
            "name": "Caller System",
            "icon": "🎙",
            "version": CALLER_VERSION,
            "description": "Score-Ansagen und Sound-Effekte",
            "running": caller_cfg.get("enabled", False),
            "can_toggle": True,
            "detail": "Aktiv" if caller_cfg.get("enabled", False) else "Deaktiviert",
        },
        {
            "id": "events",
            "name": "LED Event-Trigger",
            "icon": "⚡",
            "version": EVENTS_VERSION,
            "description": "Dart-Events → LED-Effekte zuordnen",
            "running": any_connected and enabled_events > 0,
            "can_toggle": False,
            "detail": f"{enabled_events} Events aktiv",
        },
        {
            "id": "updater",
            "name": "Auto-Updater",
            "icon": "🔄",
            "version": UPDATER_VERSION,
            "description": "Automatische Updates von GitHub",
            "running": config_manager.get("update_auto_check", True),
            "can_toggle": True,
            "detail": f"v{get_local_version()} installiert",
        },
        {
            "id": "flasher",
            "name": "Firmware Flasher",
            "icon": "↯",
            "version": FLASHER_VERSION,
            "description": "WLED Firmware auf ESP flashen",
            "running": True,
            "can_toggle": False,
            "detail": "Bereit",
        },
    ]}


@app.post("/api/modules/{module_id}/toggle")
async def toggle_module(module_id: str):
    """Start or stop a module."""
    if module_id == "autodarts":
        if autodarts_client.connected:
            await autodarts_client.disconnect()
            return {"running": False, "detail": "Getrennt"}
        else:
            boards = config_manager.get("boards", [])
            if not boards:
                raise HTTPException(400, "Keine Boards konfiguriert")
            asyncio.create_task(autodarts_client.connect_all())
            return {"running": True, "detail": "Verbinde..."}

    elif module_id == "wled":
        # Toggle device manager polling
        if device_manager._poll_task and not device_manager._poll_task.done():
            await device_manager.stop()
            return {"running": False, "detail": "Gestoppt"}
        else:
            await device_manager.start()
            return {"running": True, "detail": "Gestartet"}

    elif module_id == "caller":
        caller_cfg = config_manager.get("caller_config", {})
        new_state = not caller_cfg.get("enabled", False)
        caller_cfg["enabled"] = new_state
        config_manager.set("caller_config", caller_cfg)
        config_manager.save()
        return {"running": new_state, "detail": "Aktiv" if new_state else "Deaktiviert"}

    elif module_id == "updater":
        new_state = not config_manager.get("update_auto_check", True)
        config_manager.set("update_auto_check", new_state)
        config_manager.save()
        return {"running": new_state, "detail": "Auto-Check aktiv" if new_state else "Deaktiviert"}

    else:
        raise HTTPException(400, f"Modul '{module_id}' kann nicht umgeschaltet werden")


# ─── Serve Frontend ───────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    """Serve the main frontend."""
    if FRONTEND_HTML.exists():
        return HTMLResponse(FRONTEND_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)


def main():
    """Entry point — works both as Python script and PyInstaller binary."""
    import threading
    import webbrowser

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8420"))
    version = get_app_version()

    print()
    print("  ┌──────────────────────────────────┐")
    print(f"  │   THROWSYNC v{version:<20s}│")
    print("  │   WLED + Autodarts + Caller       │")
    print("  └──────────────────────────────────┘")
    print()

    if FROZEN:
        logger.info(f"Running as binary — Data dir: {DATA_DIR}")
    else:
        logger.info(f"Running as Python script — Project: {BUNDLE_DIR}")

    logger.info(f"Starting server on http://{host}:{port}")
    logger.info(f"Open http://localhost:{port} in your browser")

    # Open browser after short delay
    def open_browser():
        import time
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
