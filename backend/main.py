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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
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
from paths import FROZEN, BUNDLE_DIR, DATA_DIR, FRONTEND_HTML, DISPLAY_HTML, SOUNDS_DIR, CLIPS_DIR, FIRMWARE_DIR, get_version as get_app_version

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
    # Determine priority: critical events interrupt current playback
    priority = 0  # normal
    if event_name in ("match_won", "game_won", "game_on"):
        priority = 2  # critical — interrupt everything
    elif event_name in ("player_change", "busted", "checkout_possible"):
        priority = 1  # high — interrupt queue

    logger.debug(f"Caller play: {[r['key'] for r in resolved]} (priority={priority})")
    await broadcast_ws({
        "type": "caller_play",
        "sounds": resolved,
        "event": event_name,
        "data": data or {},
        "volume": global_vol,
        "priority": priority,
    })

    # Check for clip assignment on this event
    clip_assignments = config_manager.get("clip_assignments", {})
    clip_info = clip_assignments.get(event_name)
    if clip_info and clip_info.get("clip"):
        await broadcast_ws({
            "type": "caller_clip",
            "clip": clip_info["clip"],
            "clip_duration": clip_info.get("duration", 5),
            "event": event_name,
        })

    # ── Crowd Sound Engine ──
    crowd_cfg = config_manager.get("crowd_config", {})
    if crowd_cfg.get("enabled", False):
        from crowd_engine import get_crowd_reaction, CROWD_EVENTS
        score = data.get("round_score", 0) if data else 0
        crowd_keys = get_crowd_reaction(score, event_name)
        if crowd_keys:
            crowd_saved = config_manager.get("crowd_sounds", {})
            crowd_resolved = []
            for key in crowd_keys:
                meta = CROWD_EVENTS.get(key, {})
                entry = crowd_saved.get(key, {})
                sound_file = entry.get("sound", "")
                if sound_file:
                    crowd_resolved.append({
                        "key": key,
                        "sound": sound_file,
                        "volume": entry.get("volume", meta.get("default_volume", 0.5)),
                        "priority": 0,
                    })
            if crowd_resolved:
                crowd_vol = crowd_cfg.get("master_volume", 0.5)
                await broadcast_ws({
                    "type": "crowd_play",
                    "sounds": crowd_resolved,
                    "event": event_name,
                    "volume": crowd_vol,
                })

    # ── Twitch Chat ──
    twitch_cfg = config_manager.get("twitch_config", {})
    if twitch_cfg.get("enabled"):
        from twitch_obs import twitch_bot, format_alert
        if twitch_bot.connected:
            alerts = twitch_cfg.get("alerts", {})
            player = data.get("player_name", "") if data else ""
            score = data.get("round_score", 0) if data else 0
            template = alerts.get(event_name)
            if template:
                msg = format_alert(template, player, score)
                asyncio.create_task(twitch_bot.send_message(msg))

    # ── Discord Webhook ──
    discord_cfg = config_manager.get("discord_config", {})
    if discord_cfg.get("enabled") and discord_cfg.get("webhook_url"):
        from discord_bot import send_discord_webhook, build_event_embed
        should_post = False
        if event_name == "180" and discord_cfg.get("post_180", True):
            should_post = True
        elif event_name == "match_won" and discord_cfg.get("post_match_won", True):
            should_post = True
        elif event_name == "game_won" and discord_cfg.get("post_game_won", False):
            should_post = True
        elif event_name == "busted" and discord_cfg.get("post_busted", False):
            should_post = True
        elif event_name == "player_change" and discord_cfg.get("post_high_score", True):
            score = data.get("round_score", 0) if data else 0
            if score >= discord_cfg.get("min_high_score", 100):
                should_post = True
                event_name = "high_score"
        if should_post:
            player = data.get("player_name", "") if data else ""
            score = data.get("round_score", 0) if data else 0
            embed = build_event_embed(event_name, player, score)
            asyncio.create_task(send_discord_webhook(
                discord_cfg["webhook_url"], embed,
                discord_cfg.get("bot_name", "ThrowSync"),
                discord_cfg.get("avatar_url", ""),
            ))


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


app = FastAPI(title="ThrowSync", version="2.1.1", lifespan=lifespan)

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


# ─── Clips (Video/GIF Overlay) ──────────────────────────────────────────────

@app.get("/clips/{filename}")
async def serve_clip_file(filename: str):
    """Serve a video/GIF clip for overlay playback."""
    filepath = CLIPS_DIR / filename
    if not filepath.exists():
        raise HTTPException(404, "Clip not found")
    media_types = {
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".gif": "image/gif", ".png": "image/png", ".jpg": "image/jpeg",
    }
    mt = media_types.get(filepath.suffix.lower(), "application/octet-stream")
    return FileResponse(filepath, media_type=mt)


