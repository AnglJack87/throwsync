"""
ThrowSync — Achievement System
Badges and milestones that unlock based on player performance.
"""
MODULE_VERSION = "1.0.0"

import time
import logging

logger = logging.getLogger("achievements")

# ── Achievement Definitions ──
# Each has: id, name, description, icon, category, condition
# condition is checked via check_achievement(achievement_id, stats, event_data)

ACHIEVEMENTS = {
    # ── Score Achievements ──
    "first_180": {
        "name": "Maximum!", "name_en": "Maximum!",
        "desc": "Wirf deine erste 180", "desc_en": "Throw your first 180",
        "icon": "\U0001F525", "category": "score", "tier": "gold",
        "check": lambda s, e: s.get("total_180s", 0) >= 1,
    },
    "180_club_5": {
        "name": "180 Club", "name_en": "180 Club",
        "desc": "5x 180 geworfen", "desc_en": "Throw 5x 180",
        "icon": "\U0001F4AF", "category": "score", "tier": "gold",
        "check": lambda s, e: s.get("total_180s", 0) >= 5,
    },
    "180_master": {
        "name": "180 Master", "name_en": "180 Master",
        "desc": "25x 180 geworfen", "desc_en": "Throw 25x 180",
        "icon": "\U0001F451", "category": "score", "tier": "diamond",
        "check": lambda s, e: s.get("total_180s", 0) >= 25,
    },
    "ton_80": {
        "name": "Ton-80", "name_en": "Ton-80",
        "desc": "Score \u00fcber 100 in einer Aufnahme", "desc_en": "Score over 100 in a turn",
        "icon": "\U0001F4AA", "category": "score", "tier": "bronze",
        "check": lambda s, e: s.get("highest_score", 0) >= 100,
    },
    "ton_40_plus": {
        "name": "Ton-40+", "name_en": "Ton-40+",
        "desc": "Score \u00fcber 140 in einer Aufnahme", "desc_en": "Score over 140 in a turn",
        "icon": "\U000026A1", "category": "score", "tier": "silver",
        "check": lambda s, e: s.get("highest_score", 0) >= 140,
    },
    "bullseye_first": {
        "name": "Bull!", "name_en": "Bull!",
        "desc": "Triff dein erstes Bullseye", "desc_en": "Hit your first Bullseye",
        "icon": "\U0001F3AF", "category": "score", "tier": "bronze",
        "check": lambda s, e: s.get("total_bullseyes", 0) >= 1,
    },
    "bullseye_10": {
        "name": "Bullseye Sniper", "name_en": "Bullseye Sniper",
        "desc": "10 Bullseyes geworfen", "desc_en": "Hit 10 Bullseyes",
        "icon": "\U0001F52B", "category": "score", "tier": "silver",
        "check": lambda s, e: s.get("total_bullseyes", 0) >= 10,
    },
    "avg_40": {
        "name": "Solide", "name_en": "Solid",
        "desc": "Average \u00fcber 40", "desc_en": "Average over 40",
        "icon": "\U0001F44D", "category": "score", "tier": "bronze",
        "check": lambda s, e: s.get("avg_score", 0) >= 40,
    },
    "avg_60": {
        "name": "Stark", "name_en": "Strong",
        "desc": "Average \u00fcber 60", "desc_en": "Average over 60",
        "icon": "\U0001F4AA", "category": "score", "tier": "silver",
        "check": lambda s, e: s.get("avg_score", 0) >= 60,
    },
    "avg_80": {
        "name": "Profi", "name_en": "Pro",
        "desc": "Average \u00fcber 80", "desc_en": "Average over 80",
        "icon": "\U0001F31F", "category": "score", "tier": "gold",
        "check": lambda s, e: s.get("avg_score", 0) >= 80,
    },

    # ── Win Achievements ──
    "first_leg": {
        "name": "Erster Sieg!", "name_en": "First Win!",
        "desc": "Gewinne dein erstes Leg", "desc_en": "Win your first leg",
        "icon": "\u2705", "category": "wins", "tier": "bronze",
        "check": lambda s, e: s.get("legs_won", 0) >= 1,
    },
    "legs_10": {
        "name": "Leg-Sammler", "name_en": "Leg Collector",
        "desc": "10 Legs gewonnen", "desc_en": "Win 10 legs",
        "icon": "\U0001F3C5", "category": "wins", "tier": "silver",
        "check": lambda s, e: s.get("legs_won", 0) >= 10,
    },
    "legs_50": {
        "name": "Leg-Maschine", "name_en": "Leg Machine",
        "desc": "50 Legs gewonnen", "desc_en": "Win 50 legs",
        "icon": "\U0001F3C6", "category": "wins", "tier": "gold",
        "check": lambda s, e: s.get("legs_won", 0) >= 50,
    },
    "first_match": {
        "name": "Match-Sieger", "name_en": "Match Winner",
        "desc": "Gewinne dein erstes Match", "desc_en": "Win your first match",
        "icon": "\U0001F947", "category": "wins", "tier": "bronze",
        "check": lambda s, e: s.get("matches_won", 0) >= 1,
    },
    "matches_10": {
        "name": "Turnier-Spieler", "name_en": "Tournament Player",
        "desc": "10 Matches gewonnen", "desc_en": "Win 10 matches",
        "icon": "\U0001F48E", "category": "wins", "tier": "gold",
        "check": lambda s, e: s.get("matches_won", 0) >= 10,
    },

    # ── Checkout Achievements ──
    "checkout_first": {
        "name": "Ausgecheckt!", "name_en": "Checked Out!",
        "desc": "Erstes erfolgreiches Checkout", "desc_en": "First successful checkout",
        "icon": "\U0001F3AF", "category": "checkout", "tier": "bronze",
        "check": lambda s, e: s.get("checkouts_hit", 0) >= 1,
    },
    "checkout_high": {
        "name": "High Finish", "name_en": "High Finish",
        "desc": "Checkout \u00fcber 100", "desc_en": "Checkout over 100",
        "icon": "\U0001F680", "category": "checkout", "tier": "gold",
        "check": lambda s, e: s.get("best_checkout", 0) >= 100,
    },
    "checkout_170": {
        "name": "Big Fish", "name_en": "Big Fish",
        "desc": "170 Checkout!", "desc_en": "170 Checkout!",
        "icon": "\U0001F40B", "category": "checkout", "tier": "diamond",
        "check": lambda s, e: s.get("best_checkout", 0) >= 170,
    },
    "checkout_rate_50": {
        "name": "Zuverl\u00e4ssig", "name_en": "Reliable",
        "desc": "Checkout-Quote \u00fcber 50%", "desc_en": "Checkout rate over 50%",
        "icon": "\U0001F4C8", "category": "checkout", "tier": "silver",
        "check": lambda s, e: _co_rate(s) >= 50,
    },

    # ── Grind Achievements ──
    "games_10": {
        "name": "Einsteiger", "name_en": "Beginner",
        "desc": "10 Spiele gespielt", "desc_en": "Play 10 games",
        "icon": "\U0001F3AE", "category": "grind", "tier": "bronze",
        "check": lambda s, e: s.get("games_played", 0) >= 10,
    },
    "games_50": {
        "name": "Stammgast", "name_en": "Regular",
        "desc": "50 Spiele gespielt", "desc_en": "Play 50 games",
        "icon": "\U0001F3B3", "category": "grind", "tier": "silver",
        "check": lambda s, e: s.get("games_played", 0) >= 50,
    },
    "games_200": {
        "name": "Dart-Veteran", "name_en": "Dart Veteran",
        "desc": "200 Spiele gespielt", "desc_en": "Play 200 games",
        "icon": "\U0001F396", "category": "grind", "tier": "gold",
        "check": lambda s, e: s.get("games_played", 0) >= 200,
    },
}

