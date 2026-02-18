"""
ThrowSync — Player Profiles
Each player gets personalized sounds, LED colors, clips, and walk-on effects.
Auto-switches when Autodarts detects player change.

Profile structure:
{
    "id": "uuid",
    "name": "Marcel",
    "avatar": "🎯",  # emoji or image
    "walk_on_sound": "walk_on_marcel.mp3",
    "led_color": "#8b5cf6",
    "led_effect": 0,
    "victory_clip": "victory.mp4",
    "bust_clip": "bust.gif",
    "theme": {
        "cheer_sound": "crowd_cheer.mp3",
        "score_color_low": "#ef4444",
        "score_color_high": "#10b981",
    },
    "stats": {
        "games_played": 0,
        "legs_won": 0,
        "matches_won": 0,
        "highest_score": 0,
        "total_180s": 0,
        "total_bullseyes": 0,
        "checkouts_hit": 0,
        "checkouts_missed": 0,
        "avg_score": 0.0,
        "best_checkout": 0,
        "scores_history": [],  # last 50 turn scores for avg calculation
    }
}
"""
MODULE_VERSION = "1.0.0"

import uuid
import time
import logging

logger = logging.getLogger("player-profiles")

# ── Avatars available for selection ──
AVATARS = [
    "\U0001F3AF", "\U0001F525", "\U0001F451", "\U0001F947", "\U0001F3C6",
    "\U0001F48E", "\U0001F31F", "\U000026A1", "\U0001F680", "\U0001F40D",
    "\U0001F43A", "\U0001F981", "\U0001F985", "\U0001F9CA", "\U0001F47B",
    "\U0001F916", "\U0001F3B3", "\U0001F3AE", "\U0001F3B5", "\U0001F3B8",
]


def create_profile(name: str, avatar: str = None) -> dict:
    """Create a new empty player profile."""
    return {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "avatar": avatar or "\U0001F3AF",
        "walk_on_sound": "",
        "led_color": "#8b5cf6",
        "led_brightness": 180,
        "led_effect": 0,
        "victory_clip": "",
        "bust_clip": "",
        "theme": {
            "cheer_sound": "",
            "score_color_low": "#ef4444",
            "score_color_high": "#10b981",
        },
        "stats": empty_stats(),
        "created": time.time(),
    }


def empty_stats() -> dict:
    return {
        "games_played": 0,
        "legs_won": 0,
        "matches_won": 0,
        "highest_score": 0,
        "total_180s": 0,
        "total_bullseyes": 0,
        "checkouts_hit": 0,
        "checkouts_missed": 0,
        "avg_score": 0.0,
        "best_checkout": 0,
        "scores_history": [],
    }


def update_stats(profile: dict, event: str, data: dict = None) -> dict:
    """Update player stats based on game event.
    Returns updated profile (mutated in place).
    """
    data = data or {}
    stats = profile.get("stats", empty_stats())

    if event == "game_on":
        stats["games_played"] = stats.get("games_played", 0) + 1

    elif event == "game_won":
        stats["legs_won"] = stats.get("legs_won", 0) + 1
        checkout = data.get("checkout_score", 0)
        if checkout > 0:
            stats["checkouts_hit"] = stats.get("checkouts_hit", 0) + 1
            if checkout > stats.get("best_checkout", 0):
                stats["best_checkout"] = checkout

    elif event == "match_won":
        stats["matches_won"] = stats.get("matches_won", 0) + 1

    elif event == "busted":
        stats["checkouts_missed"] = stats.get("checkouts_missed", 0) + 1

    elif event == "180":
        stats["total_180s"] = stats.get("total_180s", 0) + 1

    elif event == "bullseye":
        stats["total_bullseyes"] = stats.get("total_bullseyes", 0) + 1

    elif event == "turn_score":
        score = data.get("score", 0)
        if score > stats.get("highest_score", 0):
            stats["highest_score"] = score
        # Rolling average (last 50 turns)
        history = stats.get("scores_history", [])
        history.append(score)
        if len(history) > 50:
            history = history[-50:]
        stats["scores_history"] = history
        stats["avg_score"] = round(sum(history) / len(history), 1) if history else 0.0

    profile["stats"] = stats
    return profile


def get_checkout_rate(stats: dict) -> float:
    """Calculate checkout success rate."""
    hit = stats.get("checkouts_hit", 0)
    missed = stats.get("checkouts_missed", 0)
    total = hit + missed
    if total == 0:
        return 0.0
    return round((hit / total) * 100, 1)
