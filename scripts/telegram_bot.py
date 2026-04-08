"""Telegram long-polling worker for BPTrading trade execution.

Features:
    - Listens for Telegram bot messages via Bot API long polling.
    - Parses single or batch trade instructions.
    - Queues tasks so only one trade runs at a time.
    - Executes trade.py or batch_trade.py locally.
    - Parses result blocks and sends the latest screenshot back to Telegram.
    - Management commands: restart, health, queue, clear, cancel, stop, help

Environment variables:
    TELEGRAM_BOT_TOKEN          Required bot token.
    TELEGRAM_ALLOWED_CHAT_IDS   Optional comma-separated chat IDs whitelist.
    TELEGRAM_POLL_TIMEOUT       Optional long-poll timeout seconds. Default: 30.
"""
import json
import os
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from urllib import error, parse, request

from batch_trade import extract_result_from_output, parse_order_line
import config

# Try to import psutil for health checks
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


ROOT_DIR = Path(__file__).resolve().parent
TRADE_SCRIPT = ROOT_DIR / "trade.py"
BATCH_SCRIPT = ROOT_DIR / "batch_trade.py"
SCREENSHOT_DIR = ROOT_DIR / "screenshots"

# Load bot token from env or config
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or getattr(config, "TELEGRAM_BOT_TOKEN", "")

# Load allowed chat IDs from env or config
_env_chats = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
if _env_chats:
    ALLOWED_CHAT_IDS = {item.strip() for item in _env_chats.split(",") if item.strip()}
else:
    ALLOWED_CHAT_IDS = {str(cid) for cid in getattr(config, "TELEGRAM_ALLOWED_CHAT_IDS", []) if cid}

POLL_TIMEOUT = int(os.environ.get("TELEGRAM_POLL_TIMEOUT", "30"))
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API_BASE = f"https://api.telegram.org/file/bot{BOT_TOKEN}"
ORDER_PATTERN = re.compile(
    r"^\s*[A-Za-z][A-Za-z0-9/ ]+\s+\d+(?:\.\d+)?\s+(?:up|down)\s+\d+s(?:\s+(?:desktop|mobile))?\s*$",
    re.I,
)

# Session state per chat: {chat_id: {"mode": "desktop", "delay": 0}}
SESSION_FILE = ROOT_DIR / "telegram_session.json"
CHAT_SESSION: dict[str, dict] = {}


def load_sessions():
    """Load saved sessions from file."""
    global CHAT_SESSION
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                CHAT_SESSION = json.load(f)
            print(f"[session] Loaded {len(CHAT_SESSION)} session(s) from {SESSION_FILE}")
        except Exception as e:
            print(f"[session] Failed to load sessions: {e}")
            CHAT_SESSION = {}


