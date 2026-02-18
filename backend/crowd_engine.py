"""
ThrowSync — Crowd Sound Engine
Dynamic crowd/ambient sounds that react to game events.

Features:
- Background ambient murmur during play
- Cheering that scales with score quality
- Tension building before checkout attempts
- Dramatic reactions (180, Bullseye, Bust, Win)
- Configurable volume and intensity
"""
MODULE_VERSION = "1.0.0"

import logging

logger = logging.getLogger("crowd-engine")

# ── Crowd Sound Categories ──
# These map to sound files the user uploads into sounds/ folder
# Format: crowd_<category>_<variant>.mp3

CROWD_EVENTS = {
    # Ambient / Background
    "crowd_ambient_murmur": {
        "label": "Hintergrund-Gemurmel",
        "category": "ambient",
        "description": "Leises Publikumsrauschen während des Spiels",
        "default_volume": 0.15,
    },
    "crowd_ambient_tension": {
        "label": "Spannung",
        "category": "ambient",
        "description": "Angespanntes Flüstern vor dem Checkout-Versuch",
        "default_volume": 0.2,
    },

    # Positive Reactions
    "crowd_cheer_light": {
        "label": "Leichter Applaus",
        "category": "positive",
        "description": "Für solide Scores (40-59)",
        "default_volume": 0.3,
    },
    "crowd_cheer_medium": {
        "label": "Jubel",
        "category": "positive",
        "description": "Für gute Scores (60-99)",
        "default_volume": 0.5,
    },
    "crowd_cheer_loud": {
        "label": "Lauter Jubel",
        "category": "positive",
        "description": "Für sehr gute Scores (100-139)",
        "default_volume": 0.7,
    },
    "crowd_cheer_epic": {
        "label": "Frenetischer Jubel",
        "category": "positive",
        "description": "Für überragende Scores (140-179)",
        "default_volume": 0.85,
    },
    "crowd_cheer_180": {
        "label": "180 Explosion",
        "category": "positive",
        "description": "Maximaler Jubel bei 180!",
        "default_volume": 1.0,
    },
    "crowd_cheer_bullseye": {
        "label": "Bullseye Jubel",
        "category": "positive",
        "description": "Begeisterung bei Bullseye",
        "default_volume": 0.8,
    },
    "crowd_cheer_checkout": {
        "label": "Checkout Jubel",
        "category": "positive",
        "description": "Jubel beim erfolgreichen Checkout",
        "default_volume": 0.9,
    },
    "crowd_cheer_match_won": {
        "label": "Match-Sieg Jubel",
        "category": "positive",
        "description": "Maximaler Jubel + Applaus beim Matchsieg",
        "default_volume": 1.0,
    },

    # Negative Reactions
    "crowd_groan_miss": {
        "label": "Enttäuschtes Stöhnen",
        "category": "negative",
        "description": "Bei Daneben-Würfen",
        "default_volume": 0.4,
    },
    "crowd_groan_bust": {
        "label": "Überworfen!",
        "category": "negative",
        "description": "Kollektives Stöhnen bei Bust",
        "default_volume": 0.6,
    },
    "crowd_groan_low": {
        "label": "Enttäuschung",
        "category": "negative",
        "description": "Bei schwachen Scores (0-25)",
        "default_volume": 0.35,
    },
    "crowd_silence": {
        "label": "Stille",
        "category": "negative",
        "description": "Peinliche Stille bei 0-Punkte",
        "default_volume": 0.1,
    },

    # Special
    "crowd_ooh": {
        "label": "Ooh!",
        "category": "special",
        "description": "Staunendes 'Ooh' bei knappen Würfen",
        "default_volume": 0.5,
    },
    "crowd_countdown": {
        "label": "Countdown",
        "category": "special",
        "description": "Publikum zählt runter bei niedrigem Rest",
        "default_volume": 0.4,
    },
    "crowd_clap_rhythm": {
        "label": "Rhythmisches Klatschen",
        "category": "special",
        "description": "Klatschen zwischen den Würfen",
        "default_volume": 0.25,
    },
}

# ── Score → Crowd Reaction Mapping ──
def get_crowd_reaction(score: int, event_type: str = "", remaining: int = None) -> list:
    """Determine crowd sounds based on score and game event.
    Returns list of crowd sound keys to play.
    """
    sounds = []

    # Special events take priority
    if event_type == "180":
        sounds.append("crowd_cheer_180")
        return sounds
    if event_type == "match_won":
        sounds.append("crowd_cheer_match_won")
        return sounds
    if event_type == "game_won":
        sounds.append("crowd_cheer_checkout")
        return sounds
    if event_type == "busted":
        sounds.append("crowd_groan_bust")
        return sounds
    if event_type == "bullseye":
        sounds.append("crowd_cheer_bullseye")
        return sounds
    if event_type == "miss":
        sounds.append("crowd_groan_miss")
        return sounds
    if event_type == "checkout_possible":
        sounds.append("crowd_ambient_tension")
        return sounds
    if event_type == "game_on":
        sounds.append("crowd_cheer_light")
        return sounds

    # Score-based reactions (turn score after 3 darts)
    if score <= 0:
        sounds.append("crowd_silence")
    elif score <= 25:
        sounds.append("crowd_groan_low")
    elif score <= 39:
        pass  # No reaction, neutral
    elif score <= 59:
        sounds.append("crowd_cheer_light")
    elif score <= 99:
        sounds.append("crowd_cheer_medium")
    elif score <= 139:
        sounds.append("crowd_cheer_loud")
    elif score <= 179:
        sounds.append("crowd_cheer_epic")

    return sounds


# ── Default config ──
DEFAULT_CROWD_CONFIG = {
    "enabled": False,
    "master_volume": 0.5,
    "ambient_enabled": True,
    "reactions_enabled": True,
}
