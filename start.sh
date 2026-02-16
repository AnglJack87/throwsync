#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Read version
VERSION="?.?.?"
if [ -f "$SCRIPT_DIR/VERSION" ]; then
    VERSION=$(cat "$SCRIPT_DIR/VERSION" | tr -d '[:space:]')
fi

echo "========================================"
echo "  🎯 THROWSYNC v${VERSION}"
echo "========================================"
echo ""

# Use virtual environment if it exists (created by install.sh)
VENV_DIR="$SCRIPT_DIR/venv"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo "Python-Umgebung: venv"
fi

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 nicht gefunden!"
    echo ""
    echo "Führe zuerst die Installation aus:"
    echo "  ./install.sh"
    echo ""
    echo "Oder installiere manuell:"
    echo "  sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# Check if dependencies are installed
python3 -c "import fastapi" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Abhängigkeiten fehlen!"
    echo ""
    if [ -d "$VENV_DIR" ]; then
        echo "Installiere in venv..."
        pip install -r requirements.txt -q
    else
        echo "Führe zuerst die Installation aus:"
        echo "  ./install.sh"
        echo ""
        echo "Oder installiere manuell:"
        echo "  pip3 install -r requirements.txt --break-system-packages"
        exit 1
    fi
fi

# Dialout group hint
if ! groups | grep -q dialout 2>/dev/null; then
    echo "⚠  Tipp: Für USB-ESP-Flashing → sudo usermod -a -G dialout $USER"
    echo ""
fi

# Get IP for display
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "Server startet..."
echo "  Lokal:    http://localhost:8420"
if [ -n "$LOCAL_IP" ]; then
    echo "  Netzwerk: http://$LOCAL_IP:8420"
fi
echo ""

python3 run.py