def save_sessions():
    """Save sessions to file."""
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(CHAT_SESSION, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[session] Failed to save sessions: {e}")


def get_session(chat_id: str) -> dict:
    """Get or create session state for a chat."""
    if chat_id not in CHAT_SESSION:
        CHAT_SESSION[chat_id] = {
            "mode": "desktop",
            "delay": 0,
            "accounts": [],
            "active_account": 0,
            "erc20": "",
            "wd_method": "usdt",
        }
        save_sessions()
    else:
        # Ensure existing sessions have new fields
        s = CHAT_SESSION[chat_id]
        changed = False
        for key, default in [("accounts", []), ("active_account", 0), ("erc20", ""), ("wd_method", "usdt")]:
            if key not in s:
                s[key] = default
                changed = True
        if changed:
            save_sessions()
    return CHAT_SESSION[chat_id]


def _next_account_id(session: dict) -> int:
    """Return next available account ID."""
    existing_ids = [a["id"] for a in session.get("accounts", [])]
    return max(existing_ids, default=0) + 1


def _get_active_account(session: dict) -> Optional[dict]:
    """Return the active account dict or None."""
    aid = session.get("active_account", 0)
    if aid == 0:
        return None
    for a in session.get("accounts", []):
        if a["id"] == aid:
            return a
    return None


def handle_account_command(chat_id: str, text: str) -> Optional[str]:
    """Handle account management commands. Returns response message or None."""
    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    session = get_session(chat_id)

    # add=ACCOUNT,pass=PASSWORD  (case-insensitive keys)
    add_match = re.match(
        r'^add\s*=\s*(.+?)\s*,\s*pass\s*=\s*(.+)$', text_stripped, re.I
    )
    if add_match:
        acc_val = add_match.group(1).strip()
        pwd_val = add_match.group(2).strip()
        if not acc_val or not pwd_val:
            return "Format: add=ACCOUNT,pass=PASSWORD"
        # Check duplicate
        for a in session["accounts"]:
            if a["account"] == acc_val:
                return f"Account '{acc_val}' already exists (ID: {a['id']})"
        new_id = _next_account_id(session)
        session["accounts"].append({"id": new_id, "account": acc_val, "password": pwd_val})
        # Auto-activate if first account
        if session["active_account"] == 0:
            session["active_account"] = new_id
        save_sessions()
        active_mark = " (active)" if session["active_account"] == new_id else ""
        return f"Account added\nID: {new_id}\nAccount: {acc_val}{active_mark}\nTotal: {len(session['accounts'])} account(s)"

    # del=ACCOUNT_OR_ID
    del_match = re.match(r'^del\s*=\s*(.+)$', text_stripped, re.I)
    if del_match:
        val = del_match.group(1).strip()
        found = None
        for a in session["accounts"]:
            if str(a["id"]) == val or a["account"] == val:
                found = a
                break
        if not found:
            return f"Account '{val}' not found"
        session["accounts"].remove(found)
        if session["active_account"] == found["id"]:
            session["active_account"] = session["accounts"][0]["id"] if session["accounts"] else 0
        save_sessions()
        return f"Deleted account: {found['account']} (ID: {found['id']})\nRemaining: {len(session['accounts'])} account(s)"

    # acc=ACCOUNT_OR_ID  or  acc=0 (use default config account)
    acc_match = re.match(r'^acc\s*=\s*(.+)$', text_stripped, re.I)
    if acc_match:
        val = acc_match.group(1).strip()
        if val == "0":
            session["active_account"] = 0
            save_sessions()
            return f"Switched to default config account ({config.ACCOUNT})"
        found = None
        for a in session["accounts"]:
            if str(a["id"]) == val or a["account"] == val:
                found = a
                break
        if not found:
            return f"Account '{val}' not found. Use /accounts to see all."
        session["active_account"] = found["id"]
        save_sessions()
        return f"Active account switched to: {found['account']} (ID: {found['id']})"

    # /accounts or accounts
    if text_lower in {"/accounts", "accounts"}:
        accs = session.get("accounts", [])
        if not accs:
            lines = ["No accounts added.", f"Using default: {config.ACCOUNT}", "", "Add: add=ACCOUNT,pass=PASSWORD"]
        else:
            active_id = session.get("active_account", 0)
            lines = [f"Accounts ({len(accs)}):"]
            for a in accs:
                mark = " ← active" if a["id"] == active_id else ""
                lines.append(f"  {a['id']}. {a['account']}{mark}")
            if active_id == 0:
                lines.append(f"\nUsing default: {config.ACCOUNT}")
            lines.append("\nSwitch: acc=ID or acc=ACCOUNT")
            lines.append("Delete: del=ID or del=ACCOUNT")
            lines.append("Default config: acc=0")
        return "\n".join(lines)

    return None


def handle_withdraw_command(chat_id: str, text: str) -> Optional[str]:
    """Handle withdrawal setting commands. Returns response message or None."""
    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    session = get_session(chat_id)

    # erc20=ADDRESS
    erc20_match = re.match(r'^erc20\s*=\s*(.+)$', text_stripped, re.I)
    if erc20_match:
        addr = erc20_match.group(1).strip()
        if not addr:
            return "text", "Format: erc20=YOUR_WALLET_ADDRESS"
        session["erc20"] = addr
        save_sessions()
        return "text", f"ERC20 address set to: {addr}"

    # wdmethod=usdt or wdmethod=bank
    wd_method_match = re.match(r'^wdmethod\s*=\s*(usdt|bank)$', text_stripped, re.I)
    if wd_method_match:
        method = wd_method_match.group(1).lower()
        session["wd_method"] = method
        save_sessions()
        return "text", f"Withdrawal method set to: {method}"

    # wd=AMOUNT (execute withdrawal)
    wd_match = re.match(r'^wd\s*=\s*(\d+(?:\.\d+)?)$', text_stripped, re.I)
    if wd_match:
        amount = wd_match.group(1)
        erc20 = session.get("erc20", "")
        wd_method = session.get("wd_method", "usdt")
        if not erc20:
            return "text", "No ERC20 address set. Use: erc20=YOUR_ADDRESS first."
        # Get active account credentials
        acc = _get_active_account(session)
        if acc:
            account = acc["account"]
            password = acc["password"]
        else:
            account = config.ACCOUNT
            password = config.PASSWORD
        return "withdraw", _execute_withdraw(chat_id, amount, account, password, erc20, wd_method)

    return None, None


def _execute_withdraw(chat_id: str, amount: str, account: str, password: str,
                      erc20: str, wd_method: str) -> tuple[str, Optional[Path]]:
    """Execute a withdrawal via withdraw.py script. Returns (message, screenshot_path)."""
    withdraw_script = ROOT_DIR / "withdraw.py"
    if not withdraw_script.exists():
        return "withdraw.py not found", None

    command = [
        sys.executable,
        str(withdraw_script),
        "--account", account,
        "--password", password,
        "--amount", amount,
        "--erc20", erc20,
        "--method", wd_method,
    ]

    start_time = time.time()
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            command,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, cwd=str(ROOT_DIR), timeout=120,
        )
        result = extract_result_from_output(proc.stdout)
        # Find latest withdraw screenshot
        shot = _latest_withdraw_screenshot(start_time)
        if result and result.get("status") == "ok":
            msg = (
                f"Withdrawal submitted\n"
                f"Amount: {amount}\n"
                f"Method: {wd_method}\n"
                f"Address: {erc20[:10]}...{erc20[-6:]}\n"
                f"Message: {result.get('message', 'OK')}"
            )
            return msg, shot
        err = (result or {}).get("message", proc.stdout[-300:] if proc.stdout else "Unknown error")
        return f"Withdrawal failed\nError: {err}", shot
    except subprocess.TimeoutExpired:
        return "Withdrawal timeout (120s)", _latest_withdraw_screenshot(start_time)
    except Exception as e:
        return f"Withdrawal error: {e}", None


