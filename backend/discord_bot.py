"""
ThrowSync — Discord Integration
Post game events to Discord channels via webhooks.
No bot token needed — just a webhook URL.

Features:
- Rich embed messages for game events
- Player stats updates
- Achievement notifications
- Live match scores
"""
MODULE_VERSION = "1.0.0"

import logging
import json

logger = logging.getLogger("discord")

DEFAULT_DISCORD_CONFIG = {
    "enabled": False,
    "webhook_url": "",
    "bot_name": "ThrowSync",
    "avatar_url": "",
    "post_180": True,
    "post_match_won": True,
    "post_game_won": False,
    "post_busted": False,
    "post_high_score": True,
    "post_achievements": True,
    "min_high_score": 100,
}

# Discord embed colors
COLORS = {
    "180": 0xFF4500,       # Orange-Red
    "match_won": 0xFFD700,  # Gold
    "game_won": 0x22C55E,   # Green
    "busted": 0xEF4444,     # Red
    "high_score": 0x3B82F6, # Blue
    "bullseye": 0x8B5CF6,   # Purple
    "achievement": 0xF59E0B, # Amber
}

EMOJIS = {
    "180": "\U0001F525",
    "match_won": "\U0001F3C6",
    "game_won": "\u2705",
    "busted": "\U0001F4A5",
    "high_score": "\U0001F4AA",
    "bullseye": "\U0001F3AF",
    "achievement": "\U0001F3C5",
}


async def send_discord_webhook(webhook_url: str, embed: dict, bot_name: str = "ThrowSync", avatar_url: str = ""):
    """Send a Discord webhook message with embed."""
    import aiohttp
    payload = {
        "username": bot_name,
        "embeds": [embed],
    }
    if avatar_url:
        payload["avatar_url"] = avatar_url

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status in (200, 204):
                    logger.debug("Discord webhook sent")
                    return True
                else:
                    text = await resp.text()
                    logger.error(f"Discord webhook failed ({resp.status}): {text}")
                    return False
    except Exception as e:
        logger.error(f"Discord webhook error: {e}")
        return False


def build_event_embed(event: str, player: str = "", score: int = 0, stats: dict = None, achievement: dict = None) -> dict:
    """Build a Discord embed for a game event."""
    color = COLORS.get(event, 0x8B5CF6)
    emoji = EMOJIS.get(event, "\U0001F3AF")

    if event == "180":
        return {
            "title": f"{emoji} 180! MAXIMUM!",
            "description": f"**{player}** wirft die perfekte 180!",
            "color": color,
            "footer": {"text": "ThrowSync \u2022 Dart Gaming Lightshow"},
        }
    elif event == "match_won":
        return {
            "title": f"{emoji} Match gewonnen!",
            "description": f"**{player}** gewinnt das Match!",
            "color": color,
            "fields": _stats_fields(stats) if stats else [],
            "footer": {"text": "ThrowSync"},
        }
    elif event == "game_won":
        return {
            "title": f"{emoji} Leg gewonnen!",
            "description": f"**{player}** checkt aus!",
            "color": color,
        }
    elif event == "busted":
        return {
            "title": f"{emoji} Bust!",
            "description": f"**{player}** hat sich \u00fcberworfen!",
            "color": color,
        }
    elif event == "high_score":
        return {
            "title": f"{emoji} High Score: {score}",
            "description": f"**{player}** mit {score} Punkten in einer Aufnahme!",
            "color": color,
        }
    elif event == "achievement":
        ach = achievement or {}
        return {
            "title": f"{emoji} Achievement Unlocked!",
            "description": f"**{player}** hat freigeschaltet: {ach.get('icon', '')} **{ach.get('name', '?')}**\n_{ach.get('desc', '')}_",
            "color": color,
            "footer": {"text": f"Tier: {ach.get('tier', '').upper()}"},
        }
    else:
        return {
            "title": f"{emoji} {event}",
            "description": f"**{player}** \u2014 {event}",
            "color": color,
        }


def _stats_fields(stats: dict) -> list:
    if not stats:
        return []
    return [
        {"name": "Avg Score", "value": str(stats.get("avg_score", "—")), "inline": True},
        {"name": "180s", "value": str(stats.get("total_180s", 0)), "inline": True},
        {"name": "Legs Won", "value": str(stats.get("legs_won", 0)), "inline": True},
    ]
