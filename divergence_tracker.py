"""
divergence_tracker.py — explicit hypothesis-tracking for OI-vs-price divergence
------------------------------------------------------------------------------------
Saim's 18 Aug 2026 instruction: the agent shouldn't just passively log
trade outcomes — it needs to know WHAT SPECIFIC QUESTION to investigate,
or it'll "just watch things happen and let them go" without understanding
significance. This module encodes ONE specific, well-defined hypothesis
for the agent to test continuously:

  QUESTION: When live option-chain OI/PCR shows a BULLISH lean but price
  is currently trending DOWN (or OI shows BEARISH while price trends UP)
  — a divergence between positioning and price — does price eventually
  move in OI's implied direction? If yes, how long does it take (how
  many minutes / candles), and how big is the eventual move? If it
  DOESN'T resolve by end of day, that's also a valid, useful answer
  (tells us OI didn't lead price that day).

This does NOT feed into engine.py's live scoring (Saim explicitly said
not to build an active "divergence warning" signal yet) — it's a purely
observational tracker that accumulates evidence. Once enough divergence
events have resolved (or not), review_divergence_stats() can report
hit-rate and typical resolution time — giving a genuine, data-backed
answer instead of a guess.
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DIVERGENCE_LOG_PATH = os.path.join(BASE, "memory", "divergence_events.jsonl")

# How far price must move in OI's implied direction to count as "resolved"
RESOLUTION_THRESHOLD_POINTS = 15
# Give up tracking an event after this many minutes if unresolved
MAX_TRACKING_MINUTES = 180


def _read_all():
    if not os.path.exists(DIVERGENCE_LOG_PATH):
        return []
    with open(DIVERGENCE_LOG_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(DIVERGENCE_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def detect_and_log_divergence(symbol, date_str, oi_lean, price_trend_direction, current_price, current_time_iso,
                               gex_context=None, days_to_expiry=None):
    """
    Call this each loop tick with the current OI lean and the current
    short-term price trend direction (e.g. from trend_continuation.py or
    a simple recent-candles read). If they disagree (OI BULLISH vs price
    DOWN, or OI BEARISH vs price UP) and there's no already-open tracked
    event for this symbol+date, logs a new divergence event to watch.

    gex_context: optional dict from compute_gamma_exposure() (net_gex,
    regime, peak_gamma_strike) — captured alongside the event so future
    analysis can separate "this happened in a high-gamma/near-expiry
    window" from "this happened in a calmer mid-cycle window" (see
    memory/greeks_knowledge.md Part 4 — weekly NIFTY vs monthly BANKNIFTY
    expiry cycles mean the SAME divergence pattern may behave differently
    depending on where in the expiry cycle it occurs).
    days_to_expiry: optional int — how many days until THIS symbol's own
    next expiry (weekly for NIFTY/SENSEX, monthly for BANKNIFTY).

    Does nothing if OI is NEUTRAL, or if they already agree, or if an
    event for this symbol+date is already open.
    """
    if oi_lean not in ("BULLISH", "BEARISH") or price_trend_direction not in ("UP", "DOWN"):
        return None

    agrees = (oi_lean == "BULLISH" and price_trend_direction == "UP") or \
             (oi_lean == "BEARISH" and price_trend_direction == "DOWN")
    if agrees:
        return None

    entries = _read_all()
    already_open = any(e["symbol"] == symbol and e["date"] == date_str and e["status"] == "OPEN" for e in entries)
    if already_open:
        return None

    event = {
        "symbol": symbol,
        "date": date_str,
        "oi_lean": oi_lean,
        "price_trend_at_detection": price_trend_direction,
        "price_at_detection": current_price,
        "detected_at": current_time_iso,
        "gex_regime": (gex_context or {}).get("regime"),
        "net_gex": (gex_context or {}).get("net_gex"),
        "days_to_expiry": days_to_expiry,
        "status": "OPEN",
        "resolved": None,          # True/False once determined
        "resolution_minutes": None,
        "resolution_price": None,
        "resolution_move_points": None,
    }
    entries.append(event)
    _write_all(entries)
    return event


def check_divergence_resolution(symbol, date_str, current_price, current_time_iso, is_eod=False):
    """
    Checks all OPEN divergence events for this symbol+date: has price now
    moved RESOLUTION_THRESHOLD_POINTS in OI's implied direction? If yes,
    marks resolved=True with how long it took and how far it moved. If
    MAX_TRACKING_MINUTES has elapsed (or is_eod) without resolution,
    marks resolved=False (a valid, useful "OI didn't lead price" data point).

    Returns list of events closed this call.
    """
    entries = _read_all()
    closed = []

    for event in entries:
        if event["symbol"] != symbol or event["date"] != date_str or event["status"] != "OPEN":
            continue

        detected_dt = datetime.fromisoformat(event["detected_at"])
        current_dt = datetime.fromisoformat(current_time_iso)
        elapsed_min = (current_dt - detected_dt).total_seconds() / 60

        implied_up = event["oi_lean"] == "BULLISH"
        move = (current_price - event["price_at_detection"]) if implied_up else (event["price_at_detection"] - current_price)

        if move >= RESOLUTION_THRESHOLD_POINTS:
            event["status"] = "CLOSED"
            event["resolved"] = True
            event["resolution_minutes"] = round(elapsed_min, 1)
            event["resolution_price"] = current_price
            event["resolution_move_points"] = round(move, 1)
            closed.append(event)
        elif elapsed_min >= MAX_TRACKING_MINUTES or is_eod:
            event["status"] = "CLOSED"
            event["resolved"] = False
            event["resolution_minutes"] = round(elapsed_min, 1)
            event["resolution_price"] = current_price
            event["resolution_move_points"] = round(move, 1)
            closed.append(event)

    _write_all(entries)
    return closed


def review_divergence_stats():
    """
    Reports what the agent has learned so far: out of all CLOSED
    divergence events, how many resolved in OI's favor, average time to
    resolve, and average move size. Also breaks this down by GEX regime
    (pinning vs acceleration) since the same divergence pattern may
    behave differently in each (see memory/greeks_knowledge.md Part 4) —
    this is the actual answer to Saim's question, built from real
    accumulated evidence, not assumption.
    """
    entries = [e for e in _read_all() if e["status"] == "CLOSED"]
    if not entries:
        return {"total_events": 0, "message": "No divergence events tracked yet."}

    resolved = [e for e in entries if e["resolved"]]
    unresolved = [e for e in entries if not e["resolved"]]

    stats = {
        "total_events": len(entries),
        "resolved_in_ois_favor": len(resolved),
        "did_not_resolve": len(unresolved),
        "resolution_rate_pct": round(len(resolved) / len(entries) * 100, 1),
    }
    if resolved:
        stats["avg_minutes_to_resolve"] = round(sum(e["resolution_minutes"] for e in resolved) / len(resolved), 1)
        stats["avg_move_points"] = round(sum(e["resolution_move_points"] for e in resolved) / len(resolved), 1)

    # Breakdown by GEX regime, where available
    by_regime = {}
    for e in entries:
        regime = e.get("gex_regime") or "unknown"
        key = "pinning" if regime and "PINNING" in str(regime).upper() else ("acceleration" if regime and "ACCELERATION" in str(regime).upper() else "unknown")
        by_regime.setdefault(key, {"total": 0, "resolved": 0})
        by_regime[key]["total"] += 1
        if e["resolved"]:
            by_regime[key]["resolved"] += 1
    for key, d in by_regime.items():
        d["resolution_rate_pct"] = round(d["resolved"] / d["total"] * 100, 1) if d["total"] else None
    stats["breakdown_by_gex_regime"] = by_regime

    return stats


if __name__ == "__main__":
    print(json.dumps(review_divergence_stats(), indent=2))