def _latest_withdraw_screenshot(after_timestamp: float) -> Optional[Path]:
    """Find the latest withdraw screenshot created after given timestamp."""
    if not SCREENSHOT_DIR.exists():
        return None
    candidates = [
        f for f in SCREENSHOT_DIR.glob("withdraw-*.png")
        if f.is_file() and f.stat().st_mtime > after_timestamp
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.stat().st_mtime)


def handle_setting_command(chat_id: str, text: str) -> Optional[str]:
    """Parse setting commands like mode=mobile, delay=5. Returns response message or None."""
    text_lower = text.lower().strip()
    session = get_session(chat_id)
    
    # Handle mode=mobile, mode=desktop, mode=0, mode=1
    mode_match = re.match(r"^mode\s*=\s*(mobile|desktop|0|1)$", text_lower)
    if mode_match:
        mode_value = mode_match.group(1)
        # Map 0/1 to desktop/mobile
        if mode_value == "0":
            new_mode = "desktop"
        elif mode_value == "1":
            new_mode = "mobile"
        else:
            new_mode = mode_value
        session["mode"] = new_mode
        save_sessions()
        return f"Default mode set to: {new_mode}\nAll future orders will use {new_mode} mode unless specified."
    
    # Handle delay=N
    delay_match = re.match(r"^delay\s*=\s*(\d+)$", text_lower)
    if delay_match:
        new_delay = int(delay_match.group(1))
        session["delay"] = new_delay
        save_sessions()
        return f"Default delay set to: {new_delay}s\nAfter each trade, bot will wait {new_delay}s before next operation."
    
    # Handle /settings or settings to show current settings
    if text_lower in {"/settings", "settings"}:
        acc = _get_active_account(session)
        acc_display = acc["account"] if acc else f"{config.ACCOUNT} (default)"
        erc20 = session.get("erc20", "") or "(not set)"
        wd_method = session.get("wd_method", "usdt")
        return (
            f"Current settings:\n"
            f"- Mode: {session['mode']}\n"
            f"- Delay: {session['delay']}s\n"
            f"- Account: {acc_display}\n"
            f"- ERC20: {erc20}\n"
            f"- WD Method: {wd_method}"
        )
    
    return None


def apply_session_defaults(chat_id: str, order_text: str) -> str:
    """Apply session default mode to an order if not explicitly specified."""
    session = get_session(chat_id)
    
    # Check if order already has mode specified
    if re.search(r"\b(desktop|mobile)\b", order_text, re.I):
        return order_text
    
    # Append default mode
    return f"{order_text} {session['mode']}"


@dataclass
class TradeTask:
    chat_id: str
    message_id: int
    text: str
    task_id: int = 0
    created_at: float = field(default_factory=time.time)


# Global queue management
TASK_QUEUE: queue.Queue = queue.Queue()
TASK_LIST: List[TradeTask] = []  # Shadow list for queue inspection
TASK_LIST_LOCK = threading.Lock()
TASK_COUNTER = 0
CURRENT_TASK: Optional[TradeTask] = None
CURRENT_PROCESS: Optional[subprocess.Popen] = None
STOP_CURRENT_FLAG = threading.Event()
BOT_START_TIME = time.time()


def get_next_task_id() -> int:
    global TASK_COUNTER
    TASK_COUNTER += 1
    return TASK_COUNTER


def add_task_to_queue(task: TradeTask) -> int:
    """Add task to queue and return its position."""
    task.task_id = get_next_task_id()
    with TASK_LIST_LOCK:
        TASK_LIST.append(task)
        TASK_QUEUE.put(task)
        return len(TASK_LIST)


def remove_task_from_list(task: TradeTask):
    """Remove task from shadow list when completed."""
    with TASK_LIST_LOCK:
        if task in TASK_LIST:
            TASK_LIST.remove(task)


def get_queue_info() -> List[dict]:
    """Get info about all tasks in queue."""
    with TASK_LIST_LOCK:
        result = []
        for i, task in enumerate(TASK_LIST):
            result.append({
                "position": i + 1,
                "task_id": task.task_id,
                "text": task.text[:50] + ("..." if len(task.text) > 50 else ""),
                "age": int(time.time() - task.created_at),
            })
        return result


