"""
absorption_tracker.py — does order-book absorption actually predict price behavior?
------------------------------------------------------------------------------------
Same pattern as divergence_tracker.py, applied to order_flow_depth.py's
absorption detection instead of OI-vs-price. When absorption is
detected (OI says one direction, but order-book depth shows the
opposite pressure at a specific wall), this logs the event and tracks
whether OI's direction eventually wins anyway (wall gets absorbed/
overwhelmed) or whether the wall's direction wins instead (OI proves
wrong) — the real test of whether this BEHAVIORAL-tier signal (see
confidence_tiers.py) is actually predictive.
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ABSORPTION_LOG_PATH = os.path.join(BASE, "memory", "absorption_events.jsonl")
RESOLUTION_THRESHOLD_POINTS = 15
MAX_TRACKING_MINUTES = 120


def _read_all():
    if not os.path.exists(ABSORPTION_LOG_PATH):
        return []
    with open(ABSORPTION_LOG_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(ABSORPTION_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def log_absorption_event(symbol, date_str, absorption_result, current_price, current_time_iso):
    """
    Call this when order_flow_depth.detect_absorption() flags
    absorption_detected=True. Logs which side "should" win per OI, and
    which side the wall is defending, so we can check later which one
    actually happened.
    """
    if not absorption_result or not absorption_result.get("absorption_detected"):
        return None

    entries = _read_all()
    already_open = any(e["symbol"] == symbol and e["date"] == date_str and e["status"] == "OPEN" for e in entries)
    if already_open:
        return None

    event = {
        "symbol": symbol, "date": date_str,
        "oi_lean": absorption_result["oi_lean"],
        "depth_lean": absorption_result["depth_lean"],
        "wall": absorption_result["wall"],
        "price_at_detection": current_price,
        "detected_at": current_time_iso,
        "status": "OPEN", "resolved_direction": None, "resolution_minutes": None, "resolution_move_points": None,
    }
    entries.append(event)
    _write_all(entries)
    return event


def check_absorption_resolution(symbol, date_str, current_price, current_time_iso, is_eod=False):
    """
    Checks OPEN absorption events: has price moved 15+ points in OI's
    implied direction (OI "won", wall got absorbed) or 15+ points in the
    wall's direction (wall "won", OI proved wrong)? Times out at 2 hours
    or EOD as inconclusive.
    """
    entries = _read_all()
    closed = []
    for event in entries:
        if event["symbol"] != symbol or event["date"] != date_str or event["status"] != "OPEN":
            continue

        elapsed_min = (datetime.fromisoformat(current_time_iso) - datetime.fromisoformat(event["detected_at"])).total_seconds() / 60
        oi_implied_up = event["oi_lean"] == "BULLISH"
        move_toward_oi = (current_price - event["price_at_detection"]) if oi_implied_up else (event["price_at_detection"] - current_price)

        if move_toward_oi >= RESOLUTION_THRESHOLD_POINTS:
            event["status"] = "CLOSED"; event["resolved_direction"] = "OI_WON"
            event["resolution_minutes"] = round(elapsed_min, 1); event["resolution_move_points"] = round(move_toward_oi, 1)
            closed.append(event)
        elif move_toward_oi <= -RESOLUTION_THRESHOLD_POINTS:
            event["status"] = "CLOSED"; event["resolved_direction"] = "WALL_WON"
            event["resolution_minutes"] = round(elapsed_min, 1); event["resolution_move_points"] = round(move_toward_oi, 1)
            closed.append(event)
        elif elapsed_min >= MAX_TRACKING_MINUTES or is_eod:
            event["status"] = "CLOSED"; event["resolved_direction"] = "INCONCLUSIVE"
            event["resolution_minutes"] = round(elapsed_min, 1); event["resolution_move_points"] = round(move_toward_oi, 1)
            closed.append(event)
    _write_all(entries)
    return closed


def review_absorption_stats():
    """Reports: when OI-vs-depth disagreement happened, who actually won
    more often — the OI-implied direction, or the wall's direction?"""
    entries = [e for e in _read_all() if e["status"] == "CLOSED"]
    if not entries:
        return {"total_events": 0, "message": "No absorption events tracked yet."}
    oi_won = sum(1 for e in entries if e["resolved_direction"] == "OI_WON")
    wall_won = sum(1 for e in entries if e["resolved_direction"] == "WALL_WON")
    inconclusive = sum(1 for e in entries if e["resolved_direction"] == "INCONCLUSIVE")
    return {
        "total_events": len(entries),
        "oi_won": oi_won, "wall_won": wall_won, "inconclusive": inconclusive,
        "wall_win_rate_pct": round(wall_won / (oi_won + wall_won) * 100, 1) if (oi_won + wall_won) else None,
    }


if __name__ == "__main__":
    print(json.dumps(review_absorption_stats(), indent=2))
