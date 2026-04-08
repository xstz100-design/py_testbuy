"""Batch and scheduled BPTrading trade runner.

Order line examples:
    BTC 60 down 60s desktop
    ETH 100 up 120s mobile delay=90
    GOLD 70 down 60s at=2026-03-27T21:30:00 desktop

Rules:
    - One order per line.
    - Orders execute strictly one by one.
    - delay= is applied after the previous order finishes.
    - at= waits until the given local datetime before starting.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Order:
    currency: str
    amount: str
    direction: str
    duration: str
    mode: str = "desktop"
    delay: int = 0
    execute_at: Optional[datetime] = None


def extract_result_from_output(output: str) -> Optional[dict]:
    marker = "===RESULT==="
    end_marker = "===END==="

    start = output.rfind(marker)
    if start != -1:
        end = output.find(end_marker, start)
        if end != -1:
            payload = output[start + len(marker):end].strip()
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                pass

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def parse_order_line(line: str) -> Optional[Order]:
    text = line.strip()
    if not text or text.startswith("#"):
        return None

    delay = 0
    execute_at = None

    delay_match = re.search(r"\bdelay=(\d+)\b", text, re.I)
    if delay_match:
        delay = int(delay_match.group(1))
        text = re.sub(r"\bdelay=\d+\b", "", text, flags=re.I).strip()

    at_match = re.search(r"\bat=([^\s]+)\b", text, re.I)
    if at_match:
        execute_at = datetime.fromisoformat(at_match.group(1))
        text = re.sub(r"\bat=[^\s]+\b", "", text, flags=re.I).strip()

    mode = "desktop"
    mode_match = re.search(r"\b(desktop|mobile)\b", text, re.I)
    if mode_match:
        mode = mode_match.group(1).lower()
        text = re.sub(r"\b(desktop|mobile)\b", "", text, flags=re.I).strip()

    parts = text.split()
    if len(parts) < 4:
        raise ValueError(f"Invalid order line: {line}")

    direction_index = None
    for index, token in enumerate(parts):
        if token.lower() in {"up", "down"}:
            direction_index = index
            break

    if direction_index is None or direction_index < 2 or direction_index + 1 >= len(parts):
        raise ValueError(f"Invalid order line: {line}")

    currency = " ".join(parts[:direction_index - 1])
    amount = parts[direction_index - 1]
    direction = parts[direction_index].lower()
    duration_token = parts[direction_index + 1]
    duration = duration_token[:-1] if duration_token.lower().endswith("s") else duration_token

    # Validate duration - only 60, 90, 120, 180, 300 are valid
    VALID_DURATIONS = {"60", "90", "120", "180", "300"}
    if duration not in VALID_DURATIONS:
        raise ValueError(f"Invalid duration: {duration}s. Valid options: 60s, 90s, 120s, 180s, 300s")

    return Order(
        currency=currency,
        amount=amount,
        direction=direction,
        duration=duration,
        mode=mode,
        delay=delay,
        execute_at=execute_at,
    )


def wait_for_schedule(order: Order, previous_finished_at: Optional[float]):
    targets = []
    if previous_finished_at is not None and order.delay > 0:
        targets.append(previous_finished_at + order.delay)
    if order.execute_at is not None:
        targets.append(order.execute_at.timestamp())
    if not targets:
        return

    target_ts = max(targets)
    remaining = target_ts - time.time()
    if remaining > 0:
        print(f"[schedule] Waiting {int(remaining)}s before {order.currency}")
        time.sleep(remaining)


def run_order(order: Order, trade_script: Path) -> dict:
    command = [
        sys.executable,
        str(trade_script),
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

    print("[queue] Running:", " ".join(command))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    
    # 单笔交易最大超时：5分钟（含等待结算）
    TRADE_TIMEOUT = 300
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=TRADE_TIMEOUT,
        )
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)

        result = extract_result_from_output(completed.stdout)
        if result is None:
            result = {"status": "error", "message": "No JSON result returned"}
        return result
    except subprocess.TimeoutExpired:
        print(f"[queue] TIMEOUT: Order exceeded {TRADE_TIMEOUT}s limit")
        return {"status": "error", "message": f"Timeout after {TRADE_TIMEOUT}s"}


def main():
    parser = argparse.ArgumentParser(description="Batch BPTrading trade runner")
    parser.add_argument("--orders-file", required=True, help="Path to an orders text file")
    args = parser.parse_args()

    orders_path = Path(args.orders_file)
    trade_script = Path(__file__).resolve().parent / "trade.py"

    orders = []
    for raw_line in orders_path.read_text(encoding="utf-8").splitlines():
        order = parse_order_line(raw_line)
        if order is not None:
            orders.append(order)

    results = []
    previous_finished_at = None
    for index, order in enumerate(orders, start=1):
        print(f"\n[queue] Order {index}/{len(orders)}")
        wait_for_schedule(order, previous_finished_at)
        result = run_order(order, trade_script)
        results.append({
            "order": {
                "currency": order.currency,
                "amount": order.amount,
                "direction": order.direction,
                "duration": order.duration,
                "mode": order.mode,
                "delay": order.delay,
                "execute_at": order.execute_at.isoformat() if order.execute_at else None,
            },
            "result": result,
        })
        previous_finished_at = time.time()

    ok = all(item["result"].get("status") == "ok" for item in results)
    summary = {
        "status": "ok" if ok else "partial",
        "total": len(results),
        "results": results,
    }
    print("===RESULT===")
    print(json.dumps(summary, ensure_ascii=False))
    print("===END===")


if __name__ == "__main__":
    main()