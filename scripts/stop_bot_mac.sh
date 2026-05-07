#!/bin/bash
# ============================================================
#  BPTrading - Stop Bot (Mac/Linux)
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.bot.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found. Bot may not be running."
    # Scope search to this instance's script directory to avoid killing the other bot
    PIDS=$(pgrep -f "$SCRIPT_DIR/bot_watchdog.py" 2>/dev/null)
    if [ -n "$PIDS" ]; then
        echo "Found bot processes: $PIDS"
        kill $PIDS 2>/dev/null
        sleep 1
        kill -9 $PIDS 2>/dev/null
        echo "Killed bot processes."
    fi
    # Also kill child telegram_bot.py scoped to this instance
    PIDS2=$(pgrep -f "$SCRIPT_DIR" 2>/dev/null)
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

# Kill only children of this specific watchdog (not all telegram_bot.py globally)
CHILD_PIDS=$(pgrep -P "$PID" 2>/dev/null)
if [ -n "$CHILD_PIDS" ]; then
    kill $CHILD_PIDS 2>/dev/null
    sleep 1
    kill -9 $CHILD_PIDS 2>/dev/null
fi
# Also scope by SCRIPT_DIR in case watchdog already exited
SCOPED_PIDS=$(pgrep -f "$SCRIPT_DIR" 2>/dev/null)
if [ -n "$SCOPED_PIDS" ]; then
    kill $SCOPED_PIDS 2>/dev/null
    sleep 1
    kill -9 $SCOPED_PIDS 2>/dev/null
fi

rm -f "$PID_FILE"
echo "Bot stopped."