@app.get("/api/clips/files")
async def list_clip_files():
    """List all uploaded clip files."""
    CLIPS_DIR.mkdir(exist_ok=True)
    clips = []
    for f in sorted(CLIPS_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in ('.mp4', '.webm', '.mov', '.gif', '.png', '.jpg', '.jpeg'):
            clips.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "type": "video" if f.suffix.lower() in ('.mp4', '.webm', '.mov') else "image",
            })
    return {"files": clips}


@app.post("/api/clips/upload")
async def upload_clip(file: UploadFile = File(...)):
    """Upload a video/GIF clip."""
    CLIPS_DIR.mkdir(exist_ok=True)
    allowed = {'.mp4', '.webm', '.mov', '.gif', '.png', '.jpg', '.jpeg'}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Nicht erlaubt: {ext}. Erlaubt: {', '.join(allowed)}")
    safe_name = "".join(c for c in file.filename if c.isalnum() or c in '.-_')
    dest = CLIPS_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return {"success": True, "filename": safe_name, "size": len(content)}


@app.delete("/api/clips/files/{filename}")
async def delete_clip(filename: str):
    """Delete a clip file."""
    filepath = CLIPS_DIR / filename
    if not filepath.exists():
        raise HTTPException(404, "Clip not found")
    filepath.unlink()
    return {"success": True}


@app.get("/api/clips/assignments")
async def get_clip_assignments():
    """Get event → clip assignments."""
    return config_manager.get("clip_assignments", {})


@app.post("/api/clips/assignments")
async def save_clip_assignments(data: dict):
    """Save event → clip assignments. Format: {event_key: {clip: 'file.mp4', duration: 5}}"""
    config_manager.set("clip_assignments", data)
    config_manager.save()
    return {"success": True}


# ─── Crowd Sound Engine ──────────────────────────────────────────────────────

@app.get("/api/crowd/config")
async def get_crowd_config():
    """Get crowd engine configuration."""
    from crowd_engine import DEFAULT_CROWD_CONFIG
    cfg = config_manager.get("crowd_config", {})
    return {**DEFAULT_CROWD_CONFIG, **cfg}


@app.post("/api/crowd/config")
async def save_crowd_config(data: dict):
    """Save crowd engine configuration."""
    config_manager.set("crowd_config", data)
    config_manager.save()
    return {"success": True}


@app.get("/api/crowd/sounds")
async def get_crowd_sounds():
    """Get all crowd sound events with assignments."""
    from crowd_engine import CROWD_EVENTS
    saved = config_manager.get("crowd_sounds", {})
    result = {}
    for key, meta in CROWD_EVENTS.items():
        entry = saved.get(key, {})
        result[key] = {
            **meta,
            "sound": entry.get("sound", ""),
            "volume": entry.get("volume", meta.get("default_volume", 0.5)),
            "enabled": entry.get("enabled", True),
        }
    return {"sounds": result}


@app.post("/api/crowd/sounds")
async def save_crowd_sounds(data: dict):
    """Save crowd sound assignments."""
    config_manager.set("crowd_sounds", data)
    config_manager.save()
    return {"success": True}


@app.post("/api/crowd/test")
async def test_crowd_sound(data: dict):
    """Test a crowd sound by key."""
    key = data.get("key", "")
    saved = config_manager.get("crowd_sounds", {})
    entry = saved.get(key, {})
    if not entry.get("sound"):
        raise HTTPException(404, f"Kein Crowd-Sound für {key}")
    crowd_cfg = config_manager.get("crowd_config", {})
    vol = crowd_cfg.get("master_volume", 0.5)
    await broadcast_ws({
        "type": "crowd_play",
        "sounds": [{"key": key, "sound": entry["sound"], "volume": entry.get("volume", 0.5), "priority": 0}],
        "event": "test",
        "volume": vol,
    })
    return {"success": True}


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
    status = get_update_status()
    # Add network IPs
    import socket
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith('127.'):
                ips.append(ip)
        ips = list(dict.fromkeys(ips))  # dedupe, keep order
    except Exception:
        pass
    status["network_ips"] = ips
    return status


@app.get("/api/update/check")
async def api_update_check():
    """Check if a newer version is available."""
    manifest_url = config_manager.get("update_manifest_url", DEFAULT_MANIFEST_URL)
    result = await check_for_update(manifest_url)
    # Add network IPs
    import socket
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith('127.'):
                ips.append(ip)
        ips = list(dict.fromkeys(ips))
    except Exception:
        pass
    result["network_ips"] = ips
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


# ─── Display Overlay Test ─────────────────────────────────────────────────────

@app.get("/api/i18n/{lang}")
async def get_translations(lang: str):
    """Get all translations for a language."""
    from i18n import get_all_translations, LANGUAGES
    if lang not in LANGUAGES:
        lang = "de"
    return {"lang": lang, "translations": get_all_translations(lang)}


@app.get("/api/i18n")
async def get_i18n_info():
    """Get available languages and current setting."""
    from i18n import LANGUAGES
    current = config_manager.get("language", "de")
    return {"current": current, "languages": LANGUAGES}


