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

IMPORTANT: a day's entry gets OVERWRITTEN (not skipped) if new data has
MORE candles than what's currently stored — this handles the case where
an intraday partial save (e.g. mid-session) is later followed by the
full end-of-day save for the same date. Exact-or-fewer candle counts are
skipped (idempotent, safe to re-run).
"""

import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(BASE, "data", "daily_store")
os.makedirs(STORE_DIR, exist_ok=True)


def _path(name):
    return os.path.join(STORE_DIR, name)


def _read_all(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        out = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


def _write_all(path, entries):
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def append_intraday_candles(symbol, candles, interval_label="5min"):
    """
    candles: list of {timestamp, open, high, low, close} dicts, possibly
    spanning multiple trading days (auto-split by date).
    A day is written if it's new, or overwritten if the new candle count
    is greater than what's already stored for that date (upgrades a
    partial mid-session save to a full end-of-day save). Otherwise skipped.
    """
    by_day = {}
    for c in candles:
        d = c["timestamp"][:10]
        by_day.setdefault(d, []).append(c)

    path = _path(f"{symbol}_{interval_label}_log.jsonl")
    existing = _read_all(path)
    existing_by_date = {e["date"]: e for e in existing}

    written = []
    for date_str, day_candles in sorted(by_day.items()):
        prev = existing_by_date.get(date_str)
        if prev is not None and len(prev.get("candles", [])) >= len(day_candles):
            continue  # already have equal-or-more complete data for this day

        entry = {"date": date_str, "symbol": symbol, "candles": day_candles,
                  "logged_at": datetime.now().isoformat()}
        existing_by_date[date_str] = entry
        written.append(date_str)

    _write_all(path, [existing_by_date[d] for d in sorted(existing_by_date)])

    # rebuild EOD log from the (now up to date) 5-min log, only for changed days
    if written:
        eod_path = _path(f"{symbol}_eod_log.jsonl")  # EOD summary stays interval-agnostic (uses whichever call has most granular/complete data for that day)
        eod_existing = {e["date"]: e for e in _read_all(eod_path)}
        for date_str in written:
            day_candles = existing_by_date[date_str]["candles"]
            closes = [c["close"] for c in day_candles]
            highs = [c["high"] for c in day_candles]
            lows = [c["low"] for c in day_candles]
            eod_existing[date_str] = {
                "date": date_str,
                "open": day_candles[0]["open"],
                "high": max(highs),
                "low": min(lows),
                "close": closes[-1],
            }
        _write_all(eod_path, [eod_existing[d] for d in sorted(eod_existing)])

    return written


# --- Stubs for future data types (wire up as sources become available) ---

def append_fii_dii(date_str, fii_net, dii_net, note=""):
    path = _path("fii_dii_log.jsonl")
    existing = {e["date"]: e for e in _read_all(path)}
    if date_str in existing:
        return False
    existing[date_str] = {"date": date_str, "fii_net_cr": fii_net, "dii_net_cr": dii_net, "note": note}
    _write_all(path, [existing[d] for d in sorted(existing)])
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


def get_previous_close(symbol, interval_label="1min"):
    """
    Returns the most recent completed trading day's closing price for
    symbol, from the stored intraday log — used by pre_open_signal_tracker.py
    to compare against GIFT NIFTY's overnight reading (added 21 Aug 2026).
    Falls back to the 5min log if 1min isn't available. Returns None if
    no data exists yet.
    """
    for label in [interval_label, "5min"]:
        path = _path(f"{symbol}_{label}_log.jsonl")
        entries = _read_all(path)
        if not entries:
            continue
        entries.sort(key=lambda e: e["date"])
        last_day = entries[-1]
        candles = last_day.get("candles", [])
        if candles:
            return candles[-1]["close"]
    return None
