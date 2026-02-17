"""
WLED Client - HTTP/JSON API communication with WLED devices.
Supports WLED API v1 (JSON) for controlling LED strips.
"""
MODULE_VERSION = "1.2.0"

import asyncio
import logging
from typing import Optional
import aiohttp

logger = logging.getLogger("wled-client")


class WLEDClient:
    """Client for communicating with a single WLED device via its JSON API."""

    # Common WLED effects (index → name)
    KNOWN_EFFECTS = [
        "Solid", "Blink", "Breathe", "Wipe", "Wipe Random", "Random Colors",
        "Sweep", "Dynamic", "Colorloop", "Rainbow", "Scan", "Scan Dual",
        "Fade", "Theater", "Theater Rainbow", "Running", "Saw", "Twinkle",
        "Dissolve", "Dissolve Rnd", "Sparkle", "Sparkle Dark", "Sparkle+",
        "Strobe", "Strobe Rainbow", "Strobe Mega", "Blink Rainbow", "Android",
        "Chase", "Chase Random", "Chase Rainbow", "Chase Flash", "Chase Flash Rnd",
        "Rainbow Runner", "Colorful", "Traffic Light", "Sweep Random", "Chase 2",
        "Aurora", "Stream", "Scanner", "Lighthouse", "Fireworks", "Rain",
        "Tetrix", "Fire Flicker", "Gradient", "Loading", "Police", "Fairy",
        "Two Dots", "Fairytwinkle", "Running Dual", "Halloween", "Chase 3",
        "Tri Wipe", "Tri Fade", "Lightning", "ICU", "Multi Comet", "Scanner Dual",
        "Stream 2", "Oscillate", "Pride 2015", "Juggle", "Palette", "Fire 2012",
        "Colorwaves", "Bpm", "Fill Noise", "Noise 1", "Noise 2", "Noise 3",
        "Noise 4", "Colortwinkles", "Lake", "Meteor", "Meteor Smooth",
        "Railway", "Ripple", "Twinklefox", "Twinklecat", "Halloween Eyes",
        "Solid Pattern", "Solid Pattern Tri", "Spots", "Spots Fade", "Glitter",
        "Candle", "Fireworks Starburst", "Fireworks 1D", "Bouncing Balls",
        "Sinelon", "Sinelon Dual", "Sinelon Rainbow", "Popcorn", "Drip",
        "Plasma", "Percent", "Ripple Rainbow", "Heartbeat", "Pacifica",
        "Candle Multi", "Solid Glitter", "Sunrise", "Phased", "Twinkleup",
        "Noise Pal", "Sine", "Phased Noise", "Flow", "Chunchun", "Dancing Shadows",
        "Washing Machine", "Blends", "TV Simulator", "Dynamic Smooth"
    ]

    KNOWN_PALETTES = [
        "Default", "* Random Cycle", "* Color 1", "* Colors 1&2", "* Color Gradient",
        "* Colors Only", "Party", "Cloud", "Lava", "Ocean", "Forest", "Rainbow",
        "Rainbow Bands", "Sunset", "Rivendell", "Breeze", "Red & Blue",
        "Yellowout", "Analogous", "Splash", "Pastel", "Sunset 2", "Beach",
        "Vintage", "Departure", "Landscape", "Beech", "Sherbet", "Hult",
        "Hult 64", "Drywet", "Jul", "Grintage", "Rewhi", "Tertiary",
        "Fire", "Icefire", "Cyane", "Light Pink", "Autumn", "Magenta",
        "Magred", "Yelmag", "Yelblu", "Orange & Teal", "Tiamat", "April Night",
        "Orangery", "C9", "Sakura", "Aurora", "Atlantica", "C9 2",
        "C9 New", "Temperature", "Aurora 2", "Retro Clown", "Candy",
        "Toxy Reaf", "Fairy Reaf", "Semi Blue", "Pink Candy", "Red Reaf",
        "Aqua Flash", "Yelblu Hot", "Lite Light", "Red Flash", "Blink Red",
        "Red Shift", "Red Tide", "Candy2"
    ]

    def __init__(self, ip: str, timeout: float = 5.0):
        self.ip = ip
        self.base_url = f"http://{ip}"
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def _get(self, path: str) -> Optional[dict]:
        """Make a GET request to the WLED API."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}{path}") as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.warning(f"GET {self.ip}{path} failed: {e}")
        return None

    async def _post(self, path: str, data: dict) -> bool:
        """Make a POST request to the WLED API."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(f"{self.base_url}{path}", json=data) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.warning(f"POST {self.ip}{path} failed: {e}")
        return False

    async def is_online(self) -> bool:
        """Check if the WLED device is reachable."""
        info = await self._get("/json/info")
        return info is not None

    async def get_info(self) -> Optional[dict]:
        """Get device info (name, version, LED count, etc.)."""
        return await self._get("/json/info")

    async def get_state(self) -> Optional[dict]:
        """Get current device state (on/off, brightness, segments, etc.)."""
        return await self._get("/json/state")

    async def get_full(self) -> Optional[dict]:
        """Get full JSON state including info, state, effects, and palettes."""
        return await self._get("/json")

    async def get_effects(self) -> Optional[list]:
        """Get the actual effects list from this device."""
        data = await self._get("/json/effects")
        return data if isinstance(data, list) else None

    async def get_palettes(self) -> Optional[list]:
        """Get the actual palettes list from this device."""
        data = await self._get("/json/palettes")
        return data if isinstance(data, list) else None

    async def set_state(self, state: dict) -> bool:
        """Set device state via JSON API."""
        return await self._post("/json/state", state)

    async def set_power(self, on: bool) -> bool:
        """Turn device on/off."""
        return await self.set_state({"on": on})

    async def set_brightness(self, brightness: int) -> bool:
        """Set brightness (0-255)."""
        return await self.set_state({"bri": max(0, min(255, brightness))})

    async def set_color(self, r: int, g: int, b: int, segment: Optional[int] = None) -> bool:
        """Set a solid color."""
        if segment is not None:
            return await self.set_state({
                "seg": [{"id": segment, "col": [[r, g, b]]}]
            })
        return await self.set_state({
            "seg": [{"col": [[r, g, b]]}]
        })

    async def set_effect(self, effect_id: int, speed: int = 128, intensity: int = 128,
                         palette: int = 0, segment: Optional[int] = None) -> bool:
        """Set an effect with speed, intensity, and palette."""
        seg_data = {
            "fx": effect_id,
            "sx": max(0, min(255, speed)),
            "ix": max(0, min(255, intensity)),
            "pal": palette,
        }
        if segment is not None:
            seg_data["id"] = segment
        return await self.set_state({"seg": [seg_data]})

    async def set_segments(self, segments: list) -> bool:
        """Configure LED segments. Each segment: {start, stop, col, fx, ...}"""
        return await self.set_state({"seg": segments})

    async def set_individual_leds(self, led_colors: dict) -> bool:
        """
        Set individual LED colors using the WLED individual LED API.
        led_colors: {led_index: [r, g, b], ...}
        Uses the 'i' field in segment to address individual LEDs.
        """
        # Build the individual LED control array
        # Format: [led_index, R, G, B, led_index2, R2, G2, B2, ...]
        i_array = []
        for idx, color in sorted(led_colors.items(), key=lambda x: int(x[0])):
            i_array.append(int(idx))
            i_array.extend(color[:3])

        return await self.set_state({
            "seg": [{"i": i_array}]
        })

    async def identify(self) -> bool:
        """Flash the device white briefly for identification."""
        # Save current state
        old_state = await self.get_state()

        # Flash white
        await self.set_state({
            "on": True,
            "bri": 255,
            "seg": [{"col": [[255, 255, 255]], "fx": 0}],
            "transition": 0
        })
        await asyncio.sleep(0.5)

        # Flash off
        await self.set_state({"bri": 0, "transition": 0})
        await asyncio.sleep(0.3)

        # Flash white again
        await self.set_state({"bri": 255, "transition": 0})
        await asyncio.sleep(0.5)

        # Restore
        if old_state:
            await self.set_state(old_state)
        return True

    async def get_presets(self) -> Optional[dict]:
        """Get saved presets on the device."""
        return await self._get("/presets.json")

    async def save_preset(self, slot: int, name: str, state: dict) -> bool:
        """Save a preset on the device."""
        return await self._post("/json/state", {
            "psave": slot,
            "n": name,
            **state
        })

    async def load_preset(self, slot: int) -> bool:
        """Load a preset on the device."""
        return await self.set_state({"ps": slot})
