"""
Caller Sound Defaults — Every possible dart event gets its own sound slot.
Sound playback happens in the browser via HTML5 Audio API.
The backend broadcasts "play sound X" via WebSocket when events fire.
"""
MODULE_VERSION = "1.3.0"

# ═══════════════════════════════════════════════════════════════════════════════
# ALL CALLER SOUND EVENTS
# Each entry: key → {label, category, enabled, volume, sound}
#   sound = filename in sounds/ directory, URL, or null (no sound)
#   volume = 0.0–1.0 multiplier (relative to global caller volume)
# ═══════════════════════════════════════════════════════════════════════════════

CALLER_SOUND_EVENTS = {}

# ─── GAME EVENTS ──────────────────────────────────────────────────────────────
_game = {
    "caller_game_on":       {"label": "Game On!",                   "category": "game"},
    "caller_game_won":      {"label": "Gameshot! (Leg gewonnen)",   "category": "game"},
    "caller_match_won":     {"label": "Matchshot! (Match gewonnen)","category": "game"},
    "caller_busted":        {"label": "Überworfen / Busted",        "category": "game"},
    "caller_game_ended":    {"label": "Spiel beendet",             "category": "game"},
    "caller_player_change": {"label": "Spielerwechsel",            "category": "game"},
    "caller_next_throw":    {"label": "Bereit / Next",             "category": "game"},
}
CALLER_SOUND_EVENTS.update(_game)

# ─── SCORE CALLING (Rundenpunktzahl 0–180) ────────────────────────────────────
# The classic caller voice: "One hundred and eighty!", "Sixty!", etc.
for i in range(0, 181):
    special = {
        0: "Null / No Score", 3: "Drei", 7: "Sieben",
        26: "Bett & Frühstück (26)",
        100: "Ton (100)", 120: "Ton-Twenty (120)", 121: "Ton-Twenty-One",
        125: "Ton-Twenty-Five", 133: "Ton-Thirty-Three",
        140: "Ton-Forty (140)", 150: "Ton-Fifty (150)",
        153: "Ton-Fifty-Three", 156: "Ton-Fifty-Six",
        158: "Ton-Fifty-Eight", 160: "Ton-Sixty (160)",
        167: "Ton-Sixty-Seven", 170: "Ton-Seventy (170)",
        171: "Ton-Seventy-One", 174: "Ton-Seventy-Four",
        177: "Ton-Seventy-Seven", 180: "HUNDERTACHTZIG! (180)",
    }
    label = special.get(i, str(i))
    CALLER_SOUND_EVENTS[f"caller_score_{i}"] = {
        "label": label, "category": "score_calling",
    }

# ─── SINGLE DART — BY FIELD NAME ──────────────────────────────────────────────
# "Triple Twenty!", "Double Sixteen!", "Single Five!", etc.
for n in range(1, 21):
    CALLER_SOUND_EVENTS[f"caller_s{n}"] = {
        "label": f"Single {n}", "category": "single_dart_name",
    }
for n in range(1, 21):
    CALLER_SOUND_EVENTS[f"caller_d{n}"] = {
        "label": f"Double {n}", "category": "single_dart_name",
    }
for n in range(1, 21):
    CALLER_SOUND_EVENTS[f"caller_t{n}"] = {
        "label": f"Triple {n}", "category": "single_dart_name",
    }
CALLER_SOUND_EVENTS["caller_bull"] = {
    "label": "Single Bull (25)", "category": "single_dart_name",
}
CALLER_SOUND_EVENTS["caller_bullseye"] = {
    "label": "Bullseye / Double Bull (50)", "category": "single_dart_name",
}
CALLER_SOUND_EVENTS["caller_miss"] = {
    "label": "Miss / Außen (0)", "category": "single_dart_name",
}

