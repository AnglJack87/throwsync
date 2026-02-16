# 🎯 ThrowSync

**Steuere deine WLED LED-Streifen über ESP32 — mit voller Autodarts-Integration.**

Ein All-in-One Tool zum Verwalten, Konfigurieren und Flashen von WLED-Geräten mit automatischen LED-Effekten für Autodarts-Events.

---

## ✨ Features

### 🔌 Multi-Device Management
- Mehrere ESP32/WLED-Geräte gleichzeitig verwalten
- Automatische Netzwerk-Erkennung (Subnetz-Scan)
- Verschiedene IPs und Netzwerke unterstützt
- Live-Status-Überwachung aller Geräte
- Geräte-Identifikation per LED-Blink

### 🎨 LED-Kontrolle
- **Farbe**: Direkte Farbauswahl mit Color Picker & Schnellfarben
- **Effekte**: Alle WLED-Effekte mit Speed, Intensität und Paletten
- **Individuelle LEDs**: Jede LED einzeln adressierbar und konfigurierbar
- **Segmente**: LED-Streifen in Segmente unterteilen
- **Helligkeit**: Globale und Segment-basierte Helligkeitssteuerung

### 🎯 Autodarts Integration
- WebSocket-Verbindung zu Autodarts API
- Automatische Event-Erkennung (Wurf, Score, Checkout, etc.)
- Vorkonfigurierte Events für alle gängigen Dart-Situationen:
  - **180!** → Firework-Effekt in Rot/Gold
  - **Bullseye** → Roter Blitz
  - **Triple** → Lila Breathe
  - **Checkout** → Grüne Explosion
  - **Miss** → Kurzes rotes Blinken
  - ...und viele mehr
- Jedes Event vollständig konfigurierbar (Effekt, Farbe, Dauer, Zielgeräte)
- Event-Test-Funktion ohne laufendes Spiel

### 💾 ESP32 Flasher
- WLED-Firmware direkt aus GitHub herunterladen
- ESP32 per USB flashen (alle ESP32-Varianten)
- Firmware-Backup erstellen und wiederherstellen
- Eigene Firmware-Dateien hochladen
- Automatische Port-Erkennung

### ⚡ Presets & Konfiguration
- LED-Zustände als Presets speichern & laden
- Komplette Konfiguration exportieren/importieren
- Auto-Connect für Autodarts
- Alle Einstellungen persistent gespeichert

---

## 🚀 Installation

### Linux (Q4OS / Debian / Ubuntu) — Empfohlen

```bash
# 1. Ordner herunterladen und entpacken, dann:
cd throwsync

# 2. Installer ausführen (macht alles automatisch)
chmod +x install.sh
./install.sh
```

Der Installer:
- Installiert Python3 + pip falls nötig (`sudo apt install`)
- Erstellt eine virtuelle Python-Umgebung (`venv/`)
- Installiert alle Abhängigkeiten (FastAPI, aiohttp, etc.)
- Fragt ob USB-Flashing-Rechte gesetzt werden sollen (dialout-Gruppe)
- Richtet optional Autostart als Systemdienst ein
- Startet am Ende den Server

**Danach:**
```bash
# Normaler Start (nach der Installation)
./start.sh

# Browser öffnen
# http://localhost:8420
# Oder im Netzwerk: http://<IP-deines-Rechners>:8420
```

**Autostart-Befehle (wenn bei Installation aktiviert):**
```bash
sudo systemctl start throwsync     # Jetzt starten
sudo systemctl stop throwsync      # Stoppen
sudo systemctl status throwsync    # Status prüfen
journalctl -u throwsync -f         # Live-Log anschauen
sudo systemctl disable throwsync   # Autostart deaktivieren
```

### Windows

```
1. Python installieren (python.org) — "Add to PATH" ankreuzen!
2. Diesen Ordner herunterladen/entpacken
3. start.bat doppelklicken
4. Browser öffnet sich automatisch
```

