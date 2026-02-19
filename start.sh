#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config/config.json"

echo "🚀 Claude Code ↔ Telegram Bridge"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Config file not found!"
    echo "   cp config/config.example.json config/config.json"
    exit 1
fi

pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet --break-system-packages 2>/dev/null || \
pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet

cd "$SCRIPT_DIR"
python3 src/bridge_server.py
