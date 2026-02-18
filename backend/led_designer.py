"""
ThrowSync — LED Animation Designer
Create custom LED animations with keyframes, played on WLED devices.

Animation structure:
{
    "id": "uuid",
    "name": "My Animation",
    "frames": [
        {"time": 0, "colors": ["#ff0000", "#00ff00", "#0000ff"], "brightness": 255, "transition": 200},
        {"time": 500, "colors": ["#ffff00"], "brightness": 180, "transition": 300},
    ],
    "duration": 2000,  # total ms
    "loop": True,
    "led_count": 30,
    "blend_mode": "linear",  # linear, step, ease
}
"""
MODULE_VERSION = "1.0.0"

import uuid
import logging

logger = logging.getLogger("led-designer")

BLEND_MODES = ["linear", "step", "ease"]

PRESET_ANIMATIONS = [
    {
        "id": "rainbow_wave",
        "name": "Rainbow Wave",
        "frames": [
            {"time": 0, "colors": ["#ff0000", "#ff8800", "#ffff00", "#00ff00", "#0088ff", "#8800ff"], "brightness": 200, "transition": 500},
            {"time": 1000, "colors": ["#8800ff", "#ff0000", "#ff8800", "#ffff00", "#00ff00", "#0088ff"], "brightness": 200, "transition": 500},
            {"time": 2000, "colors": ["#0088ff", "#8800ff", "#ff0000", "#ff8800", "#ffff00", "#00ff00"], "brightness": 200, "transition": 500},
        ],
        "duration": 3000, "loop": True, "led_count": 30, "blend_mode": "linear",
        "builtin": True,
    },
    {
        "id": "pulse_red",
        "name": "Red Pulse",
        "frames": [
            {"time": 0, "colors": ["#ff0000"], "brightness": 255, "transition": 300},
            {"time": 500, "colors": ["#ff0000"], "brightness": 40, "transition": 300},
        ],
        "duration": 1000, "loop": True, "led_count": 30, "blend_mode": "ease",
        "builtin": True,
    },
    {
        "id": "police",
        "name": "Police Lights",
        "frames": [
            {"time": 0, "colors": ["#0000ff", "#0000ff", "#ff0000", "#ff0000"], "brightness": 255, "transition": 50},
            {"time": 200, "colors": ["#ff0000", "#ff0000", "#0000ff", "#0000ff"], "brightness": 255, "transition": 50},
        ],
        "duration": 400, "loop": True, "led_count": 30, "blend_mode": "step",
        "builtin": True,
    },
    {
        "id": "fire",
        "name": "Fire",
        "frames": [
            {"time": 0, "colors": ["#ff2200", "#ff6600", "#ff4400", "#ff8800", "#ff2200"], "brightness": 220, "transition": 150},
            {"time": 300, "colors": ["#ff4400", "#ff2200", "#ff8800", "#ff2200", "#ff6600"], "brightness": 180, "transition": 150},
            {"time": 600, "colors": ["#ff8800", "#ff4400", "#ff2200", "#ff6600", "#ff4400"], "brightness": 240, "transition": 150},
        ],
        "duration": 900, "loop": True, "led_count": 30, "blend_mode": "linear",
        "builtin": True,
    },
    {
        "id": "victory_gold",
        "name": "Victory Gold",
        "frames": [
            {"time": 0, "colors": ["#000000"], "brightness": 0, "transition": 100},
            {"time": 200, "colors": ["#ffd700", "#ffaa00", "#ffd700"], "brightness": 255, "transition": 200},
            {"time": 800, "colors": ["#ffd700"], "brightness": 255, "transition": 100},
            {"time": 1500, "colors": ["#ffd700"], "brightness": 40, "transition": 500},
        ],
        "duration": 2000, "loop": False, "led_count": 30, "blend_mode": "ease",
        "builtin": True,
    },
    {
        "id": "ice_blue",
        "name": "Ice Blue",
        "frames": [
            {"time": 0, "colors": ["#00aaff", "#0066ff", "#00ccff"], "brightness": 180, "transition": 800},
            {"time": 1500, "colors": ["#0066ff", "#00ccff", "#00aaff"], "brightness": 120, "transition": 800},
        ],
        "duration": 3000, "loop": True, "led_count": 30, "blend_mode": "ease",
        "builtin": True,
    },
]


def create_animation(name: str, led_count: int = 30) -> dict:
    """Create a new empty animation."""
    return {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "frames": [
            {"time": 0, "colors": ["#8b5cf6"], "brightness": 200, "transition": 300},
            {"time": 1000, "colors": ["#3b82f6"], "brightness": 200, "transition": 300},
        ],
        "duration": 2000,
        "loop": True,
        "led_count": led_count,
        "blend_mode": "linear",
    }


def hex_to_rgb(h: str) -> tuple:
    """Convert hex color to RGB tuple."""
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def interpolate_color(c1: str, c2: str, t: float) -> str:
    """Interpolate between two hex colors. t=0 returns c1, t=1 returns c2."""
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return rgb_to_hex(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def generate_wled_payload(animation: dict, time_ms: int) -> dict:
    """Generate WLED JSON API payload for a given animation at a specific time.
    Returns dict suitable for sending to WLED /json/state.
    """
    frames = animation.get("frames", [])
    if not frames:
        return {}
    duration = animation.get("duration", 2000)
    if animation.get("loop") and duration > 0:
        time_ms = time_ms % duration

    # Find surrounding keyframes
    prev_frame = frames[0]
    next_frame = frames[-1]
    for i, f in enumerate(frames):
        if f["time"] <= time_ms:
            prev_frame = f
            next_frame = frames[i + 1] if i + 1 < len(frames) else f

    # Interpolation factor
    span = next_frame["time"] - prev_frame["time"]
    t = (time_ms - prev_frame["time"]) / span if span > 0 else 0
    t = max(0, min(1, t))

    blend = animation.get("blend_mode", "linear")
    if blend == "step":
        t = 0  # No interpolation
    elif blend == "ease":
        t = t * t * (3 - 2 * t)  # Smoothstep

    # Interpolate brightness
    bri = int(prev_frame.get("brightness", 200) + (next_frame.get("brightness", 200) - prev_frame.get("brightness", 200)) * t)

    # Interpolate colors
    prev_colors = prev_frame.get("colors", ["#ffffff"])
    next_colors = next_frame.get("colors", ["#ffffff"])
    led_count = animation.get("led_count", 30)
    seg_colors = []
    for i in range(min(3, max(len(prev_colors), len(next_colors)))):
        c1 = prev_colors[i % len(prev_colors)]
        c2 = next_colors[i % len(next_colors)]
        seg_colors.append(list(hex_to_rgb(interpolate_color(c1, c2, t))))

    transition = int(next_frame.get("transition", 200) / 100)  # WLED uses 0.1s units

    return {
        "on": True,
        "bri": max(0, min(255, bri)),
        "transition": transition,
        "seg": [{"col": seg_colors}],
    }
