"""
naked_poc_tracker.py — prior-day POCs never retested ("magnet" levels)
------------------------------------------------------------------------------
21 Aug 2026: per Saim's instruction to research Naked POC theory in
depth, then implement. Verified from multiple sources: a Naked POC
(also "virgin POC"/NPOC) is a prior session's Point of Control that
price has NOT traded back through since. Statistical tendency: ~80% of
Naked POCs get revisited within 10 trading sessions (the "magnet
effect" — unresolved institutional interest at that price).

THREE trading use-cases from research (all implemented here):
1. TARGET — a nearby naked POC in the trade's direction, use as take-profit
2. ENTRY ZONE (first test) — price approaching for the FIRST time often
   gets a sharp, tradeable reaction (SL beyond the level, target next
   naked POC or HTF level)
3. BREAKDOWN/FAILURE — price tests it and does NOT hold (aggressive
   one-sided break) — trade the CONTINUATION, not a bounce (this
   directly reuses our poc_reaction_strategy's Initiative/Responsive
   framework, built same day)

Uses volume_profile_tracker.py's daily_poc_log.jsonl (already being
populated) as the source of historical POCs — no new data-fetching
needed.
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DAILY_POC_LOG_PATH = os.path.join(BASE, "memory", "daily_poc_log.jsonl")
NAKED_POC_STATE_PATH = os.path.join(BASE, "memory", "naked_poc_state.jsonl")
DAY_RANGE_LOG_PATH = os.path.join(BASE, "memory", "day_range_log.jsonl")


def log_day_range(symbol, date_str, day_high, day_low):
    """
    Lightweight log of each day's high/low — much cheaper than
    re-fetching historical candles every time naked-POC status needs
    checking. Call once per day (EOD), reads/dedupes automatically.
    """
    entries = _read_jsonl(DAY_RANGE_LOG_PATH)
    entries = [e for e in entries if not (e["symbol"] == symbol and e["date"] == date_str)]
    entries.append({"symbol": symbol, "date": date_str, "day_high": day_high, "day_low": day_low})
    with open(DAY_RANGE_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def load_day_ranges(symbol):
    """Returns {date_str: (day_high, day_low)} for all logged days for symbol."""
    entries = [e for e in _read_jsonl(DAY_RANGE_LOG_PATH) if e["symbol"] == symbol]
    return {e["date"]: (e["day_high"], e["day_low"]) for e in entries}


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def get_naked_pocs(symbol, current_date, day_high_low_by_date, tolerance=15):
    """
    Scans all historical daily POCs for `symbol` (from volume_profile_tracker's
    log) and determines which ones remain "naked" — meaning NO subsequent
    day's price range (high to low) has traded through that POC level.

    day_high_low_by_date: {date_str: (day_high, day_low)} for ALL days
    AFTER each candidate POC's date, needed to check if it was ever
    retested. Caller must supply this (from stored candle/futures data).

    Returns list of {poc_price, date_set, sessions_unvisited} sorted by
    sessions_unvisited descending (longest-naked = strongest per theory).
    """
    all_pocs = [e for e in _read_jsonl(DAILY_POC_LOG_PATH) if e["symbol"] == symbol and e["date"] < current_date]
    if not all_pocs:
        return []

    naked = []
    for poc_entry in all_pocs:
        poc_price = poc_entry["poc_price"]
        poc_date = poc_entry["date"]

        was_retested = False
        sessions_since = 0
        for date_str, (day_high, day_low) in sorted(day_high_low_by_date.items()):
            if date_str <= poc_date:
                continue
            sessions_since += 1
            if day_low - tolerance <= poc_price <= day_high + tolerance:
                was_retested = True
                break

        if not was_retested:
            naked.append({
                "poc_price": poc_price, "date_set": poc_date,
                "sessions_unvisited": sessions_since,
            })

    naked.sort(key=lambda x: -x["sessions_unvisited"])
    return naked


def check_naked_poc_proximity(current_price, naked_pocs, proximity_tolerance=20):
    """
    Given the current price and a list of naked POCs (from
    get_naked_pocs), returns which ones price is currently near — the
    "entry zone" use-case (first test of an unvisited level).
    """
    nearby = []
    for poc in naked_pocs:
        distance = current_price - poc["poc_price"]
        if abs(distance) <= proximity_tolerance:
            nearby.append({**poc, "distance": round(distance, 1),
                            "approach_direction": "FROM_ABOVE" if distance > 0 else "FROM_BELOW"})
    return nearby
