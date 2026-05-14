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
    "$SCRIPT_DIR/bptrading/config.py"
    "$SCRIPT_DIR/bptrading/auth.json"
    "$SCRIPT_DIR/bptrading/telegram_session.json"
    "$SCRIPT_DIR/bptrading/authorized_chats.json"
    "$SCRIPT_DIR/bptrading/auth_code.txt"
)

BACKUP_DIR="$SCRIPT_DIR/.userdata_backup"
mkdir -p "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR/bptrading"

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
        # Use path relative to SCRIPT_DIR as backup key (preserves subdir structure)
        rel="${f#$SCRIPT_DIR/}"
        dest="$BACKUP_DIR/$rel"
        mkdir -p "$(dirname "$dest")"
        cp "$f" "$dest"
        echo "  Backed up: $rel"
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
        rel="${f#$SCRIPT_DIR/}"
        src="$BACKUP_DIR/$rel"
        if [ -f "$src" ]; then
            mkdir -p "$(dirname "$f")"
            cp "$src" "$f"
            echo "  Restored: $rel"
        fi
    done
    exit 1
fi

# 4. Restore user data (git pull must not overwrite these)
echo ""
echo "[4/5] Restoring user data..."
for f in "${USER_DATA_FILES[@]}"; do
    rel="${f#$SCRIPT_DIR/}"
    src="$BACKUP_DIR/$rel"
    if [ -f "$src" ]; then
        mkdir -p "$(dirname "$f")"
        cp "$src" "$f"
        echo "  Restored: $rel"
    fi
done

# 5. Restart bot
echo ""
echo "[5/5] Starting bot..."
bash "$SCRIPT_DIR/start_bot_mac.sh"

echo ""
echo "=== Update complete ==="
