#!/bin/bash
# ============================================================
#  BPTrading Mac One-Click Deploy
#  Supports: fresh install & upgrade (preserves user data)
#  Usage: bash deploy_mac.sh
# ============================================================
set -e
trap 'echo "[ERROR] Deploy failed at line $LINENO (cmd: $BASH_COMMAND)" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo "[ERROR] $1"; exit 1; }

echo ""
echo "============================================"
echo "  BPTrading - Mac One-Click Deploy"
echo "============================================"
echo ""

# ── 0. Stop running bot if upgrading ──
if [ -f "$SCRIPT_DIR/.bot.pid" ]; then
    OLD_PID=$(cat "$SCRIPT_DIR/.bot.pid")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        info "Stopping running bot (PID: $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$SCRIPT_DIR/.bot.pid"
fi
# Also kill any stray telegram_bot.py processes to avoid 409 Conflict
pkill -f "telegram_bot.py" 2>/dev/null || true
sleep 1

# ── 0.1 Pull latest code (preserve user data) ──
if [ -d "$PROJECT_DIR/.git" ]; then
    info "Existing installation detected, pulling latest code..."
    cd "$PROJECT_DIR"

    # ── Backup all user data before git operations ──
    BACKUP_DIR="$(mktemp -d)"
    PRESERVED=0

    # Files/dirs that must survive a git reset
    for item in \
        "$SCRIPT_DIR/config.py" \
        "$SCRIPT_DIR/telegram_session.json" \
        "$SCRIPT_DIR/auth.json" \
        "$SCRIPT_DIR/.bot.pid"
    do
        if [ -f "$item" ]; then
            cp "$item" "$BACKUP_DIR/" 2>/dev/null && PRESERVED=$((PRESERVED+1))
        fi
    done

    # screenshots/ directory (contains per-user auth.json + trade images)
    if [ -d "$SCRIPT_DIR/screenshots" ]; then
        cp -r "$SCRIPT_DIR/screenshots" "$BACKUP_DIR/screenshots" 2>/dev/null && PRESERVED=$((PRESERVED+1))
    fi

    # git pull / reset
    git stash -q 2>/dev/null || true
    git pull --ff-only origin main 2>/dev/null || {
        warn "Fast-forward pull failed, trying reset..."
        git fetch origin main
        git reset --hard origin/main
    }
    info "Code updated to latest version"

    # ── Restore user data ──
    for item in config.py telegram_session.json auth.json; do
        if [ -f "$BACKUP_DIR/$item" ]; then
            cp "$BACKUP_DIR/$item" "$SCRIPT_DIR/$item"
        fi
    done
    if [ -d "$BACKUP_DIR/screenshots" ]; then
        # Merge: keep new files added by git, restore user subdirs on top
        cp -rn "$BACKUP_DIR/screenshots/." "$SCRIPT_DIR/screenshots/" 2>/dev/null || \
        cp -r  "$BACKUP_DIR/screenshots"   "$SCRIPT_DIR/screenshots"  2>/dev/null || true
    fi
    rm -rf "$BACKUP_DIR"

    if [ $PRESERVED -gt 0 ]; then
        info "Preserved & restored $PRESERVED user data item(s) (config, sessions, auth, screenshots)"
    fi
fi

# ── 1. Check Python 3.10+ ──
info "[STEP 1] Checking Python..."
if command -v python3 &>/dev/null; then
    PY="python3"
elif command -v python &>/dev/null; then
    PY="python"
else
    error "Python3 not found. Install: brew install python3"
fi

PY_VERSION=$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PY -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PY -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
    error "Python 3.9+ required (found $PY_VERSION). Upgrade: brew install python3"
fi
info "Python $PY_VERSION OK"

# ── 2. Create virtual environment ──
info "[STEP 2] Virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    info "  Creating virtual environment..."
    $PY -m venv "$VENV_DIR"
    info "Virtual environment created at $VENV_DIR"
else
    info "Virtual environment exists at $VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python3"

# Verify venv python exists
if [ ! -x "$VENV_PY" ]; then
    # fallback: python (without 3)
    VENV_PY="$VENV_DIR/bin/python"
fi
if [ ! -x "$VENV_PY" ]; then
    error "venv python not found in $VENV_DIR/bin/ — delete .venv and re-run"
fi

# ── 3. Upgrade pip ──
info "[STEP 3] Upgrading pip..."
$VENV_PY -m pip install --upgrade pip -q