@app.post("/api/i18n")
async def set_language(data: dict):
    """Set the UI language."""
    from i18n import LANGUAGES
    lang = data.get("language", "de")
    if lang not in LANGUAGES:
        raise HTTPException(400, f"Unknown language: {lang}")
    config_manager.set("language", lang)
    config_manager.save()
    return {"success": True, "language": lang}


# ─── Music Player ─────────────────────────────────────────────────────────────

@app.get("/music/{filename}")
async def serve_music(filename: str):
    """Serve a music file."""
    from paths import MUSIC_DIR
    path = MUSIC_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    ct_map = {'.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.ogg': 'audio/ogg',
              '.wav': 'audio/wav', '.flac': 'audio/flac', '.aac': 'audio/aac'}
    ct = ct_map.get(path.suffix.lower(), 'audio/mpeg')
    return FileResponse(path, media_type=ct)


@app.get("/api/music/files")
async def list_music_files():
    """List uploaded music files."""
    from paths import MUSIC_DIR
    exts = {'.mp3', '.m4a', '.ogg', '.wav', '.flac', '.aac'}
    files = []
    for f in sorted(MUSIC_DIR.iterdir()):
        if f.suffix.lower() in exts:
            files.append({"filename": f.name, "size": f.stat().st_size})
    return {"files": files}


@app.post("/api/music/upload")
async def upload_music(file: UploadFile):
    """Upload a music file."""
    from paths import MUSIC_DIR
    allowed = {'.mp3', '.m4a', '.ogg', '.wav', '.flac', '.aac'}
    ext = '.' + file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed:
        raise HTTPException(400, f"Ungültiges Format: {ext}")
    safe = "".join(c for c in file.filename if c.isalnum() or c in '.-_ ').strip()
    path = MUSIC_DIR / safe
    with open(path, 'wb') as f:
        content = await file.read()
        f.write(content)
    return {"success": True, "filename": safe, "size": len(content)}


@app.delete("/api/music/files/{filename}")
async def delete_music_file(filename: str):
    """Delete a music file."""
    from paths import MUSIC_DIR
    path = MUSIC_DIR / filename
    if path.exists():
        path.unlink()
    return {"success": True}


@app.get("/api/music/config")
async def get_music_config():
    """Get music player configuration."""
    return config_manager.get("music_config", {
        "volume": 0.3, "shuffle": False, "repeat": False,
        "duck_on_event": True, "duck_level": 0.1, "playlist": [],
    })


@app.post("/api/music/config")
async def save_music_config(data: dict):
    """Save music player configuration."""
    config_manager.set("music_config", data)
    config_manager.save()
    return {"success": True}


# ─── Player Profiles ─────────────────────────────────────────────────────────

@app.get("/api/profiles/players")
async def get_player_profiles():
    """Get all player profiles."""
    profiles = config_manager.get("player_profiles", [])
    active_id = config_manager.get("active_player", "")
    return {"profiles": profiles, "active": active_id}


@app.post("/api/profiles/players")
async def create_player_profile(data: dict):
    """Create a new player profile."""
    from player_profiles import create_profile
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Name required")
    avatar = data.get("avatar", "\U0001F3AF")
    profile = create_profile(name, avatar)
    profiles = config_manager.get("player_profiles", [])
    profiles.append(profile)
    config_manager.set("player_profiles", profiles)
    config_manager.save()
    return {"success": True, "profile": profile}


@app.put("/api/profiles/players/{profile_id}")
async def update_player_profile(profile_id: str, data: dict):
    """Update a player profile."""
    profiles = config_manager.get("player_profiles", [])
    for i, p in enumerate(profiles):
        if p.get("id") == profile_id:
            # Merge update data but keep stats and id
            stats = p.get("stats", {})
            profiles[i] = {**p, **data, "id": profile_id, "stats": stats}
            config_manager.set("player_profiles", profiles)
            config_manager.save()
            return {"success": True, "profile": profiles[i]}
    raise HTTPException(404, "Profile not found")


@app.delete("/api/profiles/players/{profile_id}")
async def delete_player_profile(profile_id: str):
    """Delete a player profile."""
    profiles = config_manager.get("player_profiles", [])
    profiles = [p for p in profiles if p.get("id") != profile_id]
    config_manager.set("player_profiles", profiles)
    config_manager.save()
    return {"success": True}


@app.post("/api/profiles/players/{profile_id}/activate")
async def activate_player_profile(profile_id: str):
    """Set the active player (triggers walk-on, LED theme switch)."""
    profiles = config_manager.get("player_profiles", [])
    profile = next((p for p in profiles if p.get("id") == profile_id), None)
    if not profile:
        raise HTTPException(404, "Profile not found")
    config_manager.set("active_player", profile_id)
    config_manager.save()
    # Broadcast player change to all clients
    await broadcast_ws({
        "type": "player_activated",
        "profile": profile,
    })
    # Play walk-on sound if assigned
    if profile.get("walk_on_sound"):
        await broadcast_ws({
            "type": "caller_play",
            "sounds": [{"key": "walk_on", "sound": profile["walk_on_sound"], "volume": 1.0, "priority": 2}],
            "event": "walk_on",
            "volume": config_manager.get("caller_config", {}).get("volume", 0.8),
            "priority": 2,
        })
    # Apply LED color if set
    if profile.get("led_color"):
        await broadcast_ws({
            "type": "player_led_theme",
            "color": profile["led_color"],
            "brightness": profile.get("led_brightness", 180),
            "effect": profile.get("led_effect", 0),
        })
    return {"success": True, "profile": profile}