def cancel_task_by_position(position: int) -> Optional[TradeTask]:
    """Cancel task at given position (1-based). Returns cancelled task or None."""
    with TASK_LIST_LOCK:
        if position < 1 or position > len(TASK_LIST):
            return None
        task = TASK_LIST.pop(position - 1)
        # Note: Cannot remove from queue.Queue, but worker will skip cancelled tasks
        return task


def clear_all_queue() -> int:
    """Clear all pending tasks. Returns count of cleared tasks."""
    with TASK_LIST_LOCK:
        count = len(TASK_LIST)
        TASK_LIST.clear()
        # Drain the queue
        while not TASK_QUEUE.empty():
            try:
                TASK_QUEUE.get_nowait()
                TASK_QUEUE.task_done()
            except queue.Empty:
                break
        return count


def stop_current_task() -> bool:
    """Stop the currently executing task. Returns True if there was a task to stop."""
    global CURRENT_PROCESS
    STOP_CURRENT_FLAG.set()
    if CURRENT_PROCESS is not None:
        try:
            CURRENT_PROCESS.terminate()
            time.sleep(0.5)
            if CURRENT_PROCESS.poll() is None:
                CURRENT_PROCESS.kill()
            return True
        except Exception:
            pass
    return CURRENT_TASK is not None


def get_health_status() -> str:
    """Get system health status as formatted string."""
    lines = ["[System Health]\n"]
    
    # Uptime
    uptime_sec = int(time.time() - BOT_START_TIME)
    hours, remainder = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    lines.append(f"Uptime: {hours}h {minutes}m {seconds}s")
    
    # Queue status
    queue_info = get_queue_info()
    lines.append(f"Queue: {len(queue_info)} task(s)")
    if CURRENT_TASK:
        lines.append(f"Running: {CURRENT_TASK.text[:30]}...")
    else:
        lines.append("Status: Idle")
    
    if HAS_PSUTIL:
        # Memory
        mem = psutil.virtual_memory()
        lines.append(f"Memory: {mem.percent:.1f}% ({mem.used // 1024 // 1024}MB / {mem.total // 1024 // 1024}MB)")
        
        # CPU
        cpu = psutil.cpu_percent(interval=0.5)
        lines.append(f"CPU: {cpu:.1f}%")
        
        # Disk
        disk = psutil.disk_usage(str(ROOT_DIR))
        lines.append(f"Disk: {disk.percent:.1f}% ({disk.free // 1024 // 1024 // 1024}GB free)")
        
        # Python processes
        py_count = sum(1 for p in psutil.process_iter(['name']) 
                      if 'python' in p.info['name'].lower())
        lines.append(f"Python processes: {py_count}")
    else:
        lines.append("(pip install psutil for detailed stats)")
    
    # Screenshots
    if SCREENSHOT_DIR.exists():
        screenshots = list(SCREENSHOT_DIR.glob("*.png"))
        total_size = sum(f.stat().st_size for f in screenshots) / 1024 / 1024
        lines.append(f"Screenshots: {len(screenshots)} ({total_size:.1f}MB)")
    
    return "\n".join(lines)


def format_queue_status() -> str:
    """Format queue status as string."""
    queue_info = get_queue_info()
    if not queue_info:
        if CURRENT_TASK:
            return f"Queue: empty\nRunning: {CURRENT_TASK.text}"
        return "Queue: empty\nStatus: Idle"
    
    lines = [f"Queue ({len(queue_info)} pending):"]
    if CURRENT_TASK:
        lines.append(f"Running: {CURRENT_TASK.text[:40]}...")
    lines.append("")
    
    for info in queue_info[:10]:  # Show max 10
        lines.append(f"{info['position']}. [#{info['task_id']}] {info['text']} ({info['age']}s ago)")
    
    if len(queue_info) > 10:
        lines.append(f"... and {len(queue_info) - 10} more")
    
    return "\n".join(lines)


def get_help_text(session: dict) -> str:
    """Get help text with all commands."""
    acc = _get_active_account(session)
    acc_display = acc["account"] if acc else f"{config.ACCOUNT} (default)"
    return f"""BPTrading Bot

[Order Format]
  BTC 60 down 60s
  ETH 100 up 90s mobile
  Batch: BTC 60 up 60s, ETH 50 down 120s
  Valid durations: 60s, 90s, 120s, 180s, 300s

[Settings]
  mode=mobile / mode=0
  mode=desktop / mode=1
  delay=5 (pause 5s after each trade)
  /settings

[Account Management]
  add=ACCOUNT,pass=PASSWORD
  del=ACCOUNT or del=ID
  acc=ACCOUNT or acc=ID (switch)
  acc=0 (use default config account)
  /accounts - list all accounts

[Withdrawal]
  erc20=YOUR_WALLET_ADDRESS
  wdmethod=usdt or wdmethod=bank
  wd=AMOUNT (execute withdrawal)

[Management]
  /health - system status
  /queue - view queue
  /clear - clear queue
  /cancel N - cancel task N
  /stop - stop current task
  /restart - restart bot

[Current]
  Mode: {session['mode']}
  Delay: {session['delay']}s
  Account: {acc_display}"""


