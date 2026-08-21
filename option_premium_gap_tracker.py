"""
option_premium_gap_tracker.py — ATM strike premium move, close to open
------------------------------------------------------------------------------
21 Aug 2026: Saim's request — beyond just tracking the INDEX level's
overnight gap (pre_open_signal_tracker.py, GIFT NIFTY-based), also
track the actual OPTION PREMIUM move for the strike that was ATM at
close, comparing its premium then vs its premium at next day's open.
Saim's reasoning: this is the directly tradeable number — option
premiums often move by a very different PERCENTAGE than the index does
(Delta/Gamma amplify or dampen the index-point move), so knowing the
index gapped X points doesn't tell you how much the actual Call/Put you'd
be holding moved. Saim wants both CE and PE tracked, and whether the
premium moved up or down and by how much, as a foundational dataset for
building a proper order-flow-based strategy later.
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OPTION_GAP_LOG_PATH = os.path.join(BASE, "memory", "option_premium_gap_events.jsonl")


def _read_all():
    if not os.path.exists(OPTION_GAP_LOG_PATH):
        return []
    with open(OPTION_GAP_LOG_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(OPTION_GAP_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def log_eod_atm_snapshot(symbol, date_str, atm_strike, ce_ltp, pe_ltp, spot_at_close, timestamp_iso):
    """
    Call once near end-of-day (~3:25-3:28 PM, before the option-chain
    stops updating for the day) with the ATM strike's Call/Put LTP and
    the spot price at that moment. This becomes the "yesterday's close"
    reference point for tomorrow's gap comparison.
    """
    entries = _read_all()
    entries = [e for e in entries if not (e["symbol"] == symbol and e["date"] == date_str)]  # replace if re-logged same day
    event = {
        "symbol": symbol, "date": date_str,
        "atm_strike": atm_strike, "ce_ltp_at_close": ce_ltp, "pe_ltp_at_close": pe_ltp,
        "spot_at_close": spot_at_close,
        "logged_at": timestamp_iso,
        "status": "OPEN",
        "next_day_date": None, "ce_ltp_at_open": None, "pe_ltp_at_open": None, "spot_at_open": None,
        "ce_gap_points": None, "ce_gap_pct": None, "pe_gap_points": None, "pe_gap_pct": None,
    }
    entries.append(event)
    _write_all(entries)
    return event


def check_next_day_open(symbol, prev_date_str, next_date_str, ce_ltp_open, pe_ltp_open, spot_at_open, timestamp_iso):
    """
    Call once near next day's open (~9:16-9:20 AM) with the SAME strike's
    (from yesterday's EOD snapshot) Call/Put LTP now, plus current spot.
    Computes the overnight premium gap for both CE and PE — the direct
    answer to "how much did the actual option move overnight/at-open".
    """
    entries = _read_all()
    closed = None
    for event in entries:
        if event["symbol"] == symbol and event["date"] == prev_date_str and event["status"] == "OPEN":
            ce_gap = ce_ltp_open - event["ce_ltp_at_close"]
            pe_gap = pe_ltp_open - event["pe_ltp_at_close"]
            ce_gap_pct = round(ce_gap / event["ce_ltp_at_close"] * 100, 1) if event["ce_ltp_at_close"] else None
            pe_gap_pct = round(pe_gap / event["pe_ltp_at_close"] * 100, 1) if event["pe_ltp_at_close"] else None

            event["status"] = "CLOSED"
            event["next_day_date"] = next_date_str
            event["ce_ltp_at_open"] = ce_ltp_open
            event["pe_ltp_at_open"] = pe_ltp_open
            event["spot_at_open"] = spot_at_open
            event["ce_gap_points"] = round(ce_gap, 2)
            event["ce_gap_pct"] = ce_gap_pct
            event["pe_gap_points"] = round(pe_gap, 2)
            event["pe_gap_pct"] = pe_gap_pct
            event["closed_at"] = timestamp_iso
            closed = event
    _write_all(entries)
    return closed


def review_option_gap_stats():
    """Reports accumulated overnight premium-gap statistics for ATM
    Calls and Puts — average magnitude, direction split, and how this
    compares to typical index-point gaps (context for a future order-
    flow-based strategy, per Saim's stated purpose)."""
    entries = [e for e in _read_all() if e["status"] == "CLOSED"]
    if not entries:
        return {"total_days": 0, "message": "No option premium-gap data yet."}

    ce_pcts = [abs(e["ce_gap_pct"]) for e in entries if e.get("ce_gap_pct") is not None]
    pe_pcts = [abs(e["pe_gap_pct"]) for e in entries if e.get("pe_gap_pct") is not None]
    ce_up_days = sum(1 for e in entries if (e.get("ce_gap_points") or 0) > 0)
    pe_up_days = sum(1 for e in entries if (e.get("pe_gap_points") or 0) > 0)

    return {
        "total_days_tracked": len(entries),
        "avg_ce_gap_pct": round(sum(ce_pcts) / len(ce_pcts), 1) if ce_pcts else None,
        "avg_pe_gap_pct": round(sum(pe_pcts) / len(pe_pcts), 1) if pe_pcts else None,
        "ce_moved_up_days": ce_up_days, "ce_moved_down_days": len(entries) - ce_up_days,
        "pe_moved_up_days": pe_up_days, "pe_moved_down_days": len(entries) - pe_up_days,
    }


if __name__ == "__main__":
    print(json.dumps(review_option_gap_stats(), indent=2))
