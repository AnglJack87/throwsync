"""
ThrowSync — Internationalization (i18n)
Translations for DE, EN, NL, FR

Usage:
    from i18n import t, set_language, get_language, LANGUAGES
    set_language('en')
    t('nav.dashboard')  # → "Dashboard"
"""
MODULE_VERSION = "1.0.0"

LANGUAGES = {
    "de": {"label": "Deutsch", "flag": "\U0001F1E9\U0001F1EA"},
    "en": {"label": "English", "flag": "\U0001F1EC\U0001F1E7"},
    "nl": {"label": "Nederlands", "flag": "\U0001F1F3\U0001F1F1"},
    "fr": {"label": "Fran\u00e7ais", "flag": "\U0001F1EB\U0001F1F7"},
}

_current_language = "de"


TRANSLATIONS = {
    # ── Navigation ──
    "nav.dashboard": {
        "de": "Dashboard", "en": "Dashboard", "nl": "Dashboard", "fr": "Tableau de bord",
    },
    "nav.events": {
        "de": "Events & Caller", "en": "Events & Caller", "nl": "Events & Caller", "fr": "\u00c9v\u00e9nements & Caller",
    },
    "nav.devices": {
        "de": "Ger\u00e4te", "en": "Devices", "nl": "Apparaten", "fr": "Appareils",
    },
    "nav.settings": {
        "de": "Einstellungen", "en": "Settings", "nl": "Instellingen", "fr": "Param\u00e8tres",
    },

    # ── Tabs ──
    "tab.led": {
        "de": "LED Effekte", "en": "LED Effects", "nl": "LED Effecten", "fr": "Effets LED",
    },
    "tab.caller": {
        "de": "Caller Sounds", "en": "Caller Sounds", "nl": "Caller Geluiden", "fr": "Sons du Caller",
    },
    "tab.clips": {
        "de": "Clips", "en": "Clips", "nl": "Clips", "fr": "Clips",
    },
    "tab.crowd": {
        "de": "Crowd", "en": "Crowd", "nl": "Publiek", "fr": "Foule",
    },

    # ── Dashboard ──
    "dash.modules": {
        "de": "Module", "en": "Modules", "nl": "Modules", "fr": "Modules",
    },
    "dash.start": {
        "de": "Starten", "en": "Start", "nl": "Starten", "fr": "D\u00e9marrer",
    },
    "dash.stop": {
        "de": "Stoppen", "en": "Stop", "nl": "Stoppen", "fr": "Arr\u00eater",
    },
    "dash.running": {
        "de": "L\u00e4uft", "en": "Running", "nl": "Actief", "fr": "En cours",
    },
    "dash.stopped": {
        "de": "Gestoppt", "en": "Stopped", "nl": "Gestopt", "fr": "Arr\u00eat\u00e9",
    },
    "dash.connected": {
        "de": "Verbunden", "en": "Connected", "nl": "Verbonden", "fr": "Connect\u00e9",
    },
    "dash.disconnected": {
        "de": "Getrennt", "en": "Disconnected", "nl": "Niet verbonden", "fr": "D\u00e9connect\u00e9",
    },

    # ── Devices ──
    "dev.add": {
        "de": "Ger\u00e4t hinzuf\u00fcgen", "en": "Add Device", "nl": "Apparaat toevoegen", "fr": "Ajouter un appareil",
    },
    "dev.name": {
        "de": "Name", "en": "Name", "nl": "Naam", "fr": "Nom",
    },
    "dev.ip": {
        "de": "IP-Adresse", "en": "IP Address", "nl": "IP-adres", "fr": "Adresse IP",
    },
    "dev.scan": {
        "de": "Netzwerk scannen", "en": "Scan Network", "nl": "Netwerk scannen", "fr": "Scanner le r\u00e9seau",
    },
    "dev.delete": {
        "de": "L\u00f6schen", "en": "Delete", "nl": "Verwijderen", "fr": "Supprimer",
    },
    "dev.test": {
        "de": "Testen", "en": "Test", "nl": "Testen", "fr": "Tester",
    },

    # ── Events ──
    "ev.enabled": {
        "de": "Aktiviert", "en": "Enabled", "nl": "Ingeschakeld", "fr": "Activ\u00e9",
    },
    "ev.disabled": {
        "de": "Deaktiviert", "en": "Disabled", "nl": "Uitgeschakeld", "fr": "D\u00e9sactiv\u00e9",
    },
    "ev.edit": {
        "de": "Bearbeiten", "en": "Edit", "nl": "Bewerken", "fr": "Modifier",
    },
    "ev.save": {
        "de": "Speichern", "en": "Save", "nl": "Opslaan", "fr": "Enregistrer",
    },
    "ev.cancel": {
        "de": "Abbrechen", "en": "Cancel", "nl": "Annuleren", "fr": "Annuler",
    },
    "ev.reset": {
        "de": "Zur\u00fccksetzen", "en": "Reset", "nl": "Resetten", "fr": "R\u00e9initialiser",
    },
    "ev.filter_enabled": {
        "de": "Nur aktive anzeigen", "en": "Show enabled only", "nl": "Alleen actieve tonen", "fr": "Afficher les actifs uniquement",
    },

    # ── Event Categories ──
    "cat.game": {
        "de": "Spiel-Events", "en": "Game Events", "nl": "Spel Events", "fr": "\u00c9v\u00e9nements de jeu",
    },
    "cat.single_dart": {
        "de": "Einzelwurf (Segment-Typ)", "en": "Single Dart (Segment Type)", "nl": "Enkele worp (Segment-type)", "fr": "Fl\u00e9chette unique (Type de segment)",
    },
    "cat.single_dart_number": {
        "de": "Einzelwurf (nach Zahl)", "en": "Single Dart (by Number)", "nl": "Enkele worp (per nummer)", "fr": "Fl\u00e9chette unique (par num\u00e9ro)",
    },
    "cat.dart_position": {
        "de": "Dart-Position", "en": "Dart Position", "nl": "Dart positie", "fr": "Position de la fl\u00e9chette",
    },
    "cat.score_range": {
        "de": "Punktebereich (3-Dart)", "en": "Score Range (3-Dart)", "nl": "Puntenbereik (3-Dart)", "fr": "Plage de score (3-Dart)",
    },
    "cat.checkout": {
        "de": "Checkout-Ansagen", "en": "Checkout Calls", "nl": "Checkout Aankondigingen", "fr": "Annonces de Checkout",
    },
    "cat.turn": {
        "de": "Aufnahme-Events", "en": "Turn Events", "nl": "Beurt Events", "fr": "\u00c9v\u00e9nements de tour",
    },

    # ── Caller ──
    "caller.enabled": {
        "de": "Caller aktiv", "en": "Caller active", "nl": "Caller actief", "fr": "Caller actif",
    },
    "caller.volume": {
        "de": "Lautst\u00e4rke", "en": "Volume", "nl": "Volume", "fr": "Volume",
    },
    "caller.every_dart": {
        "de": "Jeden Dart ansagen", "en": "Call every dart", "nl": "Elke dart melden", "fr": "Annoncer chaque fl\u00e9chette",
    },
    "caller.score_after_turn": {
        "de": "Score nach Aufnahme", "en": "Score after turn", "nl": "Score na beurt", "fr": "Score apr\u00e8s le tour",
    },

    # ── Clips ──
    "clips.title": {
        "de": "Video- & GIF-Clips", "en": "Video & GIF Clips", "nl": "Video- & GIF-Clips", "fr": "Clips Vid\u00e9o & GIF",
    },
    "clips.upload": {
        "de": "Clip hochladen", "en": "Upload Clip", "nl": "Clip uploaden", "fr": "T\u00e9l\u00e9charger un clip",
    },
    "clips.assign": {
        "de": "Event \u2192 Clip Zuweisungen", "en": "Event \u2192 Clip Assignments", "nl": "Event \u2192 Clip Toewijzingen", "fr": "\u00c9v\u00e9nement \u2192 Assignation de clip",
    },
    "clips.no_clip": {
        "de": "Kein Clip", "en": "No Clip", "nl": "Geen Clip", "fr": "Aucun Clip",
    },
    "clips.duration": {
        "de": "Dauer", "en": "Duration", "nl": "Duur", "fr": "Dur\u00e9e",
    },
    "clips.seconds": {
        "de": "Sek.", "en": "sec.", "nl": "sec.", "fr": "sec.",
    },

    # ── Clip Events ──
    "clip.match_won": {
        "de": "Match gewonnen", "en": "Match Won", "nl": "Match gewonnen", "fr": "Match gagn\u00e9",
    },
    "clip.game_won": {
        "de": "Leg gewonnen", "en": "Leg Won", "nl": "Leg gewonnen", "fr": "Leg gagn\u00e9",
    },
    "clip.busted": {
        "de": "Bust", "en": "Bust", "nl": "Bust", "fr": "Bust",
    },
    "clip.game_on": {
        "de": "Game On", "en": "Game On", "nl": "Game On", "fr": "Game On",
    },
    "clip.180": {
        "de": "180!", "en": "180!", "nl": "180!", "fr": "180!",
    },
    "clip.high_score": {
        "de": "High Score (100+)", "en": "High Score (100+)", "nl": "Hoge Score (100+)", "fr": "Score \u00e9lev\u00e9 (100+)",
    },
    "clip.checkout_possible": {
        "de": "Checkout m\u00f6glich", "en": "Checkout Possible", "nl": "Checkout mogelijk", "fr": "Checkout possible",
    },
    "clip.miss": {
        "de": "Daneben (Miss)", "en": "Miss", "nl": "Mis", "fr": "Rat\u00e9",
    },
    "clip.bullseye": {
        "de": "Bullseye", "en": "Bullseye", "nl": "Bullseye", "fr": "Bullseye",
    },

    # ── Crowd ──
    "crowd.title": {
        "de": "Crowd Sound Engine", "en": "Crowd Sound Engine", "nl": "Publiek Geluidsengine", "fr": "Moteur de son de foule",
    },
    "crowd.desc": {
        "de": "Dynamische Publikums-Sounds die auf dein Spiel reagieren",
        "en": "Dynamic crowd sounds that react to your game",
        "nl": "Dynamische publieksgeluiden die reageren op je spel",
        "fr": "Sons de foule dynamiques qui r\u00e9agissent \u00e0 votre jeu",
    },
    "crowd.active": {
        "de": "Aktiv", "en": "Active", "nl": "Actief", "fr": "Actif",
    },
    "crowd.off": {
        "de": "Aus", "en": "Off", "nl": "Uit", "fr": "D\u00e9sactiv\u00e9",
    },
    "crowd.master_volume": {
        "de": "Master-Lautst\u00e4rke", "en": "Master Volume", "nl": "Hoofdvolume", "fr": "Volume principal",
    },
    "crowd.ambient": {
        "de": "Ambient", "en": "Ambient", "nl": "Ambient", "fr": "Ambiance",
    },
    "crowd.ambient_desc": {
        "de": "Hintergrund-Atmosph\u00e4re", "en": "Background atmosphere", "nl": "Achtergrond sfeer", "fr": "Atmosph\u00e8re de fond",
    },
    "crowd.positive": {
        "de": "Jubel", "en": "Cheering", "nl": "Gejuich", "fr": "Acclamations",
    },
    "crowd.positive_desc": {
        "de": "Positive Reaktionen auf gute Scores", "en": "Positive reactions to good scores", "nl": "Positieve reacties op goede scores", "fr": "R\u00e9actions positives aux bons scores",
    },
    "crowd.negative": {
        "de": "Entt\u00e4uschung", "en": "Disappointment", "nl": "Teleurstelling", "fr": "D\u00e9ception",
    },
    "crowd.negative_desc": {
        "de": "Reaktionen auf schlechte W\u00fcrfe", "en": "Reactions to bad throws", "nl": "Reacties op slechte worpen", "fr": "R\u00e9actions aux mauvais lancers",
    },
    "crowd.special": {
        "de": "Spezial", "en": "Special", "nl": "Speciaal", "fr": "Sp\u00e9cial",
    },
    "crowd.special_desc": {
        "de": "Besondere Momente", "en": "Special moments", "nl": "Bijzondere momenten", "fr": "Moments sp\u00e9ciaux",
    },
    "crowd.no_sound": {
        "de": "Kein Sound", "en": "No Sound", "nl": "Geen geluid", "fr": "Aucun son",
    },

    # ── Settings ──
    "set.language": {
        "de": "Sprache", "en": "Language", "nl": "Taal", "fr": "Langue",
    },
    "set.autodarts_login": {
        "de": "Autodarts Login", "en": "Autodarts Login", "nl": "Autodarts Login", "fr": "Connexion Autodarts",
    },
    "set.username": {
        "de": "Benutzername", "en": "Username", "nl": "Gebruikersnaam", "fr": "Nom d'utilisateur",
    },
    "set.password": {
        "de": "Passwort", "en": "Password", "nl": "Wachtwoord", "fr": "Mot de passe",
    },
    "set.connect": {
        "de": "Verbinden", "en": "Connect", "nl": "Verbinden", "fr": "Connecter",
    },
    "set.disconnect": {
        "de": "Trennen", "en": "Disconnect", "nl": "Ontkoppelen", "fr": "D\u00e9connecter",
    },
    "set.display_overlay": {
        "de": "Display Overlay", "en": "Display Overlay", "nl": "Display Overlay", "fr": "Overlay d'affichage",
    },
    "set.display_desc": {
        "de": "Zeigt Score-HUD, Clips und Event-Toasts direkt auf der Autodarts/Darthelfer Seite",
        "en": "Shows Score-HUD, Clips and Event-Toasts directly on the Autodarts/Darthelfer page",
        "nl": "Toont Score-HUD, Clips en Event-Toasts direct op de Autodarts/Darthelfer pagina",
        "fr": "Affiche le Score-HUD, les Clips et les Toasts directement sur la page Autodarts/Darthelfer",
    },
    "set.setup_bookmarklet": {
        "de": "Bookmarklet einrichten", "en": "Setup Bookmarklet", "nl": "Bookmarklet instellen", "fr": "Configurer le Bookmarklet",
    },
    "set.display_popup": {
        "de": "Display Popup", "en": "Display Popup", "nl": "Display Popup", "fr": "Popup d'affichage",
    },
    "set.copy_obs_url": {
        "de": "OBS URL kopieren", "en": "Copy OBS URL", "nl": "OBS URL kopi\u00ebren", "fr": "Copier l'URL OBS",
    },
    "set.test_overlay": {
        "de": "Overlay testen", "en": "Test Overlay", "nl": "Overlay testen", "fr": "Tester l'overlay",
    },
    "set.systeminfo": {
        "de": "Systeminfo", "en": "System Info", "nl": "Systeeminfo", "fr": "Info syst\u00e8me",
    },
    "set.server_access": {
        "de": "Server-Zugriff", "en": "Server Access", "nl": "Server Toegang", "fr": "Acc\u00e8s Serveur",
    },
    "set.server_access_desc": {
        "de": "\u00d6ffne ThrowSync auf anderen Ger\u00e4ten im Netzwerk:",
        "en": "Open ThrowSync on other devices in your network:",
        "nl": "Open ThrowSync op andere apparaten in je netwerk:",
        "fr": "Ouvrez ThrowSync sur d'autres appareils de votre r\u00e9seau:",
    },
    "set.update": {
        "de": "Update", "en": "Update", "nl": "Update", "fr": "Mise \u00e0 jour",
    },
    "set.check_update": {
        "de": "Nach Updates suchen", "en": "Check for Updates", "nl": "Controleren op updates", "fr": "V\u00e9rifier les mises \u00e0 jour",
    },
    "set.profiles": {
        "de": "Profile", "en": "Profiles", "nl": "Profielen", "fr": "Profils",
    },

    # ── Common ──
    "common.on": {
        "de": "An", "en": "On", "nl": "Aan", "fr": "Activ\u00e9",
    },
    "common.off": {
        "de": "Aus", "en": "Off", "nl": "Uit", "fr": "D\u00e9sactiv\u00e9",
    },
    "common.save": {
        "de": "Speichern", "en": "Save", "nl": "Opslaan", "fr": "Enregistrer",
    },
    "common.cancel": {
        "de": "Abbrechen", "en": "Cancel", "nl": "Annuleren", "fr": "Annuler",
    },
    "common.delete": {
        "de": "L\u00f6schen", "en": "Delete", "nl": "Verwijderen", "fr": "Supprimer",
    },
    "common.close": {
        "de": "Schlie\u00dfen", "en": "Close", "nl": "Sluiten", "fr": "Fermer",
    },
    "common.copied": {
        "de": "Kopiert!", "en": "Copied!", "nl": "Gekopieerd!", "fr": "Copi\u00e9!",
    },
    "common.error": {
        "de": "Fehler", "en": "Error", "nl": "Fout", "fr": "Erreur",
    },
    "common.success": {
        "de": "Erfolg", "en": "Success", "nl": "Succes", "fr": "Succ\u00e8s",
    },
    "common.loading": {
        "de": "Laden...", "en": "Loading...", "nl": "Laden...", "fr": "Chargement...",
    },
    "common.version": {
        "de": "Version", "en": "Version", "nl": "Versie", "fr": "Version",
    },
    "common.platform": {
        "de": "Plattform", "en": "Platform", "nl": "Platform", "fr": "Plateforme",
    },

    # ── Display Overlay / HUD ──
    "hud.turn_score": {
        "de": "Aufnahme", "en": "Turn", "nl": "Beurt", "fr": "Tour",
    },
    "hud.remaining": {
        "de": "Rest", "en": "Remaining", "nl": "Rest", "fr": "Restant",
    },
    "hud.last_throw": {
        "de": "Letzter Wurf", "en": "Last Throw", "nl": "Laatste worp", "fr": "Dernier lancer",
    },

    # ── Toasts / Events ──
    "toast.180": {
        "de": "180!", "en": "180!", "nl": "180!", "fr": "180!",
    },
    "toast.bullseye": {
        "de": "BULLSEYE!", "en": "BULLSEYE!", "nl": "BULLSEYE!", "fr": "BULLSEYE!",
    },
    "toast.match_won": {
        "de": "MATCH GEWONNEN!", "en": "MATCH WON!", "nl": "MATCH GEWONNEN!", "fr": "MATCH GAGN\u00c9!",
    },
    "toast.game_won": {
        "de": "LEG GEWONNEN!", "en": "LEG WON!", "nl": "LEG GEWONNEN!", "fr": "LEG GAGN\u00c9!",
    },
    "toast.busted": {
        "de": "BUST!", "en": "BUST!", "nl": "BUST!", "fr": "BUST!",
    },
    "toast.miss": {
        "de": "Daneben!", "en": "Miss!", "nl": "Mis!", "fr": "Rat\u00e9!",
    },
}


def set_language(lang: str):
    global _current_language
    if lang in LANGUAGES:
        _current_language = lang


def get_language() -> str:
    return _current_language


def t(key: str, lang: str = None) -> str:
    """Get translation for key in current or specified language."""
    lang = lang or _current_language
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(lang, entry.get("de", key))


def get_all_translations(lang: str = None) -> dict:
    """Get all translations for a language as flat dict."""
    lang = lang or _current_language
    result = {}
    for key, entry in TRANSLATIONS.items():
        result[key] = entry.get(lang, entry.get("de", key))
    return result
