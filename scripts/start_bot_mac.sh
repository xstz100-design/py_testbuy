#!/bin/bash
# ============================================================
#  BPTrading - Start Bot (Mac/Linux)
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PY="$PROJECT_DIR/.venv/bin/python3"
PID_FILE="$SCRIPT_DIR/.bot.pid"

if [ ! -f "$VENV_PY" ]; then
    echo "ERROR: Virtual environment not found. Run deploy_mac.sh first."
    exit 1
fi

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Bot is already running (PID: $OLD_PID)"
        echo "Use stop_bot_mac.sh to stop it first."
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

echo "Starting BPTrading bot..."
cd "$SCRIPT_DIR"

# Run in background with nohup
nohup "$VENV_PY" bot_watchdog.py >> "$SCRIPT_DIR/watchdog.log" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > "$PID_FILE"

echo "Bot started (PID: $BOT_PID)"
echo "Log: tail -f $SCRIPT_DIR/watchdog.log"
