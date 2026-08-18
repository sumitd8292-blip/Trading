"""
fii_price_impact_tracker.py — does FII net selling actually push price down, and how fast?
--------------------------------------------------------------------------------------------
Same pattern as divergence_tracker.py, applied to FII/DII flows instead
of OI. FII/DII data is still MANUAL (Saim provides daily net Cr figures
via fii_dii.record_fii_dii() — no live feed exists, see memory notes).
So this tracker activates once each day's figure is recorded: it logs
the FII lean as of that day, then over subsequent days checks whether
price actually moved in the implied direction, and how long it took.
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
FII_IMPACT_PATH = os.path.join(BASE, "memory", "fii_impact_events.jsonl")
RESOLUTION_THRESHOLD_POINTS = 30  # FII flows are a slower/bigger-picture signal than intraday OI
MAX_TRACKING_DAYS = 5


def _read_all():
    if not os.path.exists(FII_IMPACT_PATH):
        return []
    with open(FII_IMPACT_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(FII_IMPACT_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def log_fii_event(symbol, date_str, fii_lean, reference_price):
    """Call once per day (after fii_dii.record_fii_dii()) with the day's
    FII lean and the symbol's closing/reference price that day."""
    if fii_lean not in ("BULLISH", "BEARISH"):
        return None
    entries = _read_all()
    entries = [e for e in entries if not (e["symbol"] == symbol and e["date"] == date_str)]
    event = {
        "symbol": symbol, "date": date_str, "fii_lean": fii_lean,
        "reference_price": reference_price, "logged_at": datetime.now().isoformat(),
        "status": "OPEN", "resolved": None, "resolution_days": None, "resolution_move_points": None,
    }
    entries.append(event)
    _write_all(entries)
    return event


def check_fii_resolution(symbol, current_date_str, current_price):
    """Call daily with the latest price — checks all OPEN FII events for
    this symbol to see if price has now moved in FII's implied direction."""
    entries = _read_all()
    closed = []
    for event in entries:
        if event["symbol"] != symbol or event["status"] != "OPEN":
            continue
        days_elapsed = (datetime.strptime(current_date_str, "%Y-%m-%d") -
                         datetime.strptime(event["date"], "%Y-%m-%d")).days
        implied_up = event["fii_lean"] == "BULLISH"
        move = (current_price - event["reference_price"]) if implied_up else (event["reference_price"] - current_price)

        if move >= RESOLUTION_THRESHOLD_POINTS:
            event["status"] = "CLOSED"; event["resolved"] = True
            event["resolution_days"] = days_elapsed; event["resolution_move_points"] = round(move, 1)
            closed.append(event)
        elif days_elapsed >= MAX_TRACKING_DAYS:
            event["status"] = "CLOSED"; event["resolved"] = False
            event["resolution_days"] = days_elapsed; event["resolution_move_points"] = round(move, 1)
            closed.append(event)
    _write_all(entries)
    return closed


def review_fii_impact_stats():
    entries = [e for e in _read_all() if e["status"] == "CLOSED"]
    if not entries:
        return {"total_events": 0, "message": "No FII impact events tracked yet."}
    resolved = [e for e in entries if e["resolved"]]
    stats = {
        "total_events": len(entries),
        "resolved_in_fiis_favor": len(resolved),
        "resolution_rate_pct": round(len(resolved) / len(entries) * 100, 1),
    }
    if resolved:
        stats["avg_days_to_resolve"] = round(sum(e["resolution_days"] for e in resolved) / len(resolved), 1)
    return stats


if __name__ == "__main__":
    print(json.dumps(review_fii_impact_stats(), indent=2))
