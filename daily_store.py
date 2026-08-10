"""
Daily Data Store
----------------
Appends each trading day's data to persistent files, symbol by symbol.
This is the "save data going forward" system Saim asked for (10 Aug 2026):
starting today, every trading day's price data gets appended here, and as
options chain / FII-DII / Greeks data sources come online, the same pattern
extends to those (see append_options_snapshot / append_fii_dii below —
currently stubs, wire up once data is available).

Files live under data/daily_store/:
  - <symbol>_5min_log.jsonl   -> one line per day, {date, candles:[...]}
  - <symbol>_eod_log.jsonl    -> one line per day, {date, open, high, low, close}
  - fii_dii_log.jsonl         -> one line per day once wired up
  - options_oi_log.jsonl      -> one line per snapshot once wired up
  - greeks_log.jsonl          -> one line per snapshot once wired up
"""

import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(BASE, "data", "daily_store")
os.makedirs(STORE_DIR, exist_ok=True)


def _path(name):
    return os.path.join(STORE_DIR, name)


def _already_logged(path, date_str):
    if not os.path.exists(path):
        return False
    with open(path) as f:
        for line in f:
            try:
                if json.loads(line).get("date") == date_str:
                    return True
            except Exception:
                continue
    return False


def append_intraday_candles(symbol, candles):
    """
    candles: list of {timestamp, open, high, low, close} dicts for ONE trading day
    (mixed-day lists get split automatically by date).
    Skips a day if it's already logged (idempotent — safe to re-run).
    """
    by_day = {}
    for c in candles:
        d = c["timestamp"][:10]
        by_day.setdefault(d, []).append(c)

    path = _path(f"{symbol}_5min_log.jsonl")
    written = []
    for date_str, day_candles in sorted(by_day.items()):
        if _already_logged(path, date_str):
            continue
        entry = {"date": date_str, "symbol": symbol, "candles": day_candles,
                  "logged_at": datetime.now().isoformat()}
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        written.append(date_str)

        # also update the simple EOD summary log
        closes = [c["close"] for c in day_candles]
        highs = [c["high"] for c in day_candles]
        lows = [c["low"] for c in day_candles]
        eod = {
            "date": date_str,
            "open": day_candles[0]["open"],
            "high": max(highs),
            "low": min(lows),
            "close": closes[-1],
        }
        eod_path = _path(f"{symbol}_eod_log.jsonl")
        if not _already_logged(eod_path, date_str):
            with open(eod_path, "a") as f:
                f.write(json.dumps(eod) + "\n")
    return written


# --- Stubs for future data types (wire up as sources become available) ---

def append_fii_dii(date_str, fii_net, dii_net, note=""):
    path = _path("fii_dii_log.jsonl")
    if _already_logged(path, date_str):
        return False
    entry = {"date": date_str, "fii_net_cr": fii_net, "dii_net_cr": dii_net, "note": note}
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return True


def append_options_snapshot(date_str, symbol, snapshot_dict):
    """snapshot_dict: whatever OI/PCR/strike-wise data is available at capture time."""
    path = _path("options_oi_log.jsonl")
    entry = {"date": date_str, "symbol": symbol, "captured_at": datetime.now().isoformat(),
              **snapshot_dict}
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return True


def append_greeks_snapshot(date_str, symbol, greeks_dict):
    path = _path("greeks_log.jsonl")
    entry = {"date": date_str, "symbol": symbol, "captured_at": datetime.now().isoformat(),
              **greeks_dict}
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return True


if __name__ == "__main__":
    print("Daily store dir:", STORE_DIR)
    for f in os.listdir(STORE_DIR):
        print(" -", f)
