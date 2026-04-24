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

# Multi-instance support: BP_INSTANCE_DIR overrides config/data paths
_INSTANCE_DIR = Path(os.environ.get("BP_INSTANCE_DIR", "")).resolve() if os.environ.get("BP_INSTANCE_DIR") else None
if _INSTANCE_DIR:
    sys.path.insert(0, str(_INSTANCE_DIR))

from batch_trade import extract_result_from_output, parse_order_line
import config

# Try to import psutil for health checks
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = _INSTANCE_DIR if _INSTANCE_DIR else ROOT_DIR
TRADE_SCRIPT = ROOT_DIR / "trade.py"
BATCH_SCRIPT = ROOT_DIR / "batch_trade.py"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
_BOT_PID_FILE = DATA_DIR / ".bot.pid"  # module-level — accessible from poll_updates()

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
SESSION_FILE = DATA_DIR / "telegram_session.json"
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


def handle_withdraw_command(chat_id: str, text: str) -> tuple:
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

    worker = get_worker(chat_id)
    # Serialize withdrawals on the same website account
    lock = _get_account_lock(account)
    start_time = time.time()
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                   BP_SCREENSHOT_DIR=str(worker.screenshot_dir))
        with lock:
            proc = subprocess.run(
                command,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=env, cwd=str(ROOT_DIR), timeout=120,
            )
        result = extract_result_from_output(proc.stdout)
        shot = worker.latest_withdraw_screenshot(start_time)
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
        worker = get_worker(chat_id)
        return "Withdrawal timeout (120s)", worker.latest_withdraw_screenshot(start_time)
    except Exception as e:
        return f"Withdrawal error: {e}", None


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


# Global task ID counter (unique across all users)
_TASK_COUNTER = 0
_TASK_COUNTER_LOCK = threading.Lock()
BOT_START_TIME = time.time()


def _next_task_id() -> int:
    global _TASK_COUNTER
    with _TASK_COUNTER_LOCK:
        _TASK_COUNTER += 1
        return _TASK_COUNTER


# ── Account-level locks: same website account must be serialized ──
_ACCOUNT_LOCKS: dict[str, threading.Lock] = {}
_ACCOUNT_LOCKS_GUARD = threading.Lock()


def _get_account_lock(account: str) -> threading.Lock:
    """Get or create a lock for a specific website account.
    Trades on the same account are serialized; different accounts run in parallel."""
    with _ACCOUNT_LOCKS_GUARD:
        if account not in _ACCOUNT_LOCKS:
            _ACCOUNT_LOCKS[account] = threading.Lock()
        return _ACCOUNT_LOCKS[account]


