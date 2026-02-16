#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  THROWSYNC — Installer für Linux (Q4OS / Debian / Ubuntu)
# ═══════════════════════════════════════════════════════════════════

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  🎯 THROWSYNC — Installation${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
echo -e "Installationsordner: ${GREEN}$INSTALL_DIR${NC}"
echo ""

# ─── 1. System-Pakete ───────────────────────────────────────────────
echo -e "${YELLOW}[1/5] Prüfe System-Pakete...${NC}"

PACKAGES_NEEDED=""

if ! command -v python3 &> /dev/null; then
    PACKAGES_NEEDED="$PACKAGES_NEEDED python3"
fi

if ! command -v pip3 &> /dev/null; then
    # Check if python3-pip or python3-venv is available
    if ! python3 -m pip --version &> /dev/null 2>&1; then
        PACKAGES_NEEDED="$PACKAGES_NEEDED python3-pip python3-venv"
    fi
fi

# For serial/USB ESP flashing (optional but good to have)
if ! dpkg -l | grep -q python3-dev 2>/dev/null; then
    PACKAGES_NEEDED="$PACKAGES_NEEDED python3-dev"
fi

if [ -n "$PACKAGES_NEEDED" ]; then
    echo -e "  Installiere:${GREEN}$PACKAGES_NEEDED${NC}"
    sudo apt update -qq
    sudo apt install -y $PACKAGES_NEEDED
    echo -e "  ${GREEN}✓ System-Pakete installiert${NC}"
else
    echo -e "  ${GREEN}✓ Alles vorhanden${NC}"
fi

# ─── 2. Python Virtual Environment ──────────────────────────────────
echo ""
echo -e "${YELLOW}[2/5] Erstelle Python-Umgebung...${NC}"

VENV_DIR="$INSTALL_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo -e "  ${GREEN}✓ Virtual Environment erstellt: $VENV_DIR${NC}"
else
    echo -e "  ${GREEN}✓ Virtual Environment existiert bereits${NC}"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# ─── 3. Python-Abhängigkeiten ────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/5] Installiere Python-Abhängigkeiten...${NC}"

pip install --upgrade pip -q
pip install -r "$INSTALL_DIR/requirements.txt" -q

echo -e "  ${GREEN}✓ Alle Pakete installiert${NC}"

# Check what's installed
echo -e "  Python: $(python3 --version)"
echo -e "  FastAPI: $(pip show fastapi 2>/dev/null | grep Version | cut -d' ' -f2)"
echo -e "  aiohttp: $(pip show aiohttp 2>/dev/null | grep Version | cut -d' ' -f2)"

# ─── 4. Berechtigungen ──────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/5] Prüfe Berechtigungen...${NC}"

# Serial port access for ESP flashing
if groups | grep -q dialout; then
    echo -e "  ${GREEN}✓ dialout-Gruppe: OK (ESP-Flashing möglich)${NC}"
else
    echo -e "  ${YELLOW}⚠ Du bist nicht in der dialout-Gruppe (nötig für USB-ESP-Flashing)${NC}"
    echo -e "  ${YELLOW}  Falls du per USB flashen willst, führe aus:${NC}"
    echo -e "  ${YELLOW}  sudo usermod -a -G dialout $USER${NC}"
    echo -e "  ${YELLOW}  (danach neu einloggen)${NC}"
    echo ""
    read -p "  Jetzt zur dialout-Gruppe hinzufügen? (j/N): " ADD_DIALOUT
    if [[ "$ADD_DIALOUT" =~ ^[jJyY]$ ]]; then
        sudo usermod -a -G dialout "$USER"
        echo -e "  ${GREEN}✓ Hinzugefügt! Wird nach dem nächsten Login aktiv.${NC}"
    fi
fi

# Make scripts executable
chmod +x "$INSTALL_DIR/start.sh"
chmod +x "$INSTALL_DIR/install.sh"

# ─── 5. Autostart einrichten (optional) ─────────────────────────────
echo ""
echo -e "${YELLOW}[5/5] Autostart einrichten...${NC}"
echo ""
echo "  Möchtest du den LED Manager beim Systemstart automatisch starten?"
echo "  (Empfohlen wenn dein Rechner immer an den Dartboards hängt)"
echo ""
read -p "  Autostart einrichten? (j/N): " AUTOSTART

if [[ "$AUTOSTART" =~ ^[jJyY]$ ]]; then
    # Create systemd service
    SERVICE_FILE="/etc/systemd/system/throwsync.service"

    sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=ThrowSync
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python run.py
Restart=on-failure
RestartSec=5
Environment=PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable throwsync.service
    echo -e "  ${GREEN}✓ Autostart eingerichtet!${NC}"
    echo -e "  ${GREEN}  Dienst wird beim nächsten Neustart automatisch gestartet.${NC}"
    echo ""
    echo -e "  Nützliche Befehle:"
    echo -e "    ${BLUE}sudo systemctl start throwsync${NC}    → Jetzt starten"
    echo -e "    ${BLUE}sudo systemctl stop throwsync${NC}     → Stoppen"
    echo -e "    ${BLUE}sudo systemctl restart throwsync${NC}  → Neustart"
    echo -e "    ${BLUE}sudo systemctl status throwsync${NC}   → Status prüfen"
    echo -e "    ${BLUE}journalctl -u throwsync -f${NC}        → Live-Log"
    echo -e "    ${BLUE}sudo systemctl disable throwsync${NC}  → Autostart deaktivieren"
else
    echo -e "  Kein Autostart. Starte manuell mit: ${BLUE}./start.sh${NC}"
fi

# ─── Fertig! ─────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Installation abgeschlossen!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Get local IP
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo -e "  Starten:  ${BLUE}cd $INSTALL_DIR && ./start.sh${NC}"
echo -e "  Öffnen:   ${BLUE}http://localhost:8420${NC}"
if [ -n "$LOCAL_IP" ]; then
echo -e "  Netzwerk: ${BLUE}http://$LOCAL_IP:8420${NC}"
fi
echo ""
echo -e "  ${YELLOW}Nächste Schritte:${NC}"
echo -e "  1. ${GREEN}./start.sh${NC} ausführen"
echo -e "  2. Im Browser öffnen"
echo -e "  3. Unter 'Geräte' deinen Gledopto WLED Controller hinzufügen (IP eingeben)"
echo -e "  4. LED-Anzahl deines Strips einstellen"
echo -e "  5. Unter 'Autodarts' dein Board verbinden"
echo -e "  6. Fertig! 🎯"
echo ""

read -p "Jetzt starten? (J/n): " START_NOW
if [[ ! "$START_NOW" =~ ^[nN]$ ]]; then
    echo ""
    ./start.sh
fi