# ─── SINGLE DART — GENERIC FALLBACK ───────────────────────────────────────────
# Used when no specific field sound exists
CALLER_SOUND_EVENTS["caller_single"] = {
    "label": "Single (generisch)", "category": "single_dart_generic",
}
CALLER_SOUND_EVENTS["caller_double"] = {
    "label": "Double (generisch)", "category": "single_dart_generic",
}
CALLER_SOUND_EVENTS["caller_triple"] = {
    "label": "Triple (generisch)", "category": "single_dart_generic",
}

# ─── SINGLE DART — SOUND EFFECTS ──────────────────────────────────────────────
# Effect sounds instead of voice (pling, boom, swoosh, etc.)
for n in range(1, 21):
    CALLER_SOUND_EVENTS[f"caller_effect_s{n}"] = {
        "label": f"Effekt Single {n}", "category": "single_dart_effect",
    }
for n in range(1, 21):
    CALLER_SOUND_EVENTS[f"caller_effect_d{n}"] = {
        "label": f"Effekt Double {n}", "category": "single_dart_effect",
    }
for n in range(1, 21):
    CALLER_SOUND_EVENTS[f"caller_effect_t{n}"] = {
        "label": f"Effekt Triple {n}", "category": "single_dart_effect",
    }
CALLER_SOUND_EVENTS["caller_effect_bull"] = {
    "label": "Effekt Bull", "category": "single_dart_effect",
}
CALLER_SOUND_EVENTS["caller_effect_bullseye"] = {
    "label": "Effekt Bullseye", "category": "single_dart_effect",
}
CALLER_SOUND_EVENTS["caller_effect_miss"] = {
    "label": "Effekt Miss", "category": "single_dart_effect",
}
CALLER_SOUND_EVENTS["caller_effect_single"] = {
    "label": "Effekt Single (generisch)", "category": "single_dart_effect",
}
CALLER_SOUND_EVENTS["caller_effect_double"] = {
    "label": "Effekt Double (generisch)", "category": "single_dart_effect",
}
CALLER_SOUND_EVENTS["caller_effect_triple"] = {
    "label": "Effekt Triple (generisch)", "category": "single_dart_effect",
}

# ─── AMBIENT / STIMMUNGS-SOUNDS ───────────────────────────────────────────────
# Background/celebration sounds that play alongside or after the main call
_ambient = {
    "caller_ambient_180":               {"label": "🎉 180! Feier-Sound",           "category": "ambient"},
    "caller_ambient_140_plus":          {"label": "🔥 140+ Aufnahme",               "category": "ambient"},
    "caller_ambient_ton_plus":          {"label": "💯 Ton+ (100+) Aufnahme",        "category": "ambient"},
    "caller_ambient_high_score":        {"label": "⭐ Hoher Score (120+)",           "category": "ambient"},
    "caller_ambient_low_score":         {"label": "😞 Niedriger Score (<20)",        "category": "ambient"},
    "caller_ambient_gameshot":          {"label": "🏆 Gameshot Feier",              "category": "ambient"},
    "caller_ambient_matchshot":         {"label": "🏆🏆 Matchshot Feier",           "category": "ambient"},
    "caller_ambient_busted":            {"label": "💥 Busted Sound",                "category": "ambient"},
    "caller_ambient_playerchange":      {"label": "🔄 Spielerwechsel",              "category": "ambient"},
    "caller_ambient_checkout_possible": {"label": "🎯 Checkout möglich",            "category": "ambient"},
    "caller_ambient_high_finish":       {"label": "🎯 High Finish (100+)",          "category": "ambient"},
    "caller_ambient_score_26":          {"label": "🛏️ Bett & Frühstück (26)",       "category": "ambient"},
    "caller_ambient_score_0":           {"label": "😶 Null Punkte",                 "category": "ambient"},
    "caller_ambient_bogey_number":      {"label": "🚫 Bogey Number (169 etc.)",     "category": "ambient"},
}
CALLER_SOUND_EVENTS.update(_ambient)

