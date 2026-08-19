"""
session_behavior_tracker.py — cash-session vs extended-session comparison
------------------------------------------------------------------------------
19 Aug 2026 live finding: today's dramatic gap-fill-and-reject move (spike
to 24228, then hard reversal to 24078 close) happened SPECIFICALLY in the
15:15-15:40 EXTENDED window (options/futures continue trading after the
cash index's own regular session) — confirmed by comparing LTP's
regular-session high/low (24172.85/24025.65) against the 1-min candle
series' full-day high/low (24228.05/23956.85), which includes the
extended window.

This formalizes that comparison DAILY (not just on expiry days, which
expiry_close_tracker.py already covers) — computing how much of each
day's total range/movement happened in the extended window vs the
regular session, building the evidence for whether the extended window
is systematically more volatile/informative.
"""
import json
import os
from datetime import datetime, time as dtime

BASE = os.path.dirname(os.path.abspath(__file__))
SESSION_LOG_PATH = os.path.join(BASE, "memory", "session_behavior_events.jsonl")

REGULAR_SESSION_END = dtime(15, 15)  # cash index's own regular session end (approx)
EXTENDED_SESSION_END = dtime(15, 40)  # options/futures continue till here


def _read_all():
    if not os.path.exists(SESSION_LOG_PATH):
        return []
    with open(SESSION_LOG_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(SESSION_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def analyze_session_split(symbol, date_str, day_candles):
    """
    Call once after market close with the FULL day's 1-min candles.
    Splits into regular-session (before 15:15) vs extended-session
    (15:15-15:40) and compares each session's range and net move —
    answers "how much of today's real action happened in the window
    Saim keeps pointing at".
    """
    if not day_candles:
        return None

    def _time_of(c):
        return datetime.fromisoformat(c["timestamp"]).time()

    regular = [c for c in day_candles if _time_of(c) < REGULAR_SESSION_END]
    extended = [c for c in day_candles if REGULAR_SESSION_END <= _time_of(c) <= EXTENDED_SESSION_END]

    if not regular:
        return None

    regular_high = max(c["high"] for c in regular)
    regular_low = min(c["low"] for c in regular)
    regular_range = round(regular_high - regular_low, 2)

    extended_range = 0
    extended_net_move = 0
    extended_high = regular_high
    extended_low = regular_low
    if extended:
        extended_high = max(c["high"] for c in extended)
        extended_low = min(c["low"] for c in extended)
        extended_range = round(extended_high - extended_low, 2)
        extended_net_move = round(extended[-1]["close"] - regular[-1]["close"], 2)

    total_range = round(max(regular_high, extended_high) - min(regular_low, extended_low), 2)
    extended_share_pct = round(extended_range / total_range * 100, 1) if total_range else None

    event = {
        "symbol": symbol, "date": date_str,
        "regular_range": regular_range, "extended_range": extended_range,
        "extended_share_of_total_range_pct": extended_share_pct,
        "extended_net_move_from_regular_close": extended_net_move,
        "logged_at": datetime.now().isoformat(),
    }
    entries = _read_all()
    entries.append(event)
    _write_all(entries)
    return event


def review_session_stats():
    """Reports how often/how much the extended window disproportionately
    drives the day's total range — the data-backed answer to whether
    this window deserves special attention every day, not just expiry days."""
    entries = _read_all()
    if not entries:
        return {"total_days": 0, "message": "No session-split data yet."}

    shares = [e["extended_share_of_total_range_pct"] for e in entries if e.get("extended_share_of_total_range_pct") is not None]
    high_share_days = [e for e in entries if (e.get("extended_share_of_total_range_pct") or 0) >= 30]

    return {
        "total_days": len(entries),
        "avg_extended_share_pct": round(sum(shares) / len(shares), 1) if shares else None,
        "days_extended_share_30pct_plus": len(high_share_days),
    }


if __name__ == "__main__":
    print(json.dumps(review_session_stats(), indent=2))
