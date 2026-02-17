"""
Default Event → LED Mappings for Autodarts.
Standalone file with NO external dependencies — always importable.
"""

DEFAULT_EVENT_MAPPINGS = {
    # ═══════════════════════════════════════════════════════════════════
    # GAME EVENTS
    # ═══════════════════════════════════════════════════════════════════
    "game_on": {
        "label": "Game On! (Spiel startet)", "category": "game",
        "effect": {"fx": 9, "sx": 128, "ix": 128, "pal": 0, "col": [[0, 255, 0]], "bri": 200},
        "duration": 3.0, "enabled": True,
    },
    "game_won": {
        "label": "Leg gewonnen (Gameshot!)", "category": "game",
        "effect": {"fx": 44, "sx": 200, "ix": 200, "pal": 11, "col": [[255, 215, 0]], "bri": 255},
        "duration": 8.0, "enabled": True,
    },
    "match_won": {
        "label": "Match gewonnen (Matchshot!)", "category": "game",
        "effect": {"fx": 44, "sx": 255, "ix": 255, "pal": 6, "col": [[255, 215, 0], [255, 0, 0]], "bri": 255},
        "duration": 12.0, "enabled": True,
    },
    "game_ended": {
        "label": "Spiel beendet", "category": "game",
        "effect": {"fx": 0, "col": [[50, 50, 50]], "bri": 80},
        "duration": 2.0, "enabled": True,
    },
    "busted": {
        "label": "Überworfen (Busted!)", "category": "game",
        "effect": {"fx": 1, "sx": 200, "col": [[255, 0, 0]], "bri": 180},
        "duration": 3.0, "enabled": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # EINZELWURF - SEGMENT (Single / Double / Triple / Bull)
    # ═══════════════════════════════════════════════════════════════════
    "throw_single": {
        "label": "Single (S1–S20)", "category": "single_dart",
        "effect": {"fx": 0, "col": [[255, 255, 255]], "bri": 120},
        "duration": 1.0, "enabled": True,
    },
    "throw_double": {
        "label": "Double (D1–D20)", "category": "single_dart",
        "effect": {"fx": 2, "sx": 180, "col": [[0, 200, 255]], "bri": 200},
        "duration": 1.5, "enabled": True,
    },
    "throw_triple": {
        "label": "Triple (T1–T20)", "category": "single_dart",
        "effect": {"fx": 2, "sx": 200, "col": [[255, 0, 255]], "bri": 220},
        "duration": 2.0, "enabled": True,
    },
    "throw_bull": {
        "label": "Bull / Single Bull (25)", "category": "single_dart",
        "effect": {"fx": 23, "sx": 200, "col": [[0, 255, 100]], "bri": 200},
        "duration": 2.5, "enabled": True,
    },
    "throw_bullseye": {
        "label": "Bullseye / Double Bull (50)", "category": "single_dart",
        "effect": {"fx": 44, "sx": 255, "ix": 200, "col": [[255, 0, 0]], "bri": 255},
        "duration": 4.0, "enabled": True,
    },
    "throw_miss": {
        "label": "Miss / Bounce Out / Außen (0)", "category": "single_dart",
        "effect": {"fx": 0, "col": [[255, 0, 0]], "bri": 80},
        "duration": 1.5, "enabled": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # EINZELWURF - NACH ZAHL (S1–S20, D1–D20, T1–T20)
    # Standardmäßig deaktiviert — für Spezial-Trigger pro Feld
    # ═══════════════════════════════════════════════════════════════════
    **{f"throw_s{n}": {
        "label": f"Single {n}", "category": "single_dart_number",
        "effect": {"fx": 0, "col": [[255, 255, 255]], "bri": 120},
        "duration": 1.0, "enabled": False,
    } for n in range(1, 21)},
    **{f"throw_d{n}": {
        "label": f"Double {n}", "category": "single_dart_number",
        "effect": {"fx": 2, "sx": 180, "col": [[0, 200, 255]], "bri": 200},
        "duration": 1.5, "enabled": False,
    } for n in range(1, 21)},
    **{f"throw_t{n}": {
        "label": f"Triple {n}", "category": "single_dart_number",
        "effect": {"fx": 2, "sx": 200, "col": [[255, 0, 255]], "bri": 220},
        "duration": 2.0, "enabled": False,
    } for n in range(1, 21)},

    # ═══════════════════════════════════════════════════════════════════
    # DART-NUMMER (1., 2., 3. Dart einer Aufnahme)
    # ═══════════════════════════════════════════════════════════════════
    "dart_1": {
        "label": "1. Dart geworfen", "category": "dart_position",
        "effect": {"fx": 0, "col": [[200, 200, 200]], "bri": 100},
        "duration": 0.5, "enabled": False,
    },
    "dart_2": {
        "label": "2. Dart geworfen", "category": "dart_position",
        "effect": {"fx": 0, "col": [[200, 200, 200]], "bri": 120},
        "duration": 0.5, "enabled": False,
    },
    "dart_3": {
        "label": "3. Dart geworfen", "category": "dart_position",
        "effect": {"fx": 0, "col": [[200, 200, 200]], "bri": 140},
        "duration": 0.5, "enabled": False,
    },

    # ═══════════════════════════════════════════════════════════════════
    # RUNDEN-SCORE (Gesamtpunktzahl der Aufnahme)
    # ═══════════════════════════════════════════════════════════════════
    "score_180": {
        "label": "180!!!", "category": "round_score",
        "effect": {"fx": 44, "sx": 255, "ix": 255, "pal": 11, "col": [[255, 0, 0], [255, 215, 0]], "bri": 255},
        "duration": 10.0, "enabled": True,
    },
    "score_171_179": {
        "label": "171–179", "category": "round_score",
        "effect": {"fx": 44, "sx": 230, "ix": 230, "col": [[255, 50, 0]], "bri": 250},
        "duration": 6.0, "enabled": True,
    },
    "score_150_170": {
        "label": "150–170", "category": "round_score",
        "effect": {"fx": 44, "sx": 200, "ix": 200, "col": [[255, 80, 0]], "bri": 240},
        "duration": 5.0, "enabled": True,
    },
    "score_140_149": {
        "label": "140–149", "category": "round_score",
        "effect": {"fx": 44, "sx": 180, "ix": 180, "col": [[255, 100, 0]], "bri": 230},
        "duration": 4.0, "enabled": True,
    },
    "score_120_139": {
        "label": "120–139", "category": "round_score",
        "effect": {"fx": 9, "sx": 180, "ix": 150, "col": [[255, 150, 0]], "bri": 210},
        "duration": 3.5, "enabled": True,
    },
    "score_100_119": {
        "label": "100–119 (Ton)", "category": "round_score",
        "effect": {"fx": 9, "sx": 150, "ix": 128, "col": [[100, 255, 100]], "bri": 200},
        "duration": 3.0, "enabled": True,
    },
    "score_80_99": {
        "label": "80–99", "category": "round_score",
        "effect": {"fx": 0, "col": [[100, 200, 100]], "bri": 160},
        "duration": 2.0, "enabled": True,
    },
    "score_60_79": {
        "label": "60–79", "category": "round_score",
        "effect": {"fx": 0, "col": [[200, 200, 100]], "bri": 140},
        "duration": 1.5, "enabled": True,
    },
    "score_40_59": {
        "label": "40–59", "category": "round_score",
        "effect": {"fx": 0, "col": [[200, 200, 200]], "bri": 120},
        "duration": 1.0, "enabled": True,
    },
    "score_20_39": {
        "label": "20–39", "category": "round_score",
        "effect": {"fx": 0, "col": [[200, 150, 100]], "bri": 100},
        "duration": 1.0, "enabled": True,
    },
    "score_1_19": {
        "label": "1–19 (schlecht)", "category": "round_score",
        "effect": {"fx": 0, "col": [[200, 100, 50]], "bri": 80},
        "duration": 1.0, "enabled": True,
    },
    "score_0": {
        "label": "0 Punkte (kein Treffer)", "category": "round_score",
        "effect": {"fx": 1, "sx": 100, "col": [[150, 0, 0]], "bri": 80},
        "duration": 2.0, "enabled": True,
    },
    "score_26": {
        "label": "Bett & Frühstück (26)", "category": "round_score",
        "effect": {"fx": 23, "sx": 100, "col": [[150, 75, 0]], "bri": 120},
        "duration": 2.5, "enabled": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # CHECKOUT / FINISH
    # ═══════════════════════════════════════════════════════════════════
    "checkout_possible": {
        "label": "Checkout möglich (Rest ≤ 170)", "category": "checkout",
        "effect": {"fx": 2, "sx": 80, "col": [[0, 255, 0]], "bri": 180},
        "duration": 0, "enabled": True,
    },
    "checkout_hit": {
        "label": "Checkout getroffen!", "category": "checkout",
        "effect": {"fx": 44, "sx": 255, "ix": 255, "pal": 6, "col": [[0, 255, 0], [255, 255, 255]], "bri": 255},
        "duration": 8.0, "enabled": True,
    },
    "high_finish": {
        "label": "High Finish (≥ 100)", "category": "checkout",
        "effect": {"fx": 44, "sx": 255, "ix": 255, "pal": 11, "col": [[255, 215, 0], [255, 0, 0]], "bri": 255},
        "duration": 10.0, "enabled": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # SPIELERWECHSEL / DARTS GEZOGEN
    # ═══════════════════════════════════════════════════════════════════
    "player_change": {
        "label": "Spielerwechsel / Darts gezogen", "category": "turn",
        "effect": {"fx": 3, "sx": 200, "col": [[0, 100, 255]], "bri": 150},
        "duration": 2.0, "enabled": True,
    },
    "my_turn": {
        "label": "Ich bin dran (mein Wurf)", "category": "turn",
        "effect": {"fx": 0, "col": [[0, 255, 0]], "bri": 120},
        "duration": 0, "enabled": True,
    },
    "opponent_turn": {
        "label": "Gegner ist dran (warten)", "category": "turn",
        "effect": {"fx": 0, "col": [[30, 30, 30]], "bri": 40},
        "duration": 0, "enabled": True,
    },
    "next_throw": {
        "label": "Bereit für nächsten Wurf", "category": "turn",
        "effect": {"fx": 0, "col": [[100, 100, 100]], "bri": 100},
        "duration": 0, "enabled": True,
    },

    # ═══════════════════════════════════════════════════════════════════
    # TAKEOUT (Board-Erkennung: Darts rausziehen)
    # ═══════════════════════════════════════════════════════════════════
    "takeout_start": {
        "label": "Takeout gestartet (Darts rausziehen)", "category": "takeout",
        "effect": {"fx": 2, "sx": 100, "col": [[255, 255, 0]], "bri": 120},
        "duration": 0, "enabled": False,
    },
    "takeout_finished": {
        "label": "Takeout beendet", "category": "takeout",
        "effect": {"fx": 0, "col": [[100, 100, 100]], "bri": 80},
        "duration": 1.0, "enabled": False,
    },

    # ═══════════════════════════════════════════════════════════════════
    # CRICKET-SPEZIFISCH
    # ═══════════════════════════════════════════════════════════════════
    "cricket_hit": {
        "label": "Cricket: Ziel getroffen", "category": "cricket",
        "effect": {"fx": 2, "sx": 200, "col": [[0, 255, 0]], "bri": 200},
        "duration": 2.0, "enabled": False,
    },
    "cricket_closed": {
        "label": "Cricket: Zahl geschlossen", "category": "cricket",
        "effect": {"fx": 44, "sx": 200, "col": [[0, 255, 200]], "bri": 230},
        "duration": 3.0, "enabled": False,
    },
    "cricket_miss": {
        "label": "Cricket: Daneben (kein Ziel)", "category": "cricket",
        "effect": {"fx": 0, "col": [[200, 100, 0]], "bri": 80},
        "duration": 1.0, "enabled": False,
    },

    # ═══════════════════════════════════════════════════════════════════
    # AMBIENT / IDLE
    # ═══════════════════════════════════════════════════════════════════
    "idle": {
        "label": "Leerlauf / Wartemodus", "category": "ambient",
        "effect": {"fx": 9, "sx": 60, "ix": 128, "pal": 11, "col": [[128, 0, 255]], "bri": 80},
        "duration": 0, "enabled": True,
    },
}


def get_merged_events(saved: dict) -> dict:
    """Merge saved event customizations over defaults. Always returns full set."""
    import copy
    result = copy.deepcopy(DEFAULT_EVENT_MAPPINGS)
    if saved:
        for key, val in saved.items():
            if key in result and isinstance(val, dict):
                result[key].update(val)
            else:
                result[key] = val
    return result
