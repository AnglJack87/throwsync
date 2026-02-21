"""
Device Manager - Handles multiple WLED devices, discovery, and status tracking.
"""
MODULE_VERSION = "1.2.0"

import asyncio
import logging
import uuid
from typing import Optional
from datetime import datetime

from wled_client import WLEDClient
from config_manager import ConfigManager

logger = logging.getLogger("device-manager")


class DeviceManager:
    """Manages multiple WLED devices across different networks."""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.clients: dict[str, WLEDClient] = {}
        self._status_cache: dict[str, dict] = {}
        self._poll_task: Optional[asyncio.Task] = None

    async def start(self):
        """Initialize device manager and connect to saved devices."""
        devices = self.config.get("devices", [])
        for device in devices:
            ip = device.get("ip", "")
            device_id = device.get("id", str(uuid.uuid4())[:8])
            if ip:
                self.clients[device_id] = WLEDClient(ip)
                logger.info(f"Loaded device {device.get('name', ip)} ({ip})")

        # Start polling for device status
        self._poll_task = asyncio.create_task(self._poll_status())

    async def stop(self):
        """Stop device manager."""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        # Close all WLED sessions
        for client in self.clients.values():
            try:
                await client.close()
            except Exception:
                pass

    async def _poll_status(self):
        """Periodically poll device status."""
        while True:
            try:
                for device_id, client in list(self.clients.items()):
                    try:
                        info = await client.get_info()
                        state = await client.get_state()
                        self._status_cache[device_id] = {
                            "online": info is not None,
                            "info": info,
                            "state": state,
                            "last_seen": datetime.utcnow().isoformat() if info else
                                self._status_cache.get(device_id, {}).get("last_seen"),
                        }
                    except Exception as e:
                        self._status_cache[device_id] = {
                            "online": False,
                            "info": None,
                            "state": None,
                            "last_seen": self._status_cache.get(device_id, {}).get("last_seen"),
                        }
            except Exception as e:
                logger.error(f"Poll error: {e}")
            await asyncio.sleep(10)  # Poll every 10 seconds

    async def add_device(self, ip: str, name: str = "", led_count: int = 0) -> Optional[dict]:
        """Add a new device. Returns device info if successful."""
        client = WLEDClient(ip)
        info = await client.get_info()
        if info is None:
            return None

        device_id = str(uuid.uuid4())[:8]
        device_name = name or info.get("name", f"WLED-{ip}")
        actual_led_count = led_count or info.get("leds", {}).get("count", 0)

        # If user specified LED count, push it to WLED
        if led_count > 0:
            await client.set_state({"seg": [{"start": 0, "stop": led_count}]})

        self.clients[device_id] = client
        self._status_cache[device_id] = {
            "online": True,
            "info": info,
            "state": await client.get_state(),
            "last_seen": datetime.utcnow().isoformat(),
        }

        # Save to config
        devices = self.config.get("devices", [])
        devices.append({
            "id": device_id,
            "ip": ip,
            "name": device_name,
            "led_count": actual_led_count,
        })
        self.config.set("devices", devices)
        self.config.save()

        return {
            "id": device_id,
            "ip": ip,
            "name": device_name,
            "led_count": actual_led_count,
            "online": True,
            "info": info,
        }

    async def set_led_count(self, device_id: str, led_count: int) -> bool:
        """Set LED count for a device and push config to WLED."""
        client = self.clients.get(device_id)
        if not client:
            return False

        # Push to WLED: set segment 0 to the correct LED count
        result = await client.set_state({"seg": [{"id": 0, "start": 0, "stop": led_count}]})
        if result:
            # Save to config
            devices = self.config.get("devices", [])
            for d in devices:
                if d.get("id") == device_id:
                    d["led_count"] = led_count
                    break
            self.config.set("devices", devices)
            self.config.save()
            return True
        return False

    def remove_device(self, device_id: str) -> bool:
        """Remove a device from management."""
        if device_id in self.clients:
            del self.clients[device_id]
            self._status_cache.pop(device_id, None)

            devices = self.config.get("devices", [])
            devices = [d for d in devices if d.get("id") != device_id]
            self.config.set("devices", devices)
            self.config.save()
            return True
        return False

    async def get_all_devices(self) -> list:
        """Get all devices with their current status."""
        devices = self.config.get("devices", [])
        result = []
        for device in devices:
            device_id = device.get("id", "")
            status = self._status_cache.get(device_id, {})
            info = status.get("info", {}) or {}
            state = status.get("state", {}) or {}

            result.append({
                "id": device_id,
                "ip": device.get("ip", ""),
                "name": device.get("name", ""),
                "online": status.get("online", False),
                "last_seen": status.get("last_seen"),
                "led_count": device.get("led_count", 0) or info.get("leds", {}).get("count", 0),
                "version": info.get("ver", "unknown"),
                "brightness": state.get("bri", 0),
                "power": state.get("on", False),
                "segments": state.get("seg", []),
            })
        return result

    async def get_device_state(self, device_id: str) -> Optional[dict]:
        """Get full WLED state of a device."""
        client = self.clients.get(device_id)
        if client:
            return await client.get_state()
        return None

    async def set_device_state(self, device_id: str, state: dict) -> bool:
        """Set WLED state on a device."""
        client = self.clients.get(device_id)
        if client:
            result = await client.set_state(state)
            if not result:
                logger.debug(f"set_device_state({device_id}): WLED returned false")
            return result
        logger.warning(f"set_device_state: Device '{device_id}' nicht gefunden! Verfügbar: {list(self.clients.keys())}")
        return False

    async def get_device_info(self, device_id: str) -> Optional[dict]:
        """Get detailed WLED info of a device."""
        client = self.clients.get(device_id)
        if client:
            return await client.get_info()
        return None

    async def identify_device(self, device_id: str) -> bool:
        """Flash a device to identify it."""
        client = self.clients.get(device_id)
        if client:
            return await client.identify()
        return False

    async def get_segments(self, device_id: str) -> list:
        """Get segments of a device."""
        state = await self.get_device_state(device_id)
        if state:
            return state.get("seg", [])
        return []

    async def set_segments(self, device_id: str, segments: list) -> bool:
        """Set segments on a device."""
        client = self.clients.get(device_id)
        if client:
            return await client.set_segments(segments)
        return False

    async def set_color(self, device_id: str, color: list, segment: Optional[int] = None,
                        brightness: Optional[int] = None) -> bool:
        """Set color on a device."""
        client = self.clients.get(device_id)
        if not client:
            return False

        state = {"seg": [{"col": [color[:3]]}]}
        if segment is not None:
            state["seg"][0]["id"] = segment
        if brightness is not None:
            state["bri"] = brightness
        state["on"] = True

        return await client.set_state(state)

    async def set_effect(self, device_id: str, effect_id: int, speed: int = 128,
                         intensity: int = 128, palette: int = 0,
                         segment: Optional[int] = None) -> bool:
        """Set effect on a device."""
        client = self.clients.get(device_id)
        if client:
            return await client.set_effect(effect_id, speed, intensity, palette, segment)
        return False

    async def set_individual_leds(self, device_id: str, leds: dict) -> bool:
        """Set individual LED colors."""
        client = self.clients.get(device_id)
        if client:
            return await client.set_individual_leds(leds)
        return False

    async def discover_devices(self, timeout: float = 3.0) -> list:
        """Discover WLED devices on the local network via mDNS/scanning."""
        discovered = []

        # Try common subnet scanning (simplified)
        # In production, you'd use zeroconf/mDNS
        import socket
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            local_ip = "192.168.1.1"

        # Extract subnet
        parts = local_ip.rsplit(".", 1)
        if len(parts) == 2:
            subnet = parts[0]
        else:
            subnet = "192.168.1"

        logger.info(f"Scanning subnet {subnet}.0/24 for WLED devices...")

        async def check_ip(ip: str):
            client = WLEDClient(ip, timeout=2.0)
            info = await client.get_info()
            if info:
                return {
                    "ip": ip,
                    "name": info.get("name", f"WLED-{ip}"),
                    "version": info.get("ver", "?"),
                    "led_count": info.get("leds", {}).get("count", 0),
                    "already_managed": any(
                        d.get("ip") == ip for d in self.config.get("devices", [])
                    )
                }
            return None

        # Scan in batches
        tasks = []
        for i in range(1, 255):
            ip = f"{subnet}.{i}"
            tasks.append(check_ip(ip))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, dict):
                discovered.append(result)

        logger.info(f"Found {len(discovered)} WLED devices")
        return discovered

    def get_client(self, device_id: str) -> Optional[WLEDClient]:
        """Get a WLEDClient by device ID."""
        return self.clients.get(device_id)

    async def apply_to_all(self, state: dict) -> dict:
        """Apply a state to all online devices. Returns results per device."""
        results = {}
        for device_id, client in self.clients.items():
            try:
                success = await client.set_state(state)
                results[device_id] = success
            except Exception as e:
                results[device_id] = False
        return results