@app.post("/api/profiles/players/{profile_id}/stats")
async def update_player_stats(profile_id: str, data: dict):
    """Update player stats with a game event."""
    from player_profiles import update_stats
    from achievements import check_achievements, get_achievement_info
    profiles = config_manager.get("player_profiles", [])
    for i, p in enumerate(profiles):
        if p.get("id") == profile_id:
            profiles[i] = update_stats(p, data.get("event", ""), data)
            # Check for new achievements
            unlocked = profiles[i].get("achievements", [])
            new_achs = check_achievements(profiles[i].get("stats", {}), unlocked)
            if new_achs:
                profiles[i]["achievements"] = unlocked + new_achs
                # Broadcast achievement unlocked
                for aid in new_achs:
                    info = get_achievement_info(aid)
                    if info:
                        await broadcast_ws({
                            "type": "achievement_unlocked",
                            "profile_id": profile_id,
                            "player_name": p.get("name", ""),
                            "achievement": info,
                        })
            config_manager.set("player_profiles", profiles)
            config_manager.save()
            return {"success": True, "stats": profiles[i].get("stats", {}), "new_achievements": new_achs}
    raise HTTPException(404, "Profile not found")


@app.post("/api/profiles/players/{profile_id}/reset-stats")
async def reset_player_stats(profile_id: str):
    """Reset player stats."""
    from player_profiles import empty_stats
    profiles = config_manager.get("player_profiles", [])
    for i, p in enumerate(profiles):
        if p.get("id") == profile_id:
            profiles[i]["stats"] = empty_stats()
            profiles[i]["achievements"] = []
            config_manager.set("player_profiles", profiles)
            config_manager.save()
            return {"success": True}
    raise HTTPException(404, "Profile not found")


# ─── Achievements ─────────────────────────────────────────────────────────────

@app.get("/api/achievements")
async def get_achievements():
    """Get all available achievements."""
    from achievements import get_all_achievements
    lang = config_manager.get("language", "de")
    return {"achievements": get_all_achievements(lang)}


@app.get("/api/achievements/{profile_id}")
async def get_player_achievements(profile_id: str):
    """Get achievements for a specific player."""
    from achievements import get_achievement_info
    profiles = config_manager.get("player_profiles", [])
    profile = next((p for p in profiles if p.get("id") == profile_id), None)
    if not profile:
        raise HTTPException(404, "Profile not found")
    unlocked = profile.get("achievements", [])
    lang = config_manager.get("language", "de")
    return {
        "unlocked": [get_achievement_info(aid, lang) for aid in unlocked if get_achievement_info(aid, lang)],
        "total": len(unlocked),
    }


# ─── Lobby Display ────────────────────────────────────────────────────────────

@app.get("/lobby")
async def serve_lobby():
    """Serve lobby/waiting screen page."""
    profiles = config_manager.get("player_profiles", [])
    lang = config_manager.get("language", "de")
    # Build player cards HTML
    player_html = ""
    for p in profiles:
        stats = p.get("stats", {})
        avg = stats.get("avg_score", 0)
        co_hit = stats.get("checkouts_hit", 0)
        co_miss = stats.get("checkouts_missed", 0)
        co_rate = f"{(co_hit/(co_hit+co_miss)*100):.0f}%" if (co_hit+co_miss) > 0 else "—"
        ach_count = len(p.get("achievements", []))
        player_html += f'''
        <div class="player" style="border-color:{p.get('led_color','#8b5cf6')}">
            <div class="avatar">{p.get('avatar','\U0001F3AF')}</div>
            <div class="name">{p.get('name','?')}</div>
            <div class="stats">
                <span>Avg: <b>{avg}</b></span>
                <span>180s: <b>{stats.get('total_180s',0)}</b></span>
                <span>C/O: <b>{co_rate}</b></span>
                <span>\U0001F3C6 {ach_count}</span>
            </div>
        </div>'''
    html = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>ThrowSync Lobby</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0f;color:#e2e2e8;font-family:system-ui,-apple-system,sans-serif;
