"""
opening_impact_tracker.py — is the opening move the biggest of the day?
------------------------------------------------------------------------------
21 Aug 2026: Saim's detailed hypothesis — big players build positions in
futures/options AFTER cash close (3:15+), then ADJUST/hedge those
positions overnight/pre-market as news and global sentiment shift. When
the 9:15 open finally lets continuous trading resume, all that
accumulated pre-market repositioning releases at once — producing a
move in the FIRST FEW MINUTES that is disproportionately larger than
any other few-minute window for the REST of the day.

Saim is explicit this needs full order-flow-depth (who's actually
punching orders, in which direction) to fully verify the CAUSE — which
remains blocked (see order_flow_depth.py investigation). But the
OBSERVABLE EFFECT — is the opening range genuinely the day's biggest —
is testable RIGHT NOW using only price candles, which already work.
This tracker verifies that specific, price-only-testable piece of the
hypothesis daily, building the evidence base while the order-flow-depth
side gets resolved separately.
"""
import json
import os
from datetime import datetime, time as dtime

BASE = os.path.dirname(os.path.abspath(__file__))
OPENING_IMPACT_LOG_PATH = os.path.join(BASE, "memory", "opening_impact_events.jsonl")

OPENING_WINDOW_MINUTES = 5  # "first few minutes" — Saim mentioned 1-5 min


def _read_all():
    if not os.path.exists(OPENING_IMPACT_LOG_PATH):
        return []
    with open(OPENING_IMPACT_LOG_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(OPENING_IMPACT_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def analyze_opening_impact(symbol, date_str, day_candles):
    """
    Call once at end of day with the FULL day's 1-min candles. Computes:
    - opening_range: high-low range of the first OPENING_WINDOW_MINUTES
      minutes (9:15-9:20)
    - max_other_5min_range: the LARGEST 5-min rolling range found
      ANYWHERE ELSE in the rest of the day (a fair "biggest competitor"
      comparison, not just an average)
    - is_opening_the_biggest: whether the opening window actually beat
      every other 5-min window in the day — the direct test of Saim's
      "biggest move of the day happens at open" claim
    """
    if not day_candles or len(day_candles) < OPENING_WINDOW_MINUTES + 10:
        return None

    def _time_of(c):
        return datetime.fromisoformat(c["timestamp"]).time()

    opening_candles = [c for c in day_candles if _time_of(c) < dtime(9, 15 + OPENING_WINDOW_MINUTES)]
    if not opening_candles:
        return None
    opening_high = max(c["high"] for c in opening_candles)
    opening_low = min(c["low"] for c in opening_candles)
    opening_range = round(opening_high - opening_low, 2)

    # Find the largest 5-min rolling range anywhere else in the day
    rest_candles = [c for c in day_candles if _time_of(c) >= dtime(9, 15 + OPENING_WINDOW_MINUTES)]
    max_other_range = 0
    max_other_window_time = None
    for i in range(len(rest_candles) - OPENING_WINDOW_MINUTES):
        window = rest_candles[i:i + OPENING_WINDOW_MINUTES]
        w_high = max(c["high"] for c in window)
        w_low = min(c["low"] for c in window)
        w_range = w_high - w_low
        if w_range > max_other_range:
            max_other_range = w_range
            max_other_window_time = window[0]["timestamp"][11:16]

    event = {
        "symbol": symbol, "date": date_str,
        "opening_range": opening_range,
        "max_other_5min_range": round(max_other_range, 2),
        "max_other_window_time": max_other_window_time,
        "is_opening_the_biggest": opening_range > max_other_range,
        "opening_vs_max_other_ratio": round(opening_range / max_other_range, 2) if max_other_range else None,
        "logged_at": datetime.now().isoformat(),
    }
    entries = _read_all()
    entries.append(event)
    _write_all(entries)
    return event


def review_opening_impact_stats():
    """Reports how often the opening 5-min window genuinely was the
    day's single biggest move — the real, accumulated answer to Saim's
    hypothesis, and by how much on average when it does happen."""
    entries = _read_all()
    if not entries:
        return {"total_days": 0, "message": "No opening-impact data yet."}

    biggest_days = [e for e in entries if e["is_opening_the_biggest"]]
    ratios = [e["opening_vs_max_other_ratio"] for e in entries if e.get("opening_vs_max_other_ratio")]

    return {
        "total_days_tracked": len(entries),
        "days_opening_was_biggest": len(biggest_days),
        "pct_days_opening_was_biggest": round(len(biggest_days) / len(entries) * 100, 1),
        "avg_ratio_opening_to_max_other": round(sum(ratios) / len(ratios), 2) if ratios else None,
    }


if __name__ == "__main__":
    print(json.dumps(review_opening_impact_stats(), indent=2))
