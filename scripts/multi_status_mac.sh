#!/bin/bash
# ============================================================
#  BPTrading - Multi-Instance Status
#  Usage: bash multi_status_mac.sh
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTANCES_DIR="$SCRIPT_DIR/instances"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo "  BPTrading - Instance Status"
echo "============================================"
echo ""

for d in "$INSTANCES_DIR"/instance*; do
    [ ! -d "$d" ] && continue
    name=$(basename "$d")
    num="${name#instance}"
    PID_FILE="$d/.bot.pid"

    # Check config
    if [ ! -f "$d/config.py" ]; then
        echo -e "[Instance $num] ${RED}NOT CONFIGURED${NC} - config.py missing"
        continue
    fi

    if grep -q "YOUR_BOT_TOKEN" "$d/config.py" 2>/dev/null; then
        echo -e "[Instance $num] ${YELLOW}TOKEN NOT SET${NC} - edit config.py"
        continue
    fi

    # Check running
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            # Get account from config
            ACCT=$(grep 'ACCOUNT' "$d/config.py" | head -1 | grep -o '"[^"]*"' | head -1 | tr -d '"')
            echo -e "[Instance $num] ${GREEN}RUNNING${NC} (PID: $PID) Account: $ACCT"
        else
            echo -e "[Instance $num] ${RED}DEAD${NC} (stale PID: $PID)"
        fi
    else
        echo -e "[Instance $num] ${YELLOW}STOPPED${NC}"
    fi
done

echo ""