def handle_management_command(chat_id: str, text: str, message_id: int) -> bool:
    """Handle management commands. Returns True if handled."""
    # Normalize: remove leading /, lowercase, strip
    cmd = text.lower().strip()
    if cmd.startswith("/"):
        cmd = cmd[1:]
    
    # Help
    if cmd in {"help", "start", "h", "?"}:
        session = get_session(chat_id)
        send_message(chat_id, get_help_text(session), message_id)
        return True
    
    # Health check
    if cmd in {"health", "status", "sta", "stat", "info"}:
        send_message(chat_id, get_health_status(), message_id)
        return True
    
    # Queue status
    if cmd in {"queue", "q", "list", "ls"}:
        send_message(chat_id, format_queue_status(), message_id)
        return True
    
    # Clear queue
    if cmd in {"clear", "clr", "cls", "empty"}:
        count = clear_all_queue()
        send_message(chat_id, f"Cleared {count} task(s) from queue", message_id)
        return True
    
    # Cancel specific task: cancel 2, cancel2, c2, c 2
    cancel_match = re.match(r"^(?:cancel|c)\s*(\d+)$", cmd)
    if cancel_match:
        pos = int(cancel_match.group(1))
        task = cancel_task_by_position(pos)
        if task:
            send_message(chat_id, f"Cancelled task #{task.task_id}: {task.text[:40]}...", message_id)
        else:
            send_message(chat_id, f"No task at position {pos}", message_id)
        return True
    
    # Stop current task
    if cmd in {"stop", "abort", "kill"}:
        if stop_current_task():
            send_message(chat_id, "Stopping current task...", message_id)
        else:
            send_message(chat_id, "No task running", message_id)
        return True
    
    # Restart bot
    if cmd in {"restart", "reboot", "reload"}:
        send_message(chat_id, "Restarting bot in 2 seconds...", message_id)
        # Schedule restart in background thread
        def do_restart():
            time.sleep(2)
            print("[bot] Restarting via os.execv...")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        threading.Thread(target=do_restart, daemon=True).start()
        return True
    
    return False


def telegram_api(method: str, data: Optional[dict] = None, files: Optional[dict] = None) -> dict:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    url = f"{API_BASE}/{method}"
    if files:
        boundary = f"bpbot-{int(time.time() * 1000)}"
        body = bytearray()
        fields = data or {}
        for key, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        for field_name, file_path in files.items():
            path = Path(file_path)
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{path.name}"\r\n'
                ).encode()
            )
            body.extend(b"Content-Type: image/png\r\n\r\n")
            body.extend(path.read_bytes())
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        req = request.Request(url, data=bytes(body))
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    else:
        payload = parse.urlencode(data or {}).encode("utf-8")
        req = request.Request(url, data=payload)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with request.urlopen(req, timeout=POLL_TIMEOUT + 10) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not parsed.get("ok"):
        raise RuntimeError(f"Telegram API error: {parsed}")
    return parsed["result"]


def send_message(chat_id: str, text: str, reply_to_message_id: Optional[int] = None):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    telegram_api("sendMessage", payload)


def send_photo(chat_id: str, photo_path: Path, caption: str) -> bool:
    """Send photo and return True if successful."""
    try:
        telegram_api(
            "sendPhoto",
            {"chat_id": chat_id, "caption": caption},
            {"photo": str(photo_path)},
        )
        return True
    except Exception as e:
        print(f"[telegram] Failed to send photo: {e}")
        # Fallback to text message if photo fails
        send_message(chat_id, f"{caption}\n\n(Screenshot upload failed: {e})")
        return False


def parse_message_text(text: str, chat_id: Optional[str] = None) -> tuple[str, list[str]]:
    # Normalize Chinese punctuation to English
    text = text.replace("，", ",").replace("、", ",").replace("；", ";")
    
    # Support both newline and comma as order separators
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        raise ValueError("Empty message")

    # Expand comma-separated orders within each line
    orders: list[str] = []
    for line in raw_lines:
        if "," in line:
            parts = [part.strip() for part in line.split(",") if part.strip()]
            orders.extend(parts)
        else:
            orders.append(line)

    if not orders:
        raise ValueError("Empty message")

    # Apply session defaults and validate all orders
    final_orders: list[str] = []
    for order in orders:
        if chat_id:
            order = apply_session_defaults(chat_id, order)
        parse_order_line(order)
        final_orders.append(order)

    if len(final_orders) == 1:
        return "single", final_orders

    return "batch", final_orders


