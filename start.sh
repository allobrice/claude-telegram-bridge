#!/bin/bash
# ============================================================================
# Claude Code ↔ Telegram Bridge - Script de lancement
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config/config.json"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🚀 Claude Code ↔ Telegram Bridge${NC}"
echo "=================================="

# Check config
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}❌ Config file not found!${NC}"
    echo "   cp config/config.example.json config/config.json"
    echo "   Then edit config/config.json with your values."
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 not found${NC}"
    exit 1
fi

# Check/install dependencies
echo -e "${YELLOW}📦 Checking dependencies...${NC}"
pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet --break-system-packages 2>/dev/null || \
pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet

# Start the bridge
echo -e "${GREEN}🌐 Starting bridge server...${NC}"
cd "$SCRIPT_DIR"
python3 src/bridge_server.py