class UserWorker:
    """Per-user execution context: own queue, worker thread, screenshot dir."""

    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        self.task_queue: queue.Queue = queue.Queue()
        self.task_list: List[TradeTask] = []
        self.task_list_lock = threading.Lock()
        self.current_task: Optional[TradeTask] = None
        self.current_process: Optional[subprocess.Popen] = None
        self.stop_flag = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.screenshot_dir = SCREENSHOT_DIR / chat_id
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def ensure_worker_running(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(
                target=self._worker_loop, daemon=True,
                name=f"worker-{self.chat_id}",
            )
            self.thread.start()

    def add_task(self, task: TradeTask) -> int:
        task.task_id = _next_task_id()
        with self.task_list_lock:
            self.task_list.append(task)
            self.task_queue.put(task)
            return len(self.task_list)

    def remove_task(self, task: TradeTask):
        with self.task_list_lock:
            if task in self.task_list:
                self.task_list.remove(task)

    def get_queue_info(self) -> List[dict]:
        with self.task_list_lock:
            return [
                {
                    "position": i + 1,
                    "task_id": t.task_id,
                    "text": t.text[:50] + ("..." if len(t.text) > 50 else ""),
                    "age": int(time.time() - t.created_at),
                }
                for i, t in enumerate(self.task_list)
            ]

    def cancel_task(self, position: int) -> Optional[TradeTask]:
        with self.task_list_lock:
            if position < 1 or position > len(self.task_list):
                return None
            return self.task_list.pop(position - 1)

    def clear_queue(self) -> int:
        with self.task_list_lock:
            count = len(self.task_list)
            self.task_list.clear()
            # Drain the queue but do NOT call task_done() here —
            # the worker loop calls task_done() after it pulls each item.
            # Pulled items will be skipped because they're no longer in task_list.
            drained: list = []
            while not self.task_queue.empty():
                try:
                    drained.append(self.task_queue.get_nowait())
                except queue.Empty:
                    break
            # Put back sentinel-free items so task_done counts stay balanced
            for _ in drained:
                self.task_queue.task_done()
            return count

    def stop_current(self) -> bool:
        self.stop_flag.set()
        if self.current_process is not None:
            try:
                self.current_process.terminate()
                time.sleep(0.5)
                if self.current_process.poll() is None:
                    self.current_process.kill()
                return True
            except Exception:
                pass
        return self.current_task is not None

    def format_queue_status(self) -> str:
        info = self.get_queue_info()
        if not info:
            if self.current_task:
                return f"Queue: empty\nRunning: {self.current_task.text}"
            return "Queue: empty\nStatus: Idle"
        lines = [f"Queue ({len(info)} pending):"]
        if self.current_task:
            lines.append(f"Running: {self.current_task.text[:40]}...")
        lines.append("")
        for item in info[:10]:
            lines.append(
                f"{item['position']}. [#{item['task_id']}] {item['text']} ({item['age']}s ago)"
            )
        if len(info) > 10:
            lines.append(f"... and {len(info) - 10} more")
        return "\n".join(lines)

    # ── Screenshot helpers ──

    def latest_screenshot(self, after_timestamp: Optional[float] = None) -> Optional[Path]:
        if not self.screenshot_dir.exists():
            return None
        candidates = [p for p in self.screenshot_dir.glob("*.png") if p.is_file()]
        if not candidates:
            return None
        if after_timestamp is not None:
            candidates = [p for p in candidates if p.stat().st_mtime > after_timestamp]
            if not candidates:
                return None
        return max(candidates, key=lambda f: f.stat().st_mtime)

    def latest_withdraw_screenshot(self, after_timestamp: float) -> Optional[Path]:
        if not self.screenshot_dir.exists():
            return None
        candidates = [
            f for f in self.screenshot_dir.glob("withdraw-*.png")
            if f.is_file() and f.stat().st_mtime > after_timestamp
        ]
        return max(candidates, key=lambda f: f.stat().st_mtime) if candidates else None

    def cleanup_old_screenshots(self):
        if not self.screenshot_dir.exists():
            return
        cutoff = time.time() - 3600
        for f in self.screenshot_dir.glob("*.png"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass

    # ── Command execution ──

    def run_command(self, command: list[str], timeout: int = 600) -> tuple:
        print(f"[execute][{self.chat_id}] Running: {' '.join(command)}")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                   BP_SCREENSHOT_DIR=str(self.screenshot_dir))
        self.stop_flag.clear()
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=str(ROOT_DIR),
            )
            self.current_process = proc
            start_time = time.time()
            stdout_chunks: list[str] = []
            stderr_chunks: list[str] = []
            assert proc.stdout is not None
            assert proc.stderr is not None

            def _read_stdout():
                for line in proc.stdout:  # type: ignore[union-attr]
                    stdout_chunks.append(line)

            def _read_stderr():
                for line in proc.stderr:  # type: ignore[union-attr]
                    stderr_chunks.append(line)

            t_out = threading.Thread(target=_read_stdout, daemon=True)
            t_err = threading.Thread(target=_read_stderr, daemon=True)
            t_out.start()
            t_err.start()

            while True:
                if self.stop_flag.is_set():
                    print(f"[execute][{self.chat_id}] Stop signal received")
                    proc.terminate()
                    time.sleep(0.5)
                    if proc.poll() is None:
                        proc.kill()
                    t_out.join(timeout=2)
                    t_err.join(timeout=2)
                    fake = subprocess.CompletedProcess(
                        args=command, returncode=-2, stdout="", stderr="Stopped by user"
                    )
                    return fake, {"status": "error", "message": "Task stopped by user"}

                if time.time() - start_time > timeout:
                    print(f"[execute][{self.chat_id}] TIMEOUT after {timeout}s")
                    proc.terminate()
                    time.sleep(0.5)
                    if proc.poll() is None:
                        proc.kill()
                    t_out.join(timeout=2)
                    t_err.join(timeout=2)
                    fake = subprocess.CompletedProcess(
                        args=command, returncode=-1, stdout="",
                        stderr=f"Timeout after {timeout}s",
                    )
                    return fake, {"status": "error", "message": f"Timeout after {timeout}s"}

                retcode = proc.poll()
                if retcode is not None:
                    t_out.join(timeout=5)
                    t_err.join(timeout=5)
                    break

                time.sleep(0.5)

            stdout_data = "".join(stdout_chunks)
            stderr_data = "".join(stderr_chunks)

            print(f"[execute][{self.chat_id}] Exit code: {retcode}")
            if stdout_data:
                print(f"[execute][{self.chat_id}] stdout (last 500): {stdout_data[-500:]}")
            if stderr_data:
                print(f"[execute][{self.chat_id}] stderr: {stderr_data[-300:]}")

            result = extract_result_from_output(stdout_data)
            if result is None:
                err_hint = (
                    stderr_data.strip()[-200:]
                    if stderr_data.strip()
                    else "No output from subprocess"
                )
                result = {"status": "error", "message": f"No JSON result returned\n{err_hint}"}
            if retcode != 0 and result.get("status") == "ok":
                result = {"status": "error", "message": f"Process exited with code {retcode}"}

            print(f"[execute][{self.chat_id}] Result: {result}")
            completed = subprocess.CompletedProcess(
                args=command, returncode=retcode, stdout=stdout_data, stderr=stderr_data,
            )
            return completed, result
        except Exception as e:
            print(f"[execute][{self.chat_id}] Error: {e}")
            fake = subprocess.CompletedProcess(
                args=command, returncode=-1, stdout="", stderr=str(e),
            )
            return fake, {"status": "error", "message": str(e)}
        finally:
            self.current_process = None

    def execute_single_order(self, order_text: str) -> tuple[str, dict]:
        order = parse_order_line(order_text)
        if order is None:
            raise ValueError(f"Invalid order: {order_text}")
        command = [
            sys.executable, str(TRADE_SCRIPT),
            "--mode", order.mode,
            "--currency", order.currency,
            "--amount", order.amount,
            "--direction", order.direction,
            "--duration", order.duration,
        ]
        session = get_session(self.chat_id)
        acc = _get_active_account(session)
        account = acc["account"] if acc else config.ACCOUNT
        if acc:
            command.extend(["--account", acc["account"], "--password", acc["password"]])

        lock = _get_account_lock(account)
        print(f"[lock][{self.chat_id}] Waiting for account lock: {account}")
        with lock:
            print(f"[lock][{self.chat_id}] Acquired account lock: {account}")
            _, result = self.run_command(command, timeout=300)
        print(f"[lock][{self.chat_id}] Released account lock: {account}")
        message = format_single_result(result, order_text)
        return message, result

    # ── Result + screenshot feedback ──

    def send_result_with_screenshot(self, message: str, result: dict, start_time: float):
        chat_id = self.chat_id
        shot = self.latest_screenshot(after_timestamp=start_time)
        if shot is not None:
            print(f"[task][{chat_id}] Found screenshot: {shot}")
            if send_photo(chat_id, shot, message):
                try:
                    shot.unlink()
                except Exception:
                    pass
        else:
            # No screenshot found after start_time — send text only, never use stale shots
            send_message(chat_id, message + "\n(No screenshot)")
        self.cleanup_old_screenshots()

    # ── Task handler ──

    def handle_task(self, task: TradeTask):
        try:
            session = get_session(task.chat_id)
            delay = session.get("delay", 0)
            mode, orders = parse_message_text(task.text, task.chat_id)
            total_orders = len(orders)

            print(f"[task][{self.chat_id}] Starting: {total_orders} order(s)")

            if mode == "single":
                start_time = time.time()
                send_message(task.chat_id, "Executing...", task.message_id)
                message, result = self.execute_single_order(orders[0])
                self.send_result_with_screenshot(message, result, start_time)
            else:
                send_message(
                    task.chat_id,
                    f"Batch started: {total_orders} orders (queued, sequential)",
                    task.message_id,
                )
                success_count = 0
                fail_count = 0

                # Serial queue: one browser per account at a time.
                # Orders run in the exact sequence provided.
                for i, order_text in enumerate(orders, 1):
                    if self.stop_flag.is_set():
                        send_message(task.chat_id, f"[{i}/{total_orders}] Stopped.")
                        break
                    start_time = time.time()
                    send_message(
                        task.chat_id, f"[{i}/{total_orders}] Executing: {order_text}"
                    )
                    try:
                        message, result = self.execute_single_order(order_text)
                        if result and result.get("status") == "ok":
                            success_count += 1
                        else:
                            fail_count += 1
                        self.send_result_with_screenshot(
                            f"[{i}/{total_orders}] {message}", result, start_time,
                        )
                    except Exception as e:
                        fail_count += 1
                        send_message(
                            task.chat_id, f"[{i}/{total_orders}] Error: {e}"
                        )

                send_message(
                    task.chat_id,
                    f"Batch completed: {success_count} OK / {fail_count} Failed",
                )

            if delay > 0 and mode == "single":
                time.sleep(delay)
        except Exception as exc:
            import traceback
            print(f"[task][{self.chat_id}] Error: {exc}")
            traceback.print_exc()
            send_message(task.chat_id, f"Trade failed\nError: {exc}", task.message_id)

    # ── Worker loop (per-user thread) ──

    def _worker_loop(self):
        print(f"[worker][{self.chat_id}] Worker thread started")
        while True:
            try:
                try:
                    task = self.task_queue.get(timeout=300)
                except queue.Empty:
                    print(f"[worker][{self.chat_id}] Idle 5min, thread exiting")
                    return

                if task is None:
                    self.task_queue.task_done()
                    break

                with self.task_list_lock:
                    if task not in self.task_list:
                        print(f"[worker][{self.chat_id}] Task #{task.task_id} cancelled")
                        self.task_queue.task_done()
                        continue

                self.current_task = task
                print(f"[worker][{self.chat_id}] Processing task #{task.task_id}")
                try:
                    self.handle_task(task)
                finally:
                    self.current_task = None
                    self.remove_task(task)
                self.task_queue.task_done()
                print(
                    f"[worker][{self.chat_id}] Task #{task.task_id} done, "
                    f"{self.task_queue.qsize()} remaining"
                )
            except Exception as exc:
                import traceback
                print(f"[worker][{self.chat_id}] Error: {exc}")
                traceback.print_exc()
                self.current_task = None
                try:
                    self.task_queue.task_done()
                except ValueError:
                    pass
                time.sleep(1)