def format_single_result(result: dict, original_text: str) -> str:
    status = result.get("status")
    parsed = parse_order_line(original_text)
    if status == "ok":
        return (
            f"Trade completed ({parsed.mode})\n"
            f"Currency: {parsed.currency}\n"
            f"Amount: {parsed.amount}\n"
            f"Direction: {parsed.direction}\n"
            f"Duration: {parsed.duration}s\n"
            f"Result: {result.get('wins', 0)}W / {result.get('losses', 0)}L"
        )
    return (
        f"Trade failed ({parsed.mode})\n"
        f"Currency: {parsed.currency}\n"
        f"Error: {result.get('message', 'Unknown error')}"
    )


def format_batch_result(result: dict) -> str:
    lines = [
        f"Batch completed: {result.get('total', 0)} orders",
        f"Status: {result.get('status', 'unknown')}",
    ]
    for index, item in enumerate(result.get("results", []), start=1):
        order = item.get("order", {})
        order_result = item.get("result", {})
        if order_result.get("status") == "ok":
            lines.append(
                f"{index}. {order.get('currency')} {order.get('amount')} {order.get('direction')} {order.get('duration')}s {order.get('mode')} -> {order_result.get('wins', 0)}W/{order_result.get('losses', 0)}L"
            )
        else:
            lines.append(
                f"{index}. {order.get('currency')} {order.get('amount')} {order.get('direction')} {order.get('duration')}s {order.get('mode')} -> ERROR: {order_result.get('message', 'Unknown error')}"
            )
    return "\n".join(lines)


def latest_screenshot(after_timestamp: Optional[float] = None) -> Optional[Path]:
    """Get the latest screenshot, optionally only those created after a given timestamp."""
    if not SCREENSHOT_DIR.exists():
        return None
    candidates = [path for path in SCREENSHOT_DIR.glob("*.png") if path.is_file()]
    if not candidates:
        return None
    
    if after_timestamp is not None:
        # Only consider screenshots created after the given timestamp
        candidates = [p for p in candidates if p.stat().st_mtime > after_timestamp]
        if not candidates:
            return None
    
    return max(candidates, key=lambda item: item.stat().st_mtime)


def run_command(command: list[str], timeout: int = 600) -> tuple[subprocess.CompletedProcess, dict]:
    """Run a command with timeout protection and support for interruption."""
    global CURRENT_PROCESS
    
    print(f"[execute] Running: {' '.join(command)}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    STOP_CURRENT_FLAG.clear()
    
    try:
        CURRENT_PROCESS = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(ROOT_DIR),
        )
        
        start_time = time.time()
        
        # Use a thread to read stdout/stderr to avoid pipe deadlock on Mac/Linux
        import threading
        stdout_chunks = []
        stderr_chunks = []
        
        def _read_stdout():
            for line in CURRENT_PROCESS.stdout:
                stdout_chunks.append(line)
        
        def _read_stderr():
            for line in CURRENT_PROCESS.stderr:
                stderr_chunks.append(line)
        
        t_out = threading.Thread(target=_read_stdout, daemon=True)
        t_err = threading.Thread(target=_read_stderr, daemon=True)
        t_out.start()
        t_err.start()
        
        while True:
            if STOP_CURRENT_FLAG.is_set():
                print("[execute] Stop signal received, terminating process")
                CURRENT_PROCESS.terminate()
                time.sleep(0.5)
                if CURRENT_PROCESS.poll() is None:
                    CURRENT_PROCESS.kill()
                t_out.join(timeout=2)
                t_err.join(timeout=2)
                fake_completed = subprocess.CompletedProcess(
                    args=command, returncode=-2, stdout="", stderr="Stopped by user"
                )
                return fake_completed, {"status": "error", "message": "Task stopped by user"}
            
            if time.time() - start_time > timeout:
                print(f"[execute] TIMEOUT: Command exceeded {timeout}s limit")
                CURRENT_PROCESS.terminate()
                time.sleep(0.5)
                if CURRENT_PROCESS.poll() is None:
                    CURRENT_PROCESS.kill()
                t_out.join(timeout=2)
                t_err.join(timeout=2)
                fake_completed = subprocess.CompletedProcess(
                    args=command, returncode=-1, stdout="", stderr=f"Timeout after {timeout}s"
                )
                return fake_completed, {"status": "error", "message": f"Timeout after {timeout}s"}
            
            retcode = CURRENT_PROCESS.poll()
            if retcode is not None:
                t_out.join(timeout=5)
                t_err.join(timeout=5)
                break
            
            time.sleep(0.5)
        
        stdout_data = "".join(stdout_chunks)
        stderr_data = "".join(stderr_chunks)
        
        print(f"[execute] Exit code: {retcode}")
        if stdout_data:
            print(f"[execute] stdout (last 500 chars): {stdout_data[-500:]}")
        if stderr_data:
            print(f"[execute] stderr: {stderr_data[-300:]}")
        
        result = extract_result_from_output(stdout_data)
        if result is None:
            result = {"status": "error", "message": "No JSON result returned"}
        if retcode != 0 and result.get("status") == "ok":
            result = {"status": "error", "message": f"Process exited with code {retcode}"}
        
        print(f"[execute] Result: {result}")
        completed = subprocess.CompletedProcess(
            args=command, returncode=retcode, stdout=stdout_data, stderr=stderr_data
        )
        return completed, result
        
    except Exception as e:
        print(f"[execute] Error: {e}")
        fake_completed = subprocess.CompletedProcess(
            args=command, returncode=-1, stdout="", stderr=str(e)
        )
        return fake_completed, {"status": "error", "message": str(e)}
    finally:
        CURRENT_PROCESS = None


