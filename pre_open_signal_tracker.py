"""
pre_open_signal_tracker.py — does GIFT NIFTY predict NIFTY's opening move?
------------------------------------------------------------------------------
21 Aug 2026: Saim's request — combine YESTERDAY'S closing futures order-
flow with TODAY'S pre-open session order-punching (9:00-9:15) into one
"predicted direction" signal, then check whether NIFTY's actual first
few minutes after open (9:15+) genuinely move in that predicted
direction. Track this EVERY DAY — "this data is always valuable."

SIMPLIFIED IMPLEMENTATION: rather than needing full order-flow-depth
(bid/ask punching detail — still blocked, see order_flow_depth.py
investigation), GIFT NIFTY itself is a ready-made combined signal —
it already reflects overnight global cues + pre-market positioning by
the time NSE opens. GIFT NIFTY vs NIFTY's previous close gives the
"predicted gap direction" directly. This can be extended later to
also fold in raw pre-open order-flow-depth once that's unblocked
(GIFT NIFTY confirmed working via Dhan MCP, securityId=5024, IDX_I).

HYPOTHESIS TRACKED: does the sign/magnitude of (GIFT_NIFTY - prev_close)
predict the sign/magnitude of NIFTY's actual move in the first 5 (and
15) minutes after 9:15 open? This is Saim's "order police" check —
literally checking whether the pre-market order-flow "witness" was
telling the truth about where price would actually go.
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
PRE_OPEN_LOG_PATH = os.path.join(BASE, "memory", "pre_open_signal_events.jsonl")


def _read_all():
    if not os.path.exists(PRE_OPEN_LOG_PATH):
        return []
    with open(PRE_OPEN_LOG_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(PRE_OPEN_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def log_pre_open_signal(symbol, date_str, gift_nifty_value, prev_close, timestamp_iso):
    """
    Call this once, right around 9:14-9:15 AM (just before NIFTY opens),
    with GIFT NIFTY's current reading and NIFTY's previous session close.
    Computes the implied gap direction and magnitude, logs it as an
    OPEN prediction event to be checked against the actual opening move.
    """
    implied_gap = gift_nifty_value - prev_close
    implied_direction = "UP" if implied_gap > 0 else ("DOWN" if implied_gap < 0 else "FLAT")

    entries = _read_all()
    already_open = any(e["symbol"] == symbol and e["date"] == date_str and e["status"] == "OPEN" for e in entries)
    if already_open:
        return None

    event = {
        "symbol": symbol, "date": date_str,
        "gift_nifty_value": gift_nifty_value, "prev_close": prev_close,
        "implied_gap_points": round(implied_gap, 2), "implied_direction": implied_direction,
        "logged_at": timestamp_iso,
        "status": "OPEN",
        "actual_5min_move": None, "actual_15min_move": None,
        "prediction_correct_5min": None, "prediction_correct_15min": None,
    }
    entries.append(event)
    _write_all(entries)
    return event


def check_actual_open_move(symbol, date_str, price_5min_after_open, price_15min_after_open, open_price, timestamp_iso):
    """
    Call this once, after enough post-open candles exist (~9:20 and
    ~9:30 AM), with NIFTY's actual price at +5min and +15min from open,
    plus the actual 9:15 open price itself. Closes the OPEN event,
    comparing GIFT NIFTY's implied direction against what really
    happened — the direct answer to "was the pre-market signal telling
    the truth".
    """
    entries = _read_all()
    closed = None
    for event in entries:
        if event["symbol"] == symbol and event["date"] == date_str and event["status"] == "OPEN":
            move_5min = price_5min_after_open - open_price
            move_15min = price_15min_after_open - open_price
            actual_dir_5min = "UP" if move_5min > 0 else ("DOWN" if move_5min < 0 else "FLAT")
            actual_dir_15min = "UP" if move_15min > 0 else ("DOWN" if move_15min < 0 else "FLAT")

            event["status"] = "CLOSED"
            event["actual_5min_move"] = round(move_5min, 2)
            event["actual_15min_move"] = round(move_15min, 2)
            event["prediction_correct_5min"] = (event["implied_direction"] == actual_dir_5min)
            event["prediction_correct_15min"] = (event["implied_direction"] == actual_dir_15min)
            event["closed_at"] = timestamp_iso
            closed = event
    _write_all(entries)
    return closed


def review_pre_open_accuracy():
    """Reports GIFT NIFTY's actual hit-rate as a pre-open directional
    signal, at both 5-min and 15-min horizons — the real, accumulated
    answer to Saim's question, built from daily tracking, not a guess."""
    entries = [e for e in _read_all() if e["status"] == "CLOSED"]
    if not entries:
        return {"total_days": 0, "message": "No pre-open signal events tracked yet."}

    correct_5min = sum(1 for e in entries if e["prediction_correct_5min"])
    correct_15min = sum(1 for e in entries if e["prediction_correct_15min"])

    return {
        "total_days_tracked": len(entries),
        "accuracy_5min_pct": round(correct_5min / len(entries) * 100, 1),
        "accuracy_15min_pct": round(correct_15min / len(entries) * 100, 1),
        "avg_implied_gap_points": round(sum(abs(e["implied_gap_points"]) for e in entries) / len(entries), 1),
    }


if __name__ == "__main__":
    print(json.dumps(review_pre_open_accuracy(), indent=2))