display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;overflow:hidden}}
.logo{{font-size:48px;font-weight:900;letter-spacing:6px;margin-bottom:8px;
background:linear-gradient(135deg,#8b5cf6,#3b82f6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.subtitle{{color:#888;font-size:16px;margin-bottom:40px;letter-spacing:2px}}
.players{{display:flex;gap:24px;flex-wrap:wrap;justify-content:center;margin-bottom:40px}}
.player{{background:rgba(255,255,255,0.04);border:2px solid #8b5cf6;border-radius:16px;
padding:24px;min-width:200px;text-align:center;backdrop-filter:blur(10px);
animation:float 3s ease-in-out infinite}}
.player:nth-child(2){{animation-delay:0.5s}}.player:nth-child(3){{animation-delay:1s}}
.avatar{{font-size:48px;margin-bottom:8px}}
.name{{font-size:22px;font-weight:700;margin-bottom:8px}}
.stats{{display:flex;gap:12px;font-size:12px;color:#888;justify-content:center;flex-wrap:wrap}}
.stats b{{color:#e2e2e8}}
.waiting{{color:#555;font-size:14px;animation:pulse 2s ease-in-out infinite}}
@keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-8px)}}}}
@keyframes pulse{{0%,100%{{opacity:0.5}}50%{{opacity:1}}}}
.clock{{font-size:64px;font-weight:200;color:#333;font-variant-numeric:tabular-nums;margin-bottom:20px}}
</style>
<script>
setInterval(()=>{{const d=new Date();document.getElementById('clock').textContent=
d.toLocaleTimeString('de-DE',{{hour:'2-digit',minute:'2-digit'}})}},1000);
const ws=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/ws');
ws.onmessage=e=>{{const m=JSON.parse(e.data);
if(m.type==='game_started')location.reload();
if(m.type==='player_activated')location.reload()}};
</script></head><body>
<div id="clock" class="clock"></div>
<div class="logo">THROWSYNC</div>
<div class="subtitle">WAITING FOR GAME</div>
<div class="players">{player_html}</div>
<div class="waiting">\U0001F3AF Warte auf Spielbeginn...</div>
</body></html>'''
    return HTMLResponse(html)


# ─── Display Overlay Test (continued) ────────────────────────────────────────

@app.post("/api/display/test")
async def test_display_overlay(data: dict):
    """Send test events to all connected overlay/display clients."""
    event = data.get("event", "throw")

    if event == "throw":
        await broadcast_ws({"type": "display_state", "data": {
            "type": "throw", "throw_text": "T20", "points": 60, "turn_score": 60, "darts_in_turn": 1,
        }})
        await asyncio.sleep(0.5)
        await broadcast_ws({"type": "display_state", "data": {
            "type": "throw", "throw_text": "T19", "points": 57, "turn_score": 117, "darts_in_turn": 2,
        }})
        await asyncio.sleep(0.5)
        await broadcast_ws({"type": "display_state", "data": {
            "type": "throw", "throw_text": "T18", "points": 54, "turn_score": 171, "darts_in_turn": 3,
        }})
    elif event == "score_140":
        await broadcast_ws({"type": "display_state", "data": {
            "type": "throw", "throw_text": "T20", "points": 60, "turn_score": 140, "darts_in_turn": 3,
        }})
        await broadcast_ws({"type": "display_state", "data": {
            "type": "state_update", "remaining": 161, "scores": [161, 301],
        }})
    elif event == "180":
        await broadcast_ws({"type": "display_state", "data": {
            "type": "throw", "throw_text": "T20", "points": 60, "turn_score": 180, "darts_in_turn": 3,
        }})
        await broadcast_ws({"type": "event_fired", "entry": {"event": "180", "board": "test"}})
        # Also trigger clip if assigned
        clip_assignments = config_manager.get("clip_assignments", {})
        clip_info = clip_assignments.get("180")
        if clip_info and clip_info.get("clip"):
            await broadcast_ws({"type": "caller_clip", "clip": clip_info["clip"], "clip_duration": clip_info.get("duration", 5), "event": "180"})
    elif event == "bust":
        await broadcast_ws({"type": "display_state", "data": {
            "type": "throw", "throw_text": "S5", "points": 5, "turn_score": 5, "darts_in_turn": 1,
        }})
        await broadcast_ws({"type": "event_fired", "entry": {"event": "busted", "board": "test"}})
        clip_assignments = config_manager.get("clip_assignments", {})
        clip_info = clip_assignments.get("busted")
        if clip_info and clip_info.get("clip"):
            await broadcast_ws({"type": "caller_clip", "clip": clip_info["clip"], "clip_duration": clip_info.get("duration", 5), "event": "busted"})
    elif event == "game_won":
        await broadcast_ws({"type": "display_state", "data": {
            "type": "throw", "throw_text": "D16", "points": 32, "turn_score": 32, "darts_in_turn": 3,
        }})
        await broadcast_ws({"type": "display_state", "data": {
            "type": "state_update", "remaining": 0, "scores": [0, 220],
        }})
        await broadcast_ws({"type": "event_fired", "entry": {"event": "game_won", "board": "test"}})
        clip_assignments = config_manager.get("clip_assignments", {})
        clip_info = clip_assignments.get("game_won")
        if clip_info and clip_info.get("clip"):
            await broadcast_ws({"type": "caller_clip", "clip": clip_info["clip"], "clip_duration": clip_info.get("duration", 5), "event": "game_won"})
    elif event == "match_won":
        await broadcast_ws({"type": "display_state", "data": {
            "type": "state_update", "remaining": 0, "scores": [0, 180],
        }})
        await broadcast_ws({"type": "event_fired", "entry": {"event": "match_won", "board": "test"}})
        clip_assignments = config_manager.get("clip_assignments", {})
        clip_info = clip_assignments.get("match_won")
        if clip_info and clip_info.get("clip"):
            await broadcast_ws({"type": "caller_clip", "clip": clip_info["clip"], "clip_duration": clip_info.get("duration", 5), "event": "match_won"})

    return {"success": True, "event": event}


# ─── LED Animation Designer ───────────────────────────────────────────────────

@app.get("/api/led-designer/animations")
async def get_animations():
    """Get all custom + preset animations."""
    from led_designer import PRESET_ANIMATIONS
    custom = config_manager.get("custom_animations", [])
    return {"presets": PRESET_ANIMATIONS, "custom": custom}


@app.post("/api/led-designer/animations")
async def save_animation(data: dict):
    """Create or update a custom animation."""
    from led_designer import create_animation
    custom = config_manager.get("custom_animations", [])
    anim_id = data.get("id")
    if anim_id:
        # Update existing
        for i, a in enumerate(custom):
            if a.get("id") == anim_id:
                custom[i] = {**a, **data}
                break
        else:
            custom.append(data)
    else:
        # New animation
        anim = create_animation(data.get("name", "Neue Animation"), data.get("led_count", 30))
        anim.update(data)
        data = anim
        custom.append(data)
    config_manager.set("custom_animations", custom)
    config_manager.save()
    return {"success": True, "animation": data}


@app.delete("/api/led-designer/animations/{anim_id}")
async def delete_animation(anim_id: str):
    """Delete a custom animation."""
    custom = config_manager.get("custom_animations", [])
    custom = [a for a in custom if a.get("id") != anim_id]
    config_manager.set("custom_animations", custom)
    config_manager.save()
    return {"success": True}


@app.post("/api/led-designer/preview")
async def preview_animation(data: dict):
    """Preview an animation on all devices by broadcasting frames."""
    from led_designer import generate_wled_payload
    animation = data.get("animation", {})
    if not animation.get("frames"):
        raise HTTPException(400, "No frames in animation")
    duration = animation.get("duration", 2000)
    steps = min(20, max(5, duration // 100))  # 5-20 steps
    for step in range(steps):
        t = int((step / steps) * duration)
        payload = generate_wled_payload(animation, t)
        if payload:
            # Send to all devices
            devices = config_manager.get("devices", [])
            for dev in devices:
                try:
                    await device_manager.send_wled_json(dev.get("id", ""), payload)
                except Exception:
                    pass
        await asyncio.sleep(duration / steps / 1000)
    return {"success": True}


# ─── Twitch Integration ──────────────────────────────────────────────────────

@app.get("/api/twitch/config")
async def get_twitch_config():
    """Get Twitch configuration (without oauth token)."""
    from twitch_obs import DEFAULT_TWITCH_CONFIG
    cfg = config_manager.get("twitch_config", {})
    result = {**DEFAULT_TWITCH_CONFIG, **cfg}
    # Don't expose full token
    if result.get("oauth_token"):
        result["oauth_token"] = "****" + result["oauth_token"][-4:] if len(result["oauth_token"]) > 4 else "****"
        result["has_token"] = True
    else:
        result["has_token"] = False
    return result


@app.post("/api/twitch/config")
async def save_twitch_config(data: dict):
    """Save Twitch configuration."""
    # Don't overwrite token if masked
    if data.get("oauth_token", "").startswith("****"):
        existing = config_manager.get("twitch_config", {})
        data["oauth_token"] = existing.get("oauth_token", "")
    config_manager.set("twitch_config", data)
    config_manager.save()
    return {"success": True}


@app.post("/api/twitch/connect")
async def twitch_connect():
    """Connect the Twitch bot."""
    from twitch_obs import twitch_bot
    cfg = config_manager.get("twitch_config", {})
    if not cfg.get("channel") or not cfg.get("oauth_token"):
        raise HTTPException(400, "Channel und OAuth Token erforderlich")
    ok = await twitch_bot.connect(cfg["channel"], cfg["oauth_token"], cfg.get("bot_name", "ThrowSyncBot"))
    return {"success": ok, "connected": twitch_bot.connected}


@app.post("/api/twitch/disconnect")
async def twitch_disconnect():
    """Disconnect the Twitch bot."""
    from twitch_obs import twitch_bot
    await twitch_bot.disconnect()
    return {"success": True}


@app.get("/api/twitch/status")
async def twitch_status():
    """Get Twitch bot connection status."""
    from twitch_obs import twitch_bot
    return {"connected": twitch_bot.connected, "channel": twitch_bot.channel}


@app.post("/api/twitch/test")
async def twitch_test():
    """Send a test message to Twitch chat."""
    from twitch_obs import twitch_bot
    if not twitch_bot.connected:
        raise HTTPException(400, "Twitch bot nicht verbunden")
    ok = await twitch_bot.send_message("\U0001F3AF ThrowSync ist verbunden! Let's play darts! \U0001F525")
    return {"success": ok}


# ─── Discord Integration ─────────────────────────────────────────────────────

@app.get("/api/discord/config")
async def get_discord_config():
    """Get Discord configuration."""
    from discord_bot import DEFAULT_DISCORD_CONFIG
    cfg = config_manager.get("discord_config", {})
    result = {**DEFAULT_DISCORD_CONFIG, **cfg}
    # Mask webhook URL
    if result.get("webhook_url"):
        result["has_webhook"] = True
        url = result["webhook_url"]
        result["webhook_url_display"] = url[:40] + "..." if len(url) > 40 else url
    else:
        result["has_webhook"] = False
        result["webhook_url_display"] = ""
    return result


@app.post("/api/discord/config")
async def save_discord_config(data: dict):
    """Save Discord configuration."""
    config_manager.set("discord_config", data)
    config_manager.save()
    return {"success": True}


@app.post("/api/discord/test")
async def discord_test():
    """Send a test message to Discord."""
    from discord_bot import send_discord_webhook
    cfg = config_manager.get("discord_config", {})
    if not cfg.get("webhook_url"):
        raise HTTPException(400, "Kein Webhook konfiguriert")
    embed = {
        "title": "\U0001F3AF ThrowSync verbunden!",
        "description": "Discord-Integration ist aktiv. Game on!",
        "color": 0x8B5CF6,
        "footer": {"text": "ThrowSync \u2022 Dart Gaming Lightshow"},
    }
    ok = await send_discord_webhook(cfg["webhook_url"], embed, cfg.get("bot_name", "ThrowSync"), cfg.get("avatar_url", ""))
    return {"success": ok}


# ─── PWA Support ──────────────────────────────────────────────────────────────

@app.get("/manifest.json")
async def pwa_manifest():
    """Serve PWA manifest for installable app."""
    return JSONResponse({
        "name": "ThrowSync",
        "short_name": "ThrowSync",
        "description": "Dart Gaming Lightshow & Caller System",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0f",
        "theme_color": "#8b5cf6",
        "orientation": "any",
        "icons": [
            {"src": "/pwa-icon-192.svg", "sizes": "192x192", "type": "image/svg+xml"},
            {"src": "/pwa-icon-512.svg", "sizes": "512x512", "type": "image/svg+xml"},
        ],
    })


@app.get("/pwa-icon-192.svg")
@app.get("/pwa-icon-512.svg")
async def pwa_icon():
    """SVG icon for PWA."""
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
    <rect width="512" height="512" rx="64" fill="#0a0a0f"/>
    <circle cx="256" cy="256" r="180" fill="none" stroke="#8b5cf6" stroke-width="12"/>
    <circle cx="256" cy="256" r="120" fill="none" stroke="#3b82f6" stroke-width="8"/>
    <circle cx="256" cy="256" r="60" fill="none" stroke="#8b5cf6" stroke-width="6"/>
    <circle cx="256" cy="256" r="16" fill="#8b5cf6"/>
    <text x="256" y="440" text-anchor="middle" fill="#e2e2e8" font-family="system-ui" font-size="48" font-weight="900" letter-spacing="4">THROWSYNC</text>
    </svg>'''
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/sw.js")
async def service_worker():
    """Minimal service worker for PWA installability."""
    js = '''self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request).catch(() => new Response('Offline'))));'''
    return Response(content=js, media_type="application/javascript")


# ─── Serve Frontend ───────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    """Serve the main frontend."""
    if FRONTEND_HTML.exists():
        return HTMLResponse(FRONTEND_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)


@app.get("/display")
async def serve_display():
    """Serve the display overlay page (for second screen / OBS)."""
    if DISPLAY_HTML.exists():
        return HTMLResponse(DISPLAY_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Display page not found</h1>", status_code=404)


@app.get("/overlay.js")
async def serve_overlay_js(request: Request):
    """Serve the injectable overlay script with correct host."""
    js_path = FRONTEND_HTML.parent / "overlay.js"
    if not js_path.exists():
        raise HTTPException(404, "overlay.js not found")
    host = request.headers.get("host", "localhost:8420")
    js = js_path.read_text(encoding="utf-8")
    js = js.replace("__THROWSYNC_HOST__", host)
    return Response(content=js, media_type="application/javascript")


@app.get("/bookmarklet")
async def serve_bookmarklet(request: Request):
    """Serve bookmarklet setup page."""
    host = request.headers.get("host", "localhost:8420")
    html = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="UTF-8"><title>ThrowSync Bookmarklet</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, sans-serif; background: #0f0f1a; color: #e0e0e0; padding: 40px; line-height: 1.6; }}
    h1 {{ color: #8b5cf6; margin-bottom: 8px; }}
    .subtitle {{ color: #888; margin-bottom: 32px; }}
    .card {{ background: #1a1a2e; border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid #2a2a3e; }}
    .bookmarklet-link {{
        display: inline-block; padding: 14px 28px; margin: 16px 0;
        background: linear-gradient(135deg, #8b5cf6, #6d28d9); color: #fff;
        text-decoration: none; border-radius: 10px; font-size: 18px; font-weight: 700;
        box-shadow: 0 4px 20px rgba(139,92,246,0.3);
        cursor: grab; transition: transform 0.2s;
    }}
    .bookmarklet-link:hover {{ transform: scale(1.03); }}
    .step {{ display: flex; gap: 16px; margin: 16px 0; align-items: flex-start; }}
    .step-num {{ background: #8b5cf6; color: #fff; width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0; }}
    .step-text {{ padding-top: 4px; }}
    code {{ background: #2a2a3e; padding: 2px 8px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 13px; }}
    .preview {{ background: #000; border-radius: 8px; padding: 12px; margin-top: 16px; text-align: center; }}
    .preview-bar {{ display: inline-flex; gap: 16px; align-items: center; background: rgba(0,0,0,0.8); padding: 6px 16px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); }}
    .p-label {{ font-size: 10px; color: #888; text-transform: uppercase; }}
    .p-val {{ font-size: 18px; font-weight: 700; }}
    .p-score {{ color: #8b5cf6; }}
    .p-rest {{ color: #10b981; }}
    .p-throw {{ color: #f59e0b; }}
    .note {{ color: #888; font-size: 13px; margin-top: 8px; }}
</style></head><body>
    <h1>ThrowSync Overlay</h1>
    <p class="subtitle">1-Klick HUD + Clips direkt in Autodarts / Darthelfer</p>

    <div class="card">
        <h2>Bookmarklet installieren</h2>
        <div class="step">
            <div class="step-num">1</div>
            <div class="step-text">Zeige die <strong>Lesezeichen-Leiste</strong> an (Strg+Shift+B in Chrome)</div>
        </div>
        <div class="step">
            <div class="step-num">2</div>
            <div class="step-text"><strong>Ziehe</strong> diesen Button in die Lesezeichen-Leiste:</div>
        </div>

        <a class="bookmarklet-link"
           href="javascript:void(function(){{var s=document.createElement('script');s.src='http://{host}/overlay.js?t='+Date.now();document.body.appendChild(s)}})();">
            ThrowSync
        </a>

        <div class="step">
            <div class="step-num">3</div>
            <div class="step-text">Gehe auf <strong>Autodarts</strong> oder <strong>Darthelfer</strong></div>
        </div>
        <div class="step">
            <div class="step-num">4</div>
            <div class="step-text">Klicke auf <strong>ThrowSync</strong> in der Lesezeichen-Leiste</div>
        </div>
        <p class="note">Nochmal klicken = Overlay ein/ausblenden. Funktioniert auch im Fullscreen (F11)!</p>
    </div>

    <div class="card">
        <h2>Vorschau</h2>
        <p>So sieht das HUD am unteren Bildschirmrand aus:</p>
        <div class="preview">
            <div class="preview-bar">
                <span style="font-size:9px;color:rgba(255,255,255,0.25);font-weight:600;letter-spacing:1px;">THROWSYNC</span>
                <span style="width:7px;height:7px;border-radius:50%;background:#10b981;box-shadow:0 0 6px #10b981;display:inline-block;"></span>
                <span style="width:1px;height:24px;background:rgba(255,255,255,0.15);display:inline-block;"></span>
                <span><span class="p-label">Aufnahme</span><br><span class="p-val p-score">140</span></span>
                <span style="width:1px;height:24px;background:rgba(255,255,255,0.15);display:inline-block;"></span>
                <span><span class="p-label">Rest</span><br><span class="p-val p-rest">161</span></span>
                <span style="width:1px;height:24px;background:rgba(255,255,255,0.15);display:inline-block;"></span>
                <span><span class="p-label">Letzter Wurf</span><br><span class="p-val p-throw">T20</span></span>
            </div>
        </div>
        <p class="note" style="margin-top:12px;">
            Bei Events (180, Bust, Match Won) erscheinen Toasts oben und Clips als Overlay.
            <br>Kleiner lila Knopf &#x25C6; unten rechts = HUD ein/ausblenden.
        </p>
    </div>

    <div class="card">
        <h2>Alternativ: OBS Browser Source</h2>
        <p>URL: <code>http://{host}/display</code></p>
        <p class="note">Als Browser-Source in OBS einfuegen (transparenter Hintergrund).</p>
    </div>
</body></html>"""
    return HTMLResponse(html)


def main():
    """Entry point — works both as Python script and PyInstaller binary."""
    import threading
    import webbrowser

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8420"))
    version = get_app_version()

    print()
    print("  +----------------------------------+")
    print(f"  |   THROWSYNC v{version:<20s}|")
    print("  |   WLED + Autodarts + Caller       |")
    print("  +----------------------------------+")
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