def execute_single_order(order_text: str, chat_id: str) -> tuple[str, dict]:
    """Execute a single order and return (message, result)."""
    order = parse_order_line(order_text)
    command = [
        sys.executable,
        str(TRADE_SCRIPT),
        "--mode",
        order.mode,
        "--currency",
        order.currency,
        "--amount",
        order.amount,
        "--direction",
        order.direction,
        "--duration",
        order.duration,
    ]
    # Use active account if set
    session = get_session(chat_id)
    acc = _get_active_account(session)
    if acc:
        command.extend(["--account", acc["account"], "--password", acc["password"]])
    # 单笔交易最多 5 分钟
    _, result = run_command(command, timeout=300)
    message = format_single_result(result, order_text)
    return message, result


def handle_task(task: TradeTask):
    try:
        session = get_session(task.chat_id)
        delay = session.get("delay", 0)
        
        mode, orders = parse_message_text(task.text, task.chat_id)
        total_orders = len(orders)
        
        print(f"[task] Starting task: {total_orders} order(s)")
        
        if mode == "single":
            # Single order - same as before
            start_time = time.time()
            send_message(task.chat_id, "Executing...", task.message_id)
            message, result = execute_single_order(orders[0], task.chat_id)
            _send_result_with_screenshot(task.chat_id, message, result, start_time)
        else:
            # Batch orders - execute one by one with immediate feedback
            send_message(task.chat_id, f"Batch started: {total_orders} orders", task.message_id)
            
            success_count = 0
            fail_count = 0
            
            for i, order_text in enumerate(orders, 1):
                # Check if stop was requested
                if STOP_CURRENT_FLAG.is_set():
                    send_message(task.chat_id, f"Batch stopped at {i}/{total_orders}")
                    break
                
                start_time = time.time()
                send_message(task.chat_id, f"[{i}/{total_orders}] Executing: {order_text}")
                
                try:
                    message, result = execute_single_order(order_text, task.chat_id)
                    
                    if result.get("status") == "ok":
                        success_count += 1
                    else:
                        fail_count += 1
                    
                    # Immediate feedback with screenshot
                    _send_result_with_screenshot(task.chat_id, f"[{i}/{total_orders}] {message}", result, start_time)
                    
                except Exception as e:
                    fail_count += 1
                    send_message(task.chat_id, f"[{i}/{total_orders}] Error: {e}")
                
                # Apply delay between orders (except after last)
                if delay > 0 and i < total_orders:
                    time.sleep(delay)
            
            # Final summary
            send_message(task.chat_id, f"Batch completed: {success_count} OK / {fail_count} Failed")
        
        # Apply delay after task completion
        if delay > 0 and mode == "single":
            print(f"[telegram] Waiting {delay}s before next task...")
            time.sleep(delay)
            
    except Exception as exc:
        import traceback
        print(f"[task] Error: {exc}")
        traceback.print_exc()
        send_message(task.chat_id, f"Trade failed\nError: {exc}", task.message_id)


