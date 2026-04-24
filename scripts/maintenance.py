"""Maintenance utilities for long-running bot.

Handles:
- Log rotation and cleanup
- Old screenshot cleanup
- Memory monitoring
- Health checks

Usage:
    python maintenance.py              # Run all maintenance tasks
    python maintenance.py --cleanup    # Just cleanup old files
    python maintenance.py --status     # Show system status
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

ROOT_DIR = Path(__file__).resolve().parent
SCREENSHOT_DIRS = [
    ROOT_DIR / "screenshots",
    ROOT_DIR / "bptrading" / "screenshots",
]
LOG_FILES = [
    ROOT_DIR / "watchdog.log",
    ROOT_DIR / "bot.log",
]

# Import config if available
try:
    from config import STABILITY
except ImportError:
    STABILITY = {
        "log_max_bytes": 10 * 1024 * 1024,
        "log_backup_count": 5,
        "screenshot_retention_days": 3,
        "memory_warning_mb": 1024,
    }


def get_file_age_days(path: Path) -> float:
    """Get file age in days."""
    if not path.exists():
        return 0
    mtime = path.stat().st_mtime
    age_seconds = time.time() - mtime
    return age_seconds / 86400


def rotate_log(log_path: Path, max_bytes: int, backup_count: int):
    """Rotate log file if it exceeds max_bytes."""
    if not log_path.exists():
        return
    
    size = log_path.stat().st_size
    if size < max_bytes:
        return
    
    print(f"Rotating {log_path.name} ({size / 1024 / 1024:.1f} MB)")
    
    # Shift existing backups
    for i in range(backup_count - 1, 0, -1):
        old = log_path.with_suffix(f".{i}.log")
        new = log_path.with_suffix(f".{i + 1}.log")
        if old.exists():
            if new.exists():
                new.unlink()
            old.rename(new)
    
    # Move current to .1
    backup1 = log_path.with_suffix(".1.log")
    if backup1.exists():
        backup1.unlink()
    log_path.rename(backup1)
    
    # Create empty new log
    log_path.touch()
    print(f"  Created new {log_path.name}")


def cleanup_old_screenshots(retention_days: int):
    """Delete screenshots older than retention_days from all screenshot directories."""
    deleted = 0
    freed = 0
    
    for screenshot_dir in SCREENSHOT_DIRS:
        if not screenshot_dir.exists():
            continue
        for f in screenshot_dir.glob("*.png"):
            age = get_file_age_days(f)
            if age > retention_days:
                size = f.stat().st_size
                f.unlink()
                deleted += 1
                freed += size
    
    if deleted > 0:
        print(f"Deleted {deleted} old screenshots ({freed / 1024 / 1024:.1f} MB)")
    else:
        print(f"No screenshots older than {retention_days} days")


def cleanup_temp_files():
    """Clean up orphaned temp files and pycache."""
    deleted = 0
    freed = 0
    # Temp files
    patterns = ["tmp*.txt", "*.tmp"]
    for pattern in patterns:
        for f in ROOT_DIR.glob(pattern):
            age = get_file_age_days(f)
            if age > 0.04:  # Older than ~1 hour
                freed += f.stat().st_size
                f.unlink()
                deleted += 1
    # __pycache__ cleanup
    for cache_dir in ROOT_DIR.rglob("__pycache__"):
        for f in cache_dir.glob("*.pyc"):
            age = get_file_age_days(f)
            if age > 1:
                freed += f.stat().st_size
                f.unlink()
                deleted += 1
    if deleted > 0:
        print(f"Deleted {deleted} temp/cache files ({freed / 1024:.1f} KB)")


def get_system_status() -> dict:
    """Get current system status."""
    status = {
        "timestamp": datetime.now().isoformat(),
        "python_pid": os.getpid(),
    }
    
    if HAS_PSUTIL:
        # Memory
        mem = psutil.virtual_memory()
        status["memory_total_mb"] = mem.total / 1024 / 1024
        status["memory_used_mb"] = mem.used / 1024 / 1024
        status["memory_percent"] = mem.percent
        
        # CPU
        status["cpu_percent"] = psutil.cpu_percent(interval=1)
        
        # Disk
        disk = psutil.disk_usage(str(ROOT_DIR))
        status["disk_free_gb"] = disk.free / 1024 / 1024 / 1024
        status["disk_percent"] = disk.percent
        
        # Python processes
        python_procs = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cmdline']):
            info: dict = proc.info  # type: ignore[attr-defined]
            if 'python' in (info.get('name') or '').lower():
                mem_info = info.get('memory_info')
                mem_mb = (mem_info.rss if mem_info else 0) / 1024 / 1024
                cmdline = ' '.join(info.get('cmdline') or [])[:80]
                python_procs.append({
                    "pid": info.get('pid'),
                    "memory_mb": round(mem_mb, 1),
                    "cmd": cmdline,
                })
        status["python_processes"] = python_procs
        status["python_total_memory_mb"] = sum(p["memory_mb"] for p in python_procs)
    
    # Screenshots
    total_count = 0
    total_size = 0
    for screenshot_dir in SCREENSHOT_DIRS:
        if screenshot_dir.exists():
            screenshots = list(screenshot_dir.glob("*.png"))
            total_count += len(screenshots)
            total_size += sum(f.stat().st_size for f in screenshots)
    status["screenshot_count"] = total_count
    status["screenshot_size_mb"] = total_size / 1024 / 1024
    
    # Logs
    for log_path in LOG_FILES:
        if log_path.exists():
            status[f"log_{log_path.stem}_mb"] = log_path.stat().st_size / 1024 / 1024
    
    return status


def print_status():
    """Print formatted system status."""
    status = get_system_status()
    
    print("\n" + "=" * 50)
    print("  BPTrading Bot System Status")
    print("=" * 50)
    print(f"  Time: {status['timestamp']}")
    
    if HAS_PSUTIL:
        print(f"\n  Memory: {status['memory_used_mb']:.0f} / {status['memory_total_mb']:.0f} MB ({status['memory_percent']:.1f}%)")
        print(f"  CPU: {status['cpu_percent']:.1f}%")
        print(f"  Disk Free: {status['disk_free_gb']:.1f} GB")
        
        if status.get('python_processes'):
            print(f"\n  Python Processes ({len(status['python_processes'])}):")
            for p in status['python_processes']:
                print(f"    PID {p['pid']}: {p['memory_mb']:.1f} MB - {p['cmd']}")
            print(f"  Total Python Memory: {status['python_total_memory_mb']:.1f} MB")
            
            if status['python_total_memory_mb'] > STABILITY.get("memory_warning_mb", 1024):
                print(f"  ⚠️  WARNING: Memory usage exceeds {STABILITY['memory_warning_mb']} MB!")
    else:
        print("\n  (Install psutil for detailed system info: pip install psutil)")
    
    if "screenshot_count" in status:
        print(f"\n  Screenshots: {status['screenshot_count']} files ({status['screenshot_size_mb']:.1f} MB)")
    
    for log_path in LOG_FILES:
        key = f"log_{log_path.stem}_mb"
        if key in status:
            print(f"  Log {log_path.name}: {status[key]:.1f} MB")
    
    print("=" * 50 + "\n")
    
    return status


def run_maintenance():
    """Run all maintenance tasks."""
    print("\n[Maintenance] Starting maintenance tasks...")
    
    # Log rotation
    for log_path in LOG_FILES:
        rotate_log(
            log_path,
            STABILITY.get("log_max_bytes", 10 * 1024 * 1024),
            STABILITY.get("log_backup_count", 5),
        )
    
    # Screenshot cleanup
    cleanup_old_screenshots(STABILITY.get("screenshot_retention_days", 3))
    
    # Temp file cleanup
    cleanup_temp_files()
    
    print("[Maintenance] Done\n")


def main():
    parser = argparse.ArgumentParser(description="Bot maintenance utilities")
    parser.add_argument("--cleanup", action="store_true", help="Run cleanup tasks only")
    parser.add_argument("--status", action="store_true", help="Show system status only")
    args = parser.parse_args()
    
    if args.status:
        print_status()
    elif args.cleanup:
        run_maintenance()
    else:
        print_status()
        run_maintenance()


if __name__ == "__main__":
    main()
