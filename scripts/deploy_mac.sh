#!/bin/bash
# ============================================================
#  BPTrading Mac One-Click Deploy
#  Usage: bash deploy_mac.sh
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo ""
echo "============================================"
echo "  BPTrading - Mac One-Click Deploy"
echo "============================================"
echo ""

# ── 1. Check Python 3.10+ ──
info "Checking Python..."
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

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    error "Python 3.10+ required (found $PY_VERSION). Upgrade: brew install python3"
fi
info "Python $PY_VERSION OK"

# ── 2. Create virtual environment ──
if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment..."
    $PY -m venv "$VENV_DIR"
    info "Virtual environment created at $VENV_DIR"
else
    info "Virtual environment exists at $VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"

# ── 3. Upgrade pip ──
info "Upgrading pip..."
$VENV_PY -m pip install --upgrade pip -q

# ── 4. Install dependencies ──
info "Installing dependencies..."
$VENV_PIP install -r "$PROJECT_DIR/requirements.txt" -q
info "Dependencies installed"

# ── 5. Install Playwright browsers ──
info "Installing Playwright Chromium browser..."
$VENV_PY -m playwright install chromium
info "Chromium installed"

# ── 6. Install Playwright system dependencies ──
info "Installing Playwright system deps (may require sudo)..."
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
        warn "config.py created from template - EDIT IT with your credentials!"
        warn "  nano $SCRIPT_DIR/config.py"
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
info "Verifying installation..."
$VENV_PY -c "
import sys
print(f'  Python: {sys.version}')
import playwright; print(f'  Playwright: {playwright.__version__}')
import psutil; print(f'  psutil: {psutil.__version__}')
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
echo "  IMPORTANT: Edit config.py with your:"
echo "    - ACCOUNT / PASSWORD"
echo "    - TELEGRAM_BOT_TOKEN"
echo ""