# ── User worker registry ──
_USER_WORKERS: dict[str, UserWorker] = {}
_USER_WORKERS_LOCK = threading.Lock()


def get_worker(chat_id: str) -> UserWorker:
    """Get or create the per-user worker (lazy init)."""
    with _USER_WORKERS_LOCK:
        if chat_id not in _USER_WORKERS:
            _USER_WORKERS[chat_id] = UserWorker(chat_id)
        worker = _USER_WORKERS[chat_id]
    worker.ensure_worker_running()
    return worker


def get_health_status() -> str:
    """Get system health status aggregated across all users."""
    lines = ["[System Health]\n"]

    uptime_sec = int(time.time() - BOT_START_TIME)
    hours, remainder = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    lines.append(f"Uptime: {hours}h {minutes}m {seconds}s")

    # Aggregate user workers
    with _USER_WORKERS_LOCK:
        active_workers = len(_USER_WORKERS)
        total_pending = 0
        running_tasks = []
        for uid, w in _USER_WORKERS.items():
            total_pending += len(w.task_list)
            if w.current_task:
                running_tasks.append(f"  {uid}: {w.current_task.text[:30]}...")

    lines.append(f"Active users: {active_workers}")
    lines.append(f"Total pending: {total_pending}")
    if running_tasks:
        lines.append(f"Running ({len(running_tasks)}):")
        lines.extend(running_tasks)
    else:
        lines.append("Status: Idle")

    if HAS_PSUTIL:
        mem = psutil.virtual_memory()
        lines.append(
            f"Memory: {mem.percent:.1f}% "
            f"({mem.used // 1024 // 1024}MB / {mem.total // 1024 // 1024}MB)"
        )
        cpu = psutil.cpu_percent(interval=0.5)
        lines.append(f"CPU: {cpu:.1f}%")
        disk = psutil.disk_usage(str(ROOT_DIR))
        lines.append(
            f"Disk: {disk.percent:.1f}% ({disk.free // 1024 // 1024 // 1024}GB free)"
        )
        py_count = sum(
            1 for p in psutil.process_iter(["name"])
            if "python" in (p.info.get("name") or "").lower()  # type: ignore[attr-defined]
        )
        lines.append(f"Python processes: {py_count}")
    else:
        lines.append("(pip install psutil for detailed stats)")

    # Screenshots across all user dirs
    total_shots = 0
    total_size = 0
    if SCREENSHOT_DIR.exists():
        for f in SCREENSHOT_DIR.rglob("*.png"):
            total_shots += 1
            total_size += f.stat().st_size
    lines.append(f"Screenshots: {total_shots} ({total_size / 1024 / 1024:.1f}MB)")

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
    
    # Queue status (per-user)
    if cmd in {"queue", "q", "list", "ls"}:
        worker = get_worker(chat_id)
        send_message(chat_id, worker.format_queue_status(), message_id)
        return True
    
    # Clear queue (per-user)
    if cmd in {"clear", "clr", "cls", "empty"}:
        worker = get_worker(chat_id)
        count = worker.clear_queue()
        stopped = worker.stop_current()
        msg = f"Cleared {count} task(s) from queue"
        if stopped:
            msg += "\nStopped running task"
        send_message(chat_id, msg, message_id)
        return True
    
    # Cancel specific task (per-user)
    cancel_match = re.match(r"^(?:cancel|c)\s*(\d+)$", cmd)
    if cancel_match:
        pos = int(cancel_match.group(1))
        worker = get_worker(chat_id)
        task = worker.cancel_task(pos)
        if task:
            send_message(chat_id, f"Cancelled task #{task.task_id}: {task.text[:40]}...", message_id)
        else:
            send_message(chat_id, f"No task at position {pos}", message_id)
        return True
    
    # Stop current task (per-user)
    if cmd in {"stop", "abort", "kill"}:
        worker = get_worker(chat_id)
        if worker.stop_current():
            send_message(chat_id, "Stopping current task...", message_id)
        else:
            send_message(chat_id, "No task running", message_id)
        return True
    
    # Restart (per-user: reset user's worker only, not the whole bot)
    if cmd in {"restart", "reboot", "reload"}:
        worker = get_worker(chat_id)
        worker.stop_current()
        count = worker.clear_queue()
        # Kill worker thread so it restarts fresh on next task
        worker.task_queue.put(None)
        # Clear user screenshot cache
        worker.cleanup_old_screenshots()
        send_message(
            chat_id,
            f"Your environment has been reset\n"
            f"- Cleared {count} pending task(s)\n"
            f"- Stopped current task\n"
            f"- Worker thread will restart on next order",
            message_id,
        )
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
    payload: dict = {
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
    if parsed is None:
        return f"Trade result: {status}\n{result.get('message', '')}"
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
        shot_path = Path(shot_path) if shot_path and not isinstance(shot_path, Path) else shot_path
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
    """Poll for updates, route tasks to per-user workers.

    Telegram only allows ONE active getUpdates connection per token.
    Preemption policy:
    - Newly started instance should win.
    - Long-running instance should yield quickly after receiving 409.
    """
    _NEW_INSTANCE_GRAB_SECONDS = 20
    _OLD_INSTANCE_YIELD_AFTER_409 = 2
    _consecutive_409 = 0
    _boot_ts = time.time()

    # Keep 409 retry short to speed up takeover.
    _SLEEP_409_SECONDS = 1
    _SLEEP_OTHER_ERROR_SECONDS = 3


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
            # Successful poll → reset 409 counter
            _consecutive_409 = 0
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                task = extract_text_from_update(update)
                if task is None:
                    continue
                try:
                    mode, orders = parse_message_text(task.text, task.chat_id)
                except Exception:
                    send_message(
                        task.chat_id,
                        "Invalid order format\n\nExample: BTC 60 down 60s\n"
                        "Valid durations: 60s, 90s, 120s, 180s, 300s\n\nType /help for commands",
                        task.message_id,
                    )
                    continue

                worker = get_worker(task.chat_id)
                position = worker.add_task(task)
                label = "batch" if mode == "batch" else "single"
                send_message(
                    task.chat_id,
                    f"Queued {label} #{task.task_id} ({len(orders)} order(s))\nPosition: {position}",
                    task.message_id,
                )
        except error.URLError as exc:
            err_str = str(exc)
            if "409" in err_str or "Conflict" in err_str:
                _consecutive_409 += 1
                uptime = time.time() - _boot_ts

                # New instance: keep grabbing aggressively, do not exit.
                if uptime <= _NEW_INSTANCE_GRAB_SECONDS:
                    print(
                        f"[telegram] 409 Conflict (startup-grab, "
                        f"{_consecutive_409}) — retrying in {_SLEEP_409_SECONDS}s"
                    )
                    time.sleep(_SLEEP_409_SECONDS)
                    continue

                # Old instance: yield fast so the newer instance can take over.
                print(
                    f"[telegram] 409 Conflict (running {int(uptime)}s, "
                    f"{_consecutive_409}/{_OLD_INSTANCE_YIELD_AFTER_409})"
                )
                if _consecutive_409 >= _OLD_INSTANCE_YIELD_AFTER_409:
                    print("[bot] Newer instance detected. Exiting this older instance.")
                    try:
                        _BOT_PID_FILE.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise SystemExit(0)

                time.sleep(_SLEEP_409_SECONDS)
            else:
                _consecutive_409 = 0
                print(f"[telegram] Network error: {exc}")
                time.sleep(_SLEEP_OTHER_ERROR_SECONDS)
        except Exception as exc:
            _consecutive_409 = 0
            print(f"[telegram] Polling error: {exc}")
            time.sleep(_SLEEP_OTHER_ERROR_SECONDS)


def main():
    global BOT_START_TIME

    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    # ── Single-instance lock ──
    # _PID_FILE is defined at module level (below DATA_DIR)
    _lock_fh = None

    def _kill_old_instance(old_pid: int) -> None:
        """Gracefully stop an old bot instance, force-kill if needed."""
        import signal as _signal
        try:
            os.kill(old_pid, _signal.SIGTERM)
            print(f"[bot] Sent SIGTERM to old instance (PID {old_pid}), waiting...")
        except OSError:
            return
        for _ in range(30):  # wait up to 3 s
            time.sleep(0.1)
            try:
                os.kill(old_pid, 0)
            except OSError:
                return  # process gone
        # Still alive — force kill
        try:
            _sigkill = getattr(_signal, "SIGKILL", _signal.SIGTERM)  # SIGKILL is Unix-only
            os.kill(old_pid, _sigkill)
            print(f"[bot] Force-killed old instance (PID {old_pid})")
        except OSError:
            pass

    def _acquire_lock() -> None:
        nonlocal _lock_fh
        import platform
        if platform.system() == "Windows":
            # Windows: use a simple PID file (no fcntl)
            if _BOT_PID_FILE.exists():
                try:
                    old_pid = int(_BOT_PID_FILE.read_text().strip())
                    try:
                        import psutil
                        if psutil.pid_exists(old_pid):
                            print(f"[bot] Stopping previous instance (PID {old_pid})...")
                            import ctypes, subprocess as _sp
                            _sp.run(["taskkill", "/PID", str(old_pid), "/F"], capture_output=True)
                            time.sleep(1)
                    except ImportError:
                        pass
                except ValueError:
                    pass
            _BOT_PID_FILE.write_text(str(os.getpid()))
        else:
            # Unix: check PID file, kill old instance, then take the lock
            if _BOT_PID_FILE.exists():
                try:
                    old_pid = int(_BOT_PID_FILE.read_text().strip())
                    try:
                        os.kill(old_pid, 0)  # check if alive
                        print(f"[bot] Stopping previous instance (PID {old_pid})...")
                        _kill_old_instance(old_pid)
                    except OSError:
                        pass  # already gone
                except ValueError:
                    pass
                _BOT_PID_FILE.unlink(missing_ok=True)

            import fcntl as _fcntl
            _lock_fh = open(_BOT_PID_FILE, "w")
            _fcntl.flock(_lock_fh, _fcntl.LOCK_EX | _fcntl.LOCK_NB)  # type: ignore[attr-defined]
            _lock_fh.write(str(os.getpid()))
            _lock_fh.flush()

    def _release_lock() -> None:
        try:
            _BOT_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        if _lock_fh:
            try:
                _lock_fh.close()
            except Exception:
                pass

    _acquire_lock()

    load_sessions()
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    BOT_START_TIME = time.time()

    restart_count = 0
    max_restart_delay = 60

    while True:
        try:
            print("[telegram] Bot listener started (per-user concurrent mode)")
            print(
                f"[telegram] Allowed chats: "
                f"{sorted(ALLOWED_CHAT_IDS) if ALLOWED_CHAT_IDS else 'ALL'}"
            )
            if restart_count > 0:
                print(f"[telegram] Auto-restarted (attempt #{restart_count})")

            poll_updates()

        except KeyboardInterrupt:
            print("\n[telegram] Shutting down...")
            _release_lock()
            break
        except Exception as exc:
            import traceback
            restart_count += 1
            delay = min(5 * restart_count, max_restart_delay)
            print(f"[telegram] FATAL ERROR: {exc}")
            traceback.print_exc()
            print(f"[telegram] Restarting in {delay}s (attempt #{restart_count})...")
            time.sleep(delay)

    _release_lock()


if __name__ == "__main__":
    main()