TIER_ORDER = {"bronze": 1, "silver": 2, "gold": 3, "diamond": 4}
TIER_COLORS = {
    "bronze": "#cd7f32",
    "silver": "#c0c0c0",
    "gold": "#ffd700",
    "diamond": "#b9f2ff",
}


def _co_rate(s):
    hit = s.get("checkouts_hit", 0)
    total = hit + s.get("checkouts_missed", 0)
    return (hit / total * 100) if total > 0 else 0


def check_achievements(stats: dict, unlocked: list = None) -> list:
    """Check all achievements against current stats.
    Returns list of newly unlocked achievement IDs.
    """
    unlocked = unlocked or []
    newly_unlocked = []
    for aid, ach in ACHIEVEMENTS.items():
        if aid in unlocked:
            continue
        try:
            if ach["check"](stats, {}):
                newly_unlocked.append(aid)
        except Exception:
            pass
    return newly_unlocked


def get_achievement_info(aid: str, lang: str = "de") -> dict:
    """Get display info for an achievement."""
    ach = ACHIEVEMENTS.get(aid)
    if not ach:
        return None
    name_key = "name_en" if lang == "en" else "name"
    desc_key = "desc_en" if lang == "en" else "desc"
    return {
        "id": aid,
        "name": ach.get(name_key, ach["name"]),
        "desc": ach.get(desc_key, ach["desc"]),
        "icon": ach["icon"],
        "category": ach["category"],
        "tier": ach["tier"],
        "tier_color": TIER_COLORS.get(ach["tier"], "#888"),
    }


def get_all_achievements(lang: str = "de") -> list:
    """Get all achievements with display info."""
    result = []
    for aid in ACHIEVEMENTS:
        info = get_achievement_info(aid, lang)
        if info:
            result.append(info)
    return sorted(result, key=lambda a: TIER_ORDER.get(a["tier"], 0))
