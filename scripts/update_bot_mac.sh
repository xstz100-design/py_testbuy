#!/bin/bash
# ============================================================
#  BPTrading - Safe Update (Mac/Linux)
#  Backs up user data → git pull → restore → restart bot
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── User data files that must never be overwritten by git ──
USER_DATA_FILES=(
    "$SCRIPT_DIR/config.py"
    "$SCRIPT_DIR/auth.json"
    "$SCRIPT_DIR/telegram_session.json"
    "$SCRIPT_DIR/authorized_chats.json"
    "$SCRIPT_DIR/auth_code.txt"
)

BACKUP_DIR="$SCRIPT_DIR/.userdata_backup"
mkdir -p "$BACKUP_DIR"

echo "=== BPTrading Safe Update ==="
echo "Project: $PROJECT_DIR"

# 1. Stop bot
echo ""
echo "[1/5] Stopping bot..."
bash "$SCRIPT_DIR/stop_bot_mac.sh"
sleep 1

# 2. Backup user data
echo ""
echo "[2/5] Backing up user data..."
for f in "${USER_DATA_FILES[@]}"; do
    if [ -f "$f" ]; then
        fname="$(basename "$f")"
        cp "$f" "$BACKUP_DIR/$fname"
        echo "  Backed up: $fname"
    fi
done

# 3. git pull
echo ""
echo "[3/5] Pulling latest code..."
cd "$PROJECT_DIR"
git pull
GIT_EXIT=$?
if [ $GIT_EXIT -ne 0 ]; then
    echo "ERROR: git pull failed (exit $GIT_EXIT). Aborting."
    echo "Restoring user data..."
    for f in "${USER_DATA_FILES[@]}"; do
        fname="$(basename "$f")"
        if [ -f "$BACKUP_DIR/$fname" ]; then
            cp "$BACKUP_DIR/$fname" "$f"
            echo "  Restored: $fname"
        fi
    done
    exit 1
fi

# 4. Restore user data (git pull must not overwrite these)
echo ""
echo "[4/5] Restoring user data..."
for f in "${USER_DATA_FILES[@]}"; do
    fname="$(basename "$f")"
    if [ -f "$BACKUP_DIR/$fname" ]; then
        cp "$BACKUP_DIR/$fname" "$f"
        echo "  Restored: $fname"
    fi
done

# 5. Restart bot
echo ""
echo "[5/5] Starting bot..."
bash "$SCRIPT_DIR/start_bot_mac.sh"

echo ""
echo "=== Update complete ==="