def _cleanup_old_screenshots():
    """Delete all screenshots older than 1 hour to prevent accumulation."""
    if not SCREENSHOT_DIR.exists():
        return
    cutoff = time.time() - 3600
    for f in SCREENSHOT_DIR.glob("*.png"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except Exception:
            pass


def _send_result_with_screenshot(chat_id: str, message: str, result: dict, start_time: float):
    """Helper to send result message with screenshot."""
    shot = latest_screenshot(after_timestamp=start_time)
    if shot is not None:
        print(f"[task] Found new screenshot: {shot}")
        if send_photo(chat_id, shot, message):
            try:
                shot.unlink()
                print(f"[task] Deleted screenshot: {shot}")
            except Exception as e:
                print(f"[task] Failed to delete screenshot: {e}")
    else:
        if result.get("status") == "ok":
            shot = latest_screenshot()
            if shot is not None:
                if send_photo(chat_id, shot, message):
                    try:
                        shot.unlink()
                    except Exception:
                        pass
            else:
                send_message(chat_id, message + "\n(No screenshot)")
        else:
            send_message(chat_id, message)
    # Clean up old screenshots after each trade
    _cleanup_old_screenshots()


def worker_loop():
    """Worker loop using global TASK_QUEUE."""
    global CURRENT_TASK
    print("[worker] Worker thread started")
    while True:
        try:
            pending = TASK_QUEUE.qsize()
            if pending > 0:
                print(f"[worker] {pending} task(s) waiting in queue")
            
            task = TASK_QUEUE.get()
            if task is None:
                TASK_QUEUE.task_done()
                break
            
            # Check if task was cancelled (not in TASK_LIST anymore)
            with TASK_LIST_LOCK:
                if task not in TASK_LIST:
                    print(f"[worker] Task #{task.task_id} was cancelled, skipping")
                    TASK_QUEUE.task_done()
                    continue
            
            CURRENT_TASK = task
            print(f"[worker] Processing task #{task.task_id} from chat {task.chat_id}")
            
            try:
                handle_task(task)
            finally:
                CURRENT_TASK = None
                remove_task_from_list(task)
            
            TASK_QUEUE.task_done()
            print(f"[worker] Task #{task.task_id} completed, {TASK_QUEUE.qsize()} remaining")
        except Exception as exc:
            import traceback
            print(f"[worker] Unhandled error in worker loop: {exc}")
            traceback.print_exc()
            CURRENT_TASK = None
            try:
                TASK_QUEUE.task_done()
            except ValueError:
                pass
            time.sleep(1)  # Brief pause before continuing


def extract_text_from_update(update: dict) -> Optional[TradeTask]:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None
    text = (message.get("text") or "").strip()
    if not text:
        return None

    chat_id = str(message["chat"]["id"])
    message_id = message.get("message_id")
    
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        return None

    # Handle management commands first (supports both /cmd and cmd)
    if handle_management_command(chat_id, text, message_id):
        return None
    
    # Check for account commands
    account_response = handle_account_command(chat_id, text)
    if account_response:
        send_message(chat_id, account_response, message_id)
        return None

    # Check for withdrawal commands
    wd_type, wd_response = handle_withdraw_command(chat_id, text)
    if wd_type == "text":
        send_message(chat_id, wd_response, message_id)
        return None
    elif wd_type == "withdraw":
        msg, shot_path = wd_response
        if shot_path and shot_path.exists():
            send_photo(chat_id, shot_path, msg)
            try:
                shot_path.unlink()
            except Exception:
                pass
        else:
            send_message(chat_id, msg, message_id)
        return None

    # Check for setting commands
    setting_response = handle_setting_command(chat_id, text)
    if setting_response:
        send_message(chat_id, setting_response, message_id)
        return None

    return TradeTask(chat_id=chat_id, message_id=message_id, text=text)


def poll_updates():
    """Poll for updates using global TASK_QUEUE."""
    offset = 0
    while True:
        try:
            updates = telegram_api(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": POLL_TIMEOUT,
                    "allowed_updates": json.dumps(["message", "edited_message"]),
                },
            )
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                task = extract_text_from_update(update)
                if task is None:
                    continue
                try:
                    mode, orders = parse_message_text(task.text, task.chat_id)
                except Exception:
                    session = get_session(task.chat_id)
                    send_message(
                        task.chat_id,
                        f"Invalid order format\n\nExample: BTC 60 down 60s\nValid durations: 60s, 90s, 120s, 180s, 300s\n\nType /help for commands",
                        task.message_id,
                    )
                    continue

                position = add_task_to_queue(task)
                label = "batch" if mode == "batch" else "single"
                send_message(
                    task.chat_id,
                    f"Queued {label} #{task.task_id} ({len(orders)} order(s))\nPosition: {position}",
                    task.message_id,
                )
        except error.URLError as exc:
            print(f"[telegram] Network error: {exc}")
            time.sleep(5)
        except Exception as exc:
            print(f"[telegram] Polling error: {exc}")
            time.sleep(5)


def main():
    global BOT_START_TIME
    
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    # Load saved sessions
    load_sessions()
    
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    BOT_START_TIME = time.time()
    
    # Auto-restart loop
    restart_count = 0
    max_restart_delay = 60
    
    while True:
        try:
            worker = threading.Thread(target=worker_loop, daemon=True)
            worker.start()

            print("[telegram] Bot listener started")
            print(f"[telegram] Queue worker ready. Allowed chats: {sorted(ALLOWED_CHAT_IDS) if ALLOWED_CHAT_IDS else 'ALL'}")
            if restart_count > 0:
                print(f"[telegram] Auto-restarted (attempt #{restart_count})")
            
            poll_updates()
            
        except KeyboardInterrupt:
            print("\n[telegram] Shutting down...")
            break
        except Exception as exc:
            import traceback
            restart_count += 1
            delay = min(5 * restart_count, max_restart_delay)
            print(f"[telegram] FATAL ERROR: {exc}")
            traceback.print_exc()
            print(f"[telegram] Restarting in {delay}s (attempt #{restart_count})...")
            time.sleep(delay)


if __name__ == "__main__":
    main()