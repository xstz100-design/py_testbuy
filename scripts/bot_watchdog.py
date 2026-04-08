"""Watchdog script for telegram_bot.py

Monitors the bot process and restarts it if it crashes.
Includes periodic health checks and maintenance.
Designed to run at Windows startup.

Usage:
    python bot_watchdog.py
"""
import subprocess
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BOT_SCRIPT = ROOT_DIR / "telegram_bot.py"
MAINTENANCE_SCRIPT = ROOT_DIR / "maintenance.py"
LOG_FILE = ROOT_DIR / "watchdog.log"

# Prefer .venv Python over system/anaconda Python
_VENV_PYTHON_WIN = ROOT_DIR.parent / ".venv" / "Scripts" / "python.exe"
_VENV_PYTHON_UNIX = ROOT_DIR.parent / ".venv" / "bin" / "python3"
if _VENV_PYTHON_WIN.exists():
    PYTHON_EXE = str(_VENV_PYTHON_WIN)
elif _VENV_PYTHON_UNIX.exists():
    PYTHON_EXE = str(_VENV_PYTHON_UNIX)
else:
    PYTHON_EXE = sys.executable

# Restart settings
MIN_RESTART_INTERVAL = 10  # Minimum seconds between restarts
MAX_RESTART_INTERVAL = 300  # Max backoff
RESET_AFTER_STABLE = 300  # Reset backoff after running this long without crash

# Maintenance settings
MAINTENANCE_INTERVAL = 1800  # Run maintenance every 30 minutes
HEALTH_CHECK_INTERVAL = 300  # Check health every 5 minutes

_last_maintenance = time.time()
_last_health_check = time.time()


def log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run_maintenance():
    """Run maintenance script."""
    global _last_maintenance
    try:
        subprocess.run(
            [PYTHON_EXE, str(MAINTENANCE_SCRIPT), "--cleanup"],
            cwd=str(ROOT_DIR),
            timeout=60,
            capture_output=True,
        )
        log("Maintenance completed")
    except Exception as e:
        log(f"Maintenance failed: {e}")
    _last_maintenance = time.time()


def check_health():
    """Check system health and log warnings."""
    global _last_health_check
    try:
        import psutil
        
        # Check memory
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            log(f"WARNING: High memory usage: {mem.percent}%")
        
        # Check disk
        disk = psutil.disk_usage(str(ROOT_DIR))
        if disk.percent > 95:
            log(f"WARNING: Low disk space: {100 - disk.percent}% free")
        
        # Check Python process count
        python_count = sum(1 for p in psutil.process_iter(['name']) 
                         if 'python' in p.info['name'].lower())
        if python_count > 10:
            log(f"WARNING: Many Python processes: {python_count}")
            
    except ImportError:
        pass  # psutil not available
    except Exception as e:
        log(f"Health check error: {e}")
    
    _last_health_check = time.time()


def periodic_tasks():
    """Run in background thread for periodic maintenance."""
    global _last_maintenance, _last_health_check
    while True:
        try:
            now = time.time()
            
            # Health check
            if now - _last_health_check > HEALTH_CHECK_INTERVAL:
                check_health()
            
            # Maintenance
            if now - _last_maintenance > MAINTENANCE_INTERVAL:
                run_maintenance()
            
            time.sleep(60)
        except Exception as e:
            log(f"Periodic task error: {e}")
            time.sleep(60)


def run_bot():
    """Run the bot and return exit code."""
    log(f"Starting bot: {BOT_SCRIPT}")
    try:
        process = subprocess.Popen(
            [PYTHON_EXE, str(BOT_SCRIPT)],
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        
        # Stream output to log
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                line = line.rstrip()
                try:
                    print(line)
                except Exception:
                    pass  # pythonw mode has no stdout
                # Also write to log file
                try:
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except Exception:
                    pass
        
        return process.returncode
    except Exception as e:
        log(f"Error running bot: {e}")
        return 1


def main():
    log("=" * 50)
    log("Watchdog started")
    log(f"Bot script: {BOT_SCRIPT}")
    log(f"Python: {PYTHON_EXE}")
    log("=" * 50)
    
    # Start periodic maintenance thread
    maintenance_thread = threading.Thread(target=periodic_tasks, daemon=True)
    maintenance_thread.start()
    log("Periodic maintenance thread started")
    
    # Run initial maintenance
    run_maintenance()
    
    restart_count = 0
    
    while True:
        start_time = time.time()
        exit_code = run_bot()
        run_duration = time.time() - start_time
        
        log(f"Bot exited with code {exit_code} after {run_duration:.1f}s")
        
        # Reset backoff if ran for a while without crashing
        if run_duration > RESET_AFTER_STABLE:
            restart_count = 0
            log("Process was stable, resetting restart counter")
        else:
            restart_count += 1
        
        # Calculate restart delay with exponential backoff
        delay = min(MIN_RESTART_INTERVAL * (2 ** min(restart_count - 1, 5)), MAX_RESTART_INTERVAL)
        
        log(f"Restarting in {delay}s (restart #{restart_count})...")
        time.sleep(delay)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Watchdog stopped by user")
