"""
continuous_runner.py — VPS entry point (runs 24x7, active only during market hours)
--------------------------------------------------------------------------------------
This is the VPS version of the agent — replaces the GitHub-Actions-based
run_agent_check.py for live automation, because Groww's API requires a
registered STATIC IP, which GitHub Actions can't provide (random IP per
run) but a VPS can (one fixed IP, registered once in Groww's dashboard).

What it does, every LOOP_INTERVAL_SECONDS (default 60 = 1-minute, per
Saim's 11 Aug 2026 request for finer granularity):
  1. Fetches today's candles so far for NIFTY + BANKNIFTY via Groww's
     direct API (groww_api.py)
  2. Saves them into data/daily_store/ (same format as before)
  3. Scores the setup via engine.py (price+momentum, plus OI order-flow
     if a snapshot is available)
  4. Sends a Telegram alert if the (symbol,date,signal,score) combo
     hasn't been alerted yet today (dedup, same as before)
  5. Sleeps until market hours if run outside 9:15-15:30 IST, Mon-Fri

Run this under systemd (see deploy.md) so it restarts automatically and
survives reboots / crashes.
"""

import time
import sys
import os
from datetime import datetime, time as dtime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from daily_store import append_intraday_candles
from engine import score_setup, log_signal
from telegram_notify import send_telegram_message, format_signal_alert
from groww_api import fetch_candles
from run_agent_check import latest_oi_bias, _alert_key, _load_alerted, _mark_alerted

LOOP_INTERVAL_SECONDS = 60  # 1-minute granularity
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
SYMBOLS = ["NIFTY", "BANKNIFTY"]


def is_market_hours(now=None):
    now = now or datetime.now()
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def run_once():
    today = datetime.now().strftime("%Y-%m-%d")
    alerted = _load_alerted()

    for symbol in SYMBOLS:
        try:
            candles = fetch_candles(symbol, f"{today} 09:15:00",
                                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                     interval_minutes=1)
        except Exception as e:
            print(f"[{datetime.now()}] {symbol}: fetch failed — {e}")
            continue

        if not candles:
            print(f"[{datetime.now()}] {symbol}: no candles yet")
            continue

        append_intraday_candles(symbol, candles, interval_label="1min")

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        oi_bias = latest_oi_bias(symbol)
        result = score_setup(closes, highs, lows, oi_bias=oi_bias)
        log_signal(symbol, result, note=f"VPS continuous run, {today}")

        if result["signal"] == "NONE":
            print(f"[{datetime.now()}] {symbol}: no signal ({len(candles)} candles)")
            continue

        key = _alert_key(symbol, today, result["signal"], result["score"])
        if key in alerted:
            print(f"[{datetime.now()}] {symbol}: signal already alerted today, skipping")
            continue

        msg = format_signal_alert(symbol, result) + f"\n\nData date: {today} (live, VPS)"
        send_result = send_telegram_message(msg)
        print(f"[{datetime.now()}] {symbol}: ALERT SENT — {send_result.get('ok')}")
        if send_result.get("ok"):
            _mark_alerted(key)
            alerted.add(key)


def main():
    print(f"[{datetime.now()}] continuous_runner starting. Loop interval: {LOOP_INTERVAL_SECONDS}s")
    while True:
        try:
            if is_market_hours():
                run_once()
            else:
                print(f"[{datetime.now()}] outside market hours, sleeping")
        except Exception as e:
            print(f"[{datetime.now()}] UNEXPECTED ERROR: {e}")
        time.sleep(LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
