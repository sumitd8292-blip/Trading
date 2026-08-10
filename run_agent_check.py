"""
run_agent_check.py — GitHub Actions entry point.

Computes today's (or latest stored day's) signal from data/daily_store/
and sends it to Telegram. This does NOT fetch live data on its own —
GrowwMCP only works inside Claude chat sessions — it scores whatever the
most recent day already saved in data/daily_store/ is.

Until live data fetching is wired up from an external source (e.g. Dhan
API), new days must be pushed into data/daily_store/ from a Claude
session (via daily_store.append_intraday_candles) before this script has
anything fresh to score. Safe to run on a schedule regardless — it just
re-reports the latest available day if nothing new has been added.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import score_setup, log_signal
from telegram_notify import send_telegram_message, format_signal_alert

STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "daily_store")


def latest_day(symbol):
    path = os.path.join(STORE_DIR, f"{symbol}_5min_log.jsonl")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        lines = [json.loads(l) for l in f]
    return lines[-1] if lines else None


def main():
    for symbol in ["NIFTY", "BANKNIFTY"]:
        day = latest_day(symbol)
        if day is None:
            continue
        candles = day["candles"]
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        result = score_setup(closes, highs, lows)
        log_signal(symbol, result, note=f"GitHub Actions run, data date {day['date']}")

        if result["signal"] != "NONE":
            msg = format_signal_alert(symbol, result) + f"\n\nData date: {day['date']}"
            send_result = send_telegram_message(msg)
            print(symbol, "signal sent:", send_result.get("ok"))
        else:
            print(symbol, "no signal for", day["date"])


if __name__ == "__main__":
    main()
