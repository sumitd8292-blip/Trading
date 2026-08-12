"""
run_agent_check.py — GitHub Actions entry point.

Computes today's (or latest stored day's) signal from data/daily_store/
and sends it to Telegram. This does NOT fetch live data on its own —
GrowwMCP only works inside Claude chat sessions — it scores whatever the
most recent day already saved in data/daily_store/ is.

Until Groww's direct API is fully working (subscription must be active —
see groww_api.py notes) or another live source is wired up, new days must
be pushed into data/daily_store/ from a Claude session before this script
has anything fresh to score.

DEDUP: alerts for the exact same (symbol, date, signal, score) combo are
only sent ONCE — subsequent runs on unchanged data will not re-spam
Telegram. Tracked in memory/alerted_signals.jsonl.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import score_setup, log_signal
from datetime import datetime
from telegram_notify import send_telegram_message, format_signal_alert

STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "daily_store")
MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory")
ALERTED_PATH = os.path.join(MEMORY_DIR, "alerted_signals.jsonl")


def latest_day(symbol):
    path = os.path.join(STORE_DIR, f"{symbol}_5min_log.jsonl")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        lines = [json.loads(l) for l in f]
    return lines[-1] if lines else None


def latest_oi_bias(symbol):
    """Returns the most recent OI snapshot for this symbol, if any."""
    path = os.path.join(STORE_DIR, "options_oi_log.jsonl")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        entries = [json.loads(l) for l in f if l.strip()]
    matches = [e for e in entries if e.get("symbol") == symbol]
    return matches[-1] if matches else None


def _alert_key(symbol, date, signal, score):
    return f"{symbol}|{date}|{signal}|{score}"


def _load_alerted():
    if not os.path.exists(ALERTED_PATH):
        return set()
    with open(ALERTED_PATH) as f:
        return set(line.strip() for line in f if line.strip())


def _mark_alerted(key):
    with open(ALERTED_PATH, "a") as f:
        f.write(key + "\n")


def main():
    alerted = _load_alerted()
    for symbol in ["NIFTY", "BANKNIFTY"]:
        day = latest_day(symbol)
        if day is None:
            continue
        candles = day["candles"]
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        oi_bias = latest_oi_bias(symbol)
        result = score_setup(closes, highs, lows, oi_bias=oi_bias)
        log_signal(symbol, result, note=f"GitHub Actions run, data date {day['date']}")

        if result["signal"] == "NONE":
            print(symbol, "no signal for", day["date"])
            continue

        key = _alert_key(symbol, day["date"], result["signal"], result["score"])
        if key in alerted:
            print(symbol, "signal already alerted for", day["date"], "- skipping duplicate")
            continue

        msg = format_signal_alert(symbol, result) + f"\n\nData date: {day['date']}"
        send_result = send_telegram_message(msg)
        print(symbol, "signal sent:", send_result.get("ok"))
        if send_result.get("ok"):
            _mark_alerted(key)


def groww_test():
    """Quick connectivity test for the Groww direct API, safe no-op if not configured.
    Sends the result to Telegram too, since GitHub Actions logs aren't directly
    viewable from the Claude sandbox (network egress restriction)."""
    import groww_api
    from datetime import datetime
    if not groww_api.GROWW_API_KEY:
        print("GROWW_API_KEY not set, skipping Groww connectivity test.")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        candles = groww_api.fetch_candles("NIFTY", f"{today} 09:15:00", f"{today} 15:30:00", interval_minutes=5)
        msg = f"Groww API test SUCCESS: fetched {len(candles)} NIFTY candles for {today}."
        if candles:
            msg += f"\nFirst: {candles[0]}\nLast: {candles[-1]}"
        print(msg)
    except Exception as e:
        msg = f"Groww API test FAILED: {e}"
        print(msg)
    send_telegram_message("🧪 " + msg)


if __name__ == "__main__":
    groww_test()
    main()