# ─── CHECKOUT ANSAGE ──────────────────────────────────────────────────────────
# "You require..." + checkout number
CALLER_SOUND_EVENTS["caller_you_require"] = {
    "label": "\"Du brauchst...\" (Prefix)", "category": "checkout",
}
# Individual checkout numbers (2–170, only valid checkout scores)
_valid_checkouts = list(range(2, 171))  # 2 through 170
for c in _valid_checkouts:
    CALLER_SOUND_EVENTS[f"caller_checkout_{c}"] = {
        "label": f"Checkout {c}", "category": "checkout",
    }

# ─── CRICKET ──────────────────────────────────────────────────────────────────
_cricket = {
    "caller_cricket_hit":       {"label": "Cricket: Ziel getroffen",    "category": "cricket"},
    "caller_cricket_closed":    {"label": "Cricket: Zahl geschlossen",  "category": "cricket"},
    "caller_cricket_miss":      {"label": "Cricket: Daneben",           "category": "cricket"},
    "caller_cricket_points":    {"label": "Cricket: Punkte erzielt",    "category": "cricket"},
}
CALLER_SOUND_EVENTS.update(_cricket)

# ─── BOARD / SYSTEM ───────────────────────────────────────────────────────────
_board = {
    "caller_takeout_start":     {"label": "Darts rausziehen",           "category": "board"},
    "caller_takeout_finished":  {"label": "Takeout fertig",             "category": "board"},
    "caller_board_ready":       {"label": "Board bereit",               "category": "board"},
    "caller_board_stopped":     {"label": "Board gestoppt",             "category": "board"},
}
CALLER_SOUND_EVENTS.update(_board)


# ─── Initialize defaults for all events ───────────────────────────────────────
for key, val in CALLER_SOUND_EVENTS.items():
    val.setdefault("enabled", True)
    val.setdefault("volume", 1.0)
    val.setdefault("sound", None)  # null = no sound file assigned


# ─── CATEGORY DEFINITIONS ─────────────────────────────────────────────────────
CALLER_CATEGORIES = {
    "game":                 {"label": "🎮 Spielereignisse",             "order": 1},
    "score_calling":        {"label": "🎙️ Score-Ansage (0–180)",        "order": 2},
    "single_dart_name":     {"label": "🎯 Einzelwurf — Feldname",       "order": 3},
    "single_dart_generic":  {"label": "🎯 Einzelwurf — Generisch",      "order": 4},
    "single_dart_effect":   {"label": "💫 Einzelwurf — Effekt-Sounds",   "order": 5},
    "ambient":              {"label": "🔊 Ambient / Stimmung",          "order": 6},
    "checkout":             {"label": "🎯 Checkout-Ansage",             "order": 7},
    "cricket":              {"label": "🏏 Cricket",                     "order": 8},
    "board":                {"label": "📡 Board / System",              "order": 9},
}


# ═══════════════════════════════════════════════════════════════════════════════
# CALLER CONFIGURATION DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_CALLER_CONFIG = {
    "enabled": False,                   # Caller master switch
    "volume": 0.8,                      # Global volume (0.0–1.0)
    "call_every_dart": 0,               # 0=off, 1=score, 2=name, 3=effect
    "call_every_dart_total_score": True, # Also call total after every dart
    "call_score_after_turn": True,       # Call round score when turn ends
    "ambient_sounds": True,              # Play ambient/celebration sounds
    "ambient_volume": 0.6,              # Ambient volume multiplier
    "checkout_call": True,              # Announce possible checkouts
    "checkout_call_repeat": 1,          # How many times to repeat checkout
}


def get_merged_caller(saved: dict) -> dict:
    """Merge saved caller sound customizations over defaults."""
    import copy
    result = {}
    for key, val in CALLER_SOUND_EVENTS.items():
        result[key] = copy.deepcopy(val)
    if saved:
        for key, val in saved.items():
            if key in result and isinstance(val, dict):
                result[key].update(val)
            elif key.startswith("caller_"):
                result[key] = val
    return result
