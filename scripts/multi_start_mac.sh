#!/bin/bash
# ============================================================
#  BPTrading - Start All Instances (Mac/Linux)
#  Usage: bash multi_start_mac.sh
#         bash multi_start_mac.sh 1 2    (start only instance 1 and 2)
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PY="$PROJECT_DIR/.venv/bin/python3"
INSTANCES_DIR="$SCRIPT_DIR/instances"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ ! -f "$VENV_PY" ]; then
    echo -e "${RED}ERROR: Virtual environment not found. Run deploy_mac.sh first.${NC}"
    exit 1
fi

# Determine which instances to start
if [ $# -gt 0 ]; then
    TARGETS=("$@")
else
    TARGETS=()
    for d in "$INSTANCES_DIR"/instance*; do
        if [ -d "$d" ] && [ -f "$d/config.py" ]; then
            name=$(basename "$d")
            num="${name#instance}"
            TARGETS+=("$num")
        fi
    done
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
    echo -e "${RED}No instances found in $INSTANCES_DIR${NC}"
    echo "Create instance directories with: mkdir -p $INSTANCES_DIR/instance1"
    exit 1
fi

echo "============================================"
echo "  BPTrading - Multi-Instance Start"
echo "============================================"
echo ""

started=0
for num in "${TARGETS[@]}"; do
    INST_DIR="$INSTANCES_DIR/instance${num}"
    PID_FILE="$INST_DIR/.bot.pid"

    if [ ! -d "$INST_DIR" ]; then
        echo -e "${RED}[Instance $num] Directory not found: $INST_DIR${NC}"
        continue
    fi

    if [ ! -f "$INST_DIR/config.py" ]; then
        echo -e "${RED}[Instance $num] config.py not found${NC}"
        continue
    fi

    # Check if token is configured
    if grep -q "YOUR_BOT_TOKEN" "$INST_DIR/config.py" 2>/dev/null; then
        echo -e "${YELLOW}[Instance $num] SKIPPED - Bot token not configured. Edit: $INST_DIR/config.py${NC}"
        continue
    fi

    # Check if already running
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo -e "${YELLOW}[Instance $num] Already running (PID: $OLD_PID)${NC}"
            continue
        else
            rm -f "$PID_FILE"
        fi
    fi

    # Create screenshots dir
    mkdir -p "$INST_DIR/screenshots"

    # Start watchdog with --instance flag
    cd "$SCRIPT_DIR"
    BP_INSTANCE_DIR="$INST_DIR" nohup "$VENV_PY" bot_watchdog.py --instance "$INST_DIR" >> "$INST_DIR/watchdog.log" 2>&1 &
    BOT_PID=$!
    echo "$BOT_PID" > "$PID_FILE"

    echo -e "${GREEN}[Instance $num] Started (PID: $BOT_PID)${NC}"
    echo "  Log: tail -f $INST_DIR/watchdog.log"
    started=$((started + 1))
done

echo ""
echo "Started $started instance(s)"