# ── 4. Install dependencies ──
info "[STEP 4] Installing dependencies..."
if [ ! -f "$PROJECT_DIR/requirements.txt" ]; then
    error "requirements.txt not found at $PROJECT_DIR/requirements.txt"
fi
$VENV_PY -m pip install -r "$PROJECT_DIR/requirements.txt" -q
info "  Dependencies installed"

# ── 5. Install Playwright browsers ──
info "[STEP 5] Installing Playwright Chromium..."
$VENV_PY -m playwright install chromium
info "Chromium installed"

# ── 6. Install Playwright system dependencies ──
info "[STEP 6] Playwright system deps..."
$VENV_PY -m playwright install-deps chromium 2>/dev/null || {
    warn "Could not auto-install system deps. If browser fails, run:"
    warn "  $VENV_PY -m playwright install-deps chromium"
}

# ── 7. Create screenshots directory ──
mkdir -p "$SCRIPT_DIR/screenshots"

# ── 8. Create config.py if not exists ──
if [ ! -f "$SCRIPT_DIR/config.py" ]; then
    if [ -f "$SCRIPT_DIR/config.example.py" ]; then
        cp "$SCRIPT_DIR/config.example.py" "$SCRIPT_DIR/config.py"
        # Auto-fill credentials
        sed -i '' 's/ACCOUNT = "your_account"/ACCOUNT = "33334444"/' "$SCRIPT_DIR/config.py"
        sed -i '' 's/PASSWORD = "your_password"/PASSWORD = "123456"/' "$SCRIPT_DIR/config.py"
        sed -i '' 's/TELEGRAM_BOT_TOKEN = "your_telegram_bot_token"/TELEGRAM_BOT_TOKEN = "8706026109:AAF1js4zVTy05jpHFAIhPSa9V-zCBnnJ6Uo"/' "$SCRIPT_DIR/config.py"
        info "config.py created with credentials auto-filled"
    else
        error "config.py and config.example.py both missing!"
    fi
else
    info "config.py exists"
fi

# ── 9. Create auth.json if not exists ──
if [ ! -f "$SCRIPT_DIR/auth.json" ]; then
    echo '{"cookies": [], "origins": []}' > "$SCRIPT_DIR/auth.json"
    info "auth.json created (empty session)"
fi

# ── 10. Create telegram_session.json if not exists ──
if [ ! -f "$SCRIPT_DIR/telegram_session.json" ]; then
    echo '{}' > "$SCRIPT_DIR/telegram_session.json"
    info "telegram_session.json created"
fi

# ── 11. Make shell scripts executable ──
chmod +x "$SCRIPT_DIR/start_bot_mac.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/stop_bot_mac.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/deploy_mac.sh" 2>/dev/null || true

# ── 12. Verify installation ──
info "[STEP 12] Verifying installation..."
$VENV_PY -c "
import sys
print(f'  Python: {sys.version}')
try:
    from importlib.metadata import version as pkg_version
    print(f'  Playwright: {pkg_version(\"playwright\")}')
except Exception:
    print('  Playwright: installed')
try:
    import psutil; print(f'  psutil: {psutil.__version__}')
except ImportError:
    print('  psutil: not installed (optional)')
print('  All OK!')
"

echo ""
echo "============================================"
echo -e "  ${GREEN}Deploy completed!${NC}"
echo "============================================"
echo ""
echo "  Start bot:  bash $SCRIPT_DIR/start_bot_mac.sh"
echo "  Stop bot:   bash $SCRIPT_DIR/stop_bot_mac.sh"
echo "  Config:     $SCRIPT_DIR/config.py"
echo ""

# Show preserved data summary
if [ -f "$SCRIPT_DIR/telegram_session.json" ] && [ "$(cat "$SCRIPT_DIR/telegram_session.json")" != "{}" ]; then
    SESSIONS=$($VENV_PY -c "import json; d=json.load(open('$SCRIPT_DIR/telegram_session.json')); print(len(d))" 2>/dev/null || echo "?")
    info "Preserved: $SESSIONS user session(s) in telegram_session.json"
fi
if [ -d "$SCRIPT_DIR/screenshots" ]; then
    USER_DIRS=$(find "$SCRIPT_DIR/screenshots" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
    if [ "$USER_DIRS" -gt 0 ]; then
        info "Preserved: $USER_DIRS user data dir(s) in screenshots/"
    fi
fi

echo ""
echo "  To upgrade later:  bash $SCRIPT_DIR/deploy_mac.sh"
echo "    (user data is preserved automatically)"
echo ""
