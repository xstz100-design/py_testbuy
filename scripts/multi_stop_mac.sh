#!/bin/bash
# ============================================================
#  BPTrading - Stop All Instances (Mac/Linux)
#  Usage: bash multi_stop_mac.sh
#         bash multi_stop_mac.sh 1 2    (stop only instance 1 and 2)
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTANCES_DIR="$SCRIPT_DIR/instances"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Determine which instances to stop
if [ $# -gt 0 ]; then
    TARGETS=("$@")
else
    TARGETS=()
    for d in "$INSTANCES_DIR"/instance*; do
        if [ -d "$d" ]; then
            name=$(basename "$d")
            num="${name#instance}"
            TARGETS+=("$num")
        fi
    done
fi

echo "============================================"
echo "  BPTrading - Multi-Instance Stop"
echo "============================================"
echo ""

stopped=0
for num in "${TARGETS[@]}"; do
    INST_DIR="$INSTANCES_DIR/instance${num}"
    PID_FILE="$INST_DIR/.bot.pid"

    if [ ! -f "$PID_FILE" ]; then
        echo -e "${YELLOW}[Instance $num] No PID file, not running${NC}"
        continue
    fi

    PID=$(cat "$PID_FILE")
    
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        sleep 1
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null
        fi
        echo -e "${GREEN}[Instance $num] Stopped (PID: $PID)${NC}"
        stopped=$((stopped + 1))
    else
        echo -e "${YELLOW}[Instance $num] Process $PID already dead${NC}"
    fi

    rm -f "$PID_FILE"
done

# Clean up any orphaned telegram_bot.py processes with BP_INSTANCE_DIR set
ORPHANS=$(pgrep -f "telegram_bot.py" 2>/dev/null)
if [ -n "$ORPHANS" ]; then
    echo ""
    echo "Cleaning up orphaned telegram_bot.py processes: $ORPHANS"
    kill $ORPHANS 2>/dev/null
    sleep 1
    kill -9 $ORPHANS 2>/dev/null
fi

echo ""
echo "Stopped $stopped instance(s)"
