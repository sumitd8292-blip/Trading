"""
fvg_touch_tracker.py — what happens when price returns to fill an FVG?
------------------------------------------------------------------------------
19 Aug 2026: Saim's live example — a 1-hour FVG formed, price later
returned to "touch"/fill it, and reversed sharply right after (verified
live: NIFTY spiked to 24228 filling an 18-Aug gap zone, then reversed
hard). smc.py already DETECTS FVGs (find_recent_fvgs) but nothing
tracked what happens when price comes back to touch one — this closes
that loop.

HYPOTHESIS: when price touches a previously-formed FVG zone, does it
typically reject (reverse) or continue through it? And does VSA
(volume/effort-vs-result) at the moment of touch predict which?
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
FVG_TOUCH_LOG_PATH = os.path.join(BASE, "memory", "fvg_touch_events.jsonl")
RESOLUTION_THRESHOLD_POINTS = 15
MAX_TRACKING_MINUTES = 60


def _read_all():
    if not os.path.exists(FVG_TOUCH_LOG_PATH):
        return []
    with open(FVG_TOUCH_LOG_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(FVG_TOUCH_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def check_fvg_touch(symbol, date_str, candles, fvgs, vsa_bias, current_time_iso):
    """
    Call each tick with the current candle series and smc.find_recent_fvgs()
    output. If the LATEST candle's high/low enters a previously-untouched
    FVG zone, logs a "touch" event with the VSA read at that moment (does
    volume suggest rejection or continuation), then tracks forward.
    """
    if not fvgs or not candles:
        return None

    latest = candles[-1]
    entries = _read_all()

    for fvg in fvgs:
        fvg_id = f"{symbol}_{date_str}_{fvg['index']}_{fvg['type']}"
        already_tracked = any(e.get("fvg_id") == fvg_id for e in entries)
        if already_tracked:
            continue

        touched = fvg["gap_low"] <= latest["high"] and fvg["gap_low"] <= latest["low"] <= fvg["gap_high"] or \
                  (latest["low"] <= fvg["gap_high"] and latest["high"] >= fvg["gap_low"])
        if not touched:
            continue

        event = {
            "fvg_id": fvg_id, "symbol": symbol, "date": date_str,
            "fvg_type": fvg["type"], "gap_low": fvg["gap_low"], "gap_high": fvg["gap_high"],
            "touch_price": latest["close"], "touch_time": current_time_iso,
            "vsa_at_touch": vsa_bias.get("lean") if vsa_bias else None,
            "status": "OPEN", "outcome": None, "resolution_minutes": None, "move_points": None,
        }
        entries.append(event)
        _write_all(entries)
        return event
    return None


def check_touch_resolution(symbol, current_price, current_time_iso, is_eod=False):
    """
    Checks OPEN FVG-touch events: did price REJECT (move 15+ points away
    from the gap, in the direction opposite to filling it further) or
    CONTINUE (move 15+ points further through/past the gap)? Times out
    at 60 min or EOD.
    """
    entries = _read_all()
    closed = []
    for event in entries:
        if event["symbol"] != symbol or event["status"] != "OPEN":
            continue

        elapsed_min = (datetime.fromisoformat(current_time_iso) - datetime.fromisoformat(event["touch_time"])).total_seconds() / 60
        touch_price = event["touch_price"]
        move = current_price - touch_price

        # bullish FVG touched from above -> reject means price falls back below gap_low; continue means keeps rising
        # bearish FVG touched from below -> reject means price falls back above gap_high; continue means keeps falling
        if event["fvg_type"] == "bullish":
            outcome = "REJECTED" if move <= -RESOLUTION_THRESHOLD_POINTS else ("CONTINUED" if move >= RESOLUTION_THRESHOLD_POINTS else None)
        else:
            outcome = "REJECTED" if move >= RESOLUTION_THRESHOLD_POINTS else ("CONTINUED" if move <= -RESOLUTION_THRESHOLD_POINTS else None)

        if outcome:
            event["status"] = "CLOSED"; event["outcome"] = outcome
            event["resolution_minutes"] = round(elapsed_min, 1); event["move_points"] = round(move, 1)
            closed.append(event)
        elif elapsed_min >= MAX_TRACKING_MINUTES or is_eod:
            event["status"] = "CLOSED"; event["outcome"] = "INCONCLUSIVE"
            event["resolution_minutes"] = round(elapsed_min, 1); event["move_points"] = round(move, 1)
            closed.append(event)
    _write_all(entries)
    return closed


def review_fvg_touch_stats():
    """Reports rejection-vs-continuation rate, and whether VSA at touch
    predicted the outcome — the real test of whether VSA-at-FVG-touch is
    a useful confirmation."""
    entries = [e for e in _read_all() if e["status"] == "CLOSED" and e["outcome"] != "INCONCLUSIVE"]
    if not entries:
        return {"total": 0, "message": "No resolved FVG touches yet."}

    rejected = sum(1 for e in entries if e["outcome"] == "REJECTED")
    continued = sum(1 for e in entries if e["outcome"] == "CONTINUED")

    vsa_predictive = 0
    vsa_total = 0
    for e in entries:
        if e.get("vsa_at_touch") in ("BULLISH", "BEARISH"):
            vsa_total += 1
            vsa_implies_continue = (e["fvg_type"] == "bullish" and e["vsa_at_touch"] == "BULLISH") or \
                                    (e["fvg_type"] == "bearish" and e["vsa_at_touch"] == "BEARISH")
            if (vsa_implies_continue and e["outcome"] == "CONTINUED") or (not vsa_implies_continue and e["outcome"] == "REJECTED"):
                vsa_predictive += 1

    return {
        "total_resolved": len(entries),
        "rejected": rejected, "continued": continued,
        "rejection_rate_pct": round(rejected / len(entries) * 100, 1),
        "vsa_predictive_rate_pct": round(vsa_predictive / vsa_total * 100, 1) if vsa_total else None,
    }


if __name__ == "__main__":
    print(json.dumps(review_fvg_touch_stats(), indent=2))
