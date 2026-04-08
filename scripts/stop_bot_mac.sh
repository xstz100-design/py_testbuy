#!/bin/bash
# ============================================================
#  BPTrading - Stop Bot (Mac/Linux)
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.bot.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found. Bot may not be running."
    # Try to find and kill anyway
    PIDS=$(pgrep -f "bot_watchdog.py" 2>/dev/null)
    if [ -n "$PIDS" ]; then
        echo "Found bot processes: $PIDS"
        kill $PIDS 2>/dev/null
        sleep 1
        kill -9 $PIDS 2>/dev/null
        echo "Killed bot processes."
    fi
    # Also kill telegram_bot.py
    PIDS2=$(pgrep -f "telegram_bot.py" 2>/dev/null)
    if [ -n "$PIDS2" ]; then
        kill $PIDS2 2>/dev/null
        sleep 1
        kill -9 $PIDS2 2>/dev/null
        echo "Killed telegram_bot processes."
    fi
    exit 0
fi

PID=$(cat "$PID_FILE")
echo "Stopping bot (PID: $PID)..."

# Kill the watchdog
kill "$PID" 2>/dev/null
sleep 1

# Force kill if still alive
if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null
fi

# Also kill any child telegram_bot.py processes
CHILD_PIDS=$(pgrep -f "telegram_bot.py" 2>/dev/null)
if [ -n "$CHILD_PIDS" ]; then
    kill $CHILD_PIDS 2>/dev/null
    sleep 1
    kill -9 $CHILD_PIDS 2>/dev/null
fi

rm -f "$PID_FILE"
echo "Bot stopped."