### Manueller Start (alle Systeme)

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Starten
python run.py
```

Der Server startet auf **http://localhost:8420** und ist auch im lokalen Netzwerk erreichbar.

---

## 📖 Nutzung

### 1. Geräte hinzufügen
- Öffne **"Geräte"** im Menü
- Klicke **"+ Gerät hinzufügen"** und gib die IP deines WLED-ESP32 ein
- Oder nutze **"Netzwerk scannen"** um WLED-Geräte automatisch zu finden

### 2. LEDs steuern
- Wähle unter **"LED Kontrolle"** ein Gerät aus
- Nutze die Tabs für Farbe, Effekte, individuelle LEDs oder Segmente
- Änderungen werden sofort auf den LED-Streifen angewendet

### 3. Autodarts verbinden
- Gehe zu **"Autodarts"**
- Trage deine Board ID und API Key ein (findest du auf autodarts.io unter Einstellungen)
- Klicke "Verbinden"

### 4. Events konfigurieren
- Unter **"Events & Effekte"** siehst du alle verfügbaren Dart-Events
- Klicke auf ✎ um Effekt, Farbe, Dauer und Zielgeräte anzupassen
- Nutze ▶ um Events zu testen ohne ein Spiel zu starten

### 5. ESP32 flashen (optional)
- Verbinde einen ESP32 per USB
- Gehe zu **"ESP Flasher"**
- Wähle Port und Firmware-Version
- Klicke "Flash starten"

---

## 🏗 Architektur

```
throwsync/
├── backend/
│   ├── main.py              # FastAPI Server & API Endpunkte
│   ├── wled_client.py        # WLED HTTP/JSON API Client
│   ├── device_manager.py     # Multi-Device Verwaltung
│   ├── autodarts_client.py   # Autodarts WebSocket & Event-Mapping
│   ├── esp_flasher.py        # ESP32 Flash/Backup via esptool
│   └── config_manager.py     # JSON Konfigurationsspeicher
├── frontend/
│   └── index.html            # Single-Page React Web-App
├── firmware/                  # Heruntergeladene Firmware-Dateien
├── requirements.txt
├── run.py                     # Hauptstartskript
├── start.bat                  # Windows Launcher
├── start.sh                   # Linux Launcher
└── README.md
```

**Technologie-Stack:**
- **Backend**: Python, FastAPI, aiohttp, esptool
- **Frontend**: React, Vanilla CSS (kein Build-Step nötig)
- **Kommunikation**: REST API + WebSocket für Live-Updates
- **Speicher**: JSON-Datei für persistente Konfiguration

---

## 🔧 API

Der Server bietet eine vollständige REST API auf Port 8420:

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/devices` | Alle Geräte auflisten |
| `POST /api/devices` | Gerät hinzufügen |
| `POST /api/devices/{id}/color` | Farbe setzen |
| `POST /api/devices/{id}/effect` | Effekt setzen |
| `POST /api/devices/{id}/individual` | Einzelne LEDs setzen |
| `GET /api/autodarts/status` | Autodarts-Status |
| `POST /api/autodarts/connect` | Autodarts verbinden |
| `GET /api/autodarts/events` | Event-Mappings abrufen |
| `POST /api/autodarts/test-event` | Event simulieren |
| `GET /api/flash/ports` | Serielle Ports auflisten |
| `POST /api/flash/start` | ESP32 flashen |

Vollständige API-Dokumentation unter: `http://localhost:8420/docs`

---

## 💡 Tipps

- **Mehrere Rechner**: Der Server ist im Netzwerk erreichbar. Du kannst von jedem Gerät im selben Netzwerk auf `http://<server-ip>:8420` zugreifen.
- **Mehrere ESP32**: Einfach alle per IP hinzufügen. Events können auf alle oder bestimmte Geräte gemappt werden.
- **WLED-Einstellungen**: Für beste Ergebnisse, setze in WLED die Überganszeit auf 0 (Einstellungen → LED Preferences → Transition).
- **Port ändern**: Setze die Umgebungsvariable `PORT=9999` vor dem Start.

---

## 📝 Lizenz

MIT License — Frei nutzbar, veränderbar, verteilbar.
