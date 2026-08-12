"""
Options OI Order-Flow Layer
----------------------------
Parses NSE-style option chain CSV exports (the format downloaded from
NSE's option chain page: "CALLS,,PUTS" header row, then OI/CHNG IN
OI/VOLUME/IV/LTP/CHNG/BID/ASK/STRIKE/... columns) and computes the
order-flow bias signals that feed into engine.py's scoring rubric.

Logic (per Saim's original framework, 9-10 Aug 2026 discussion):
  - Call OI buildup + price falling  -> resistance forming (bearish)
  - Put OI buildup + price rising    -> support forming (bullish)
  - PCR (Put OI / Call OI): >1 leans bullish-contrarian (heavy put
    writing = support), <1 leans bearish-contrarian (heavy call
    writing = resistance) — used directionally, not as a hard rule
  - Max-OI strikes mark the nearest strong support/resistance zones
"""

import csv
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))


def _num(x):
    x = x.strip().replace(",", "")
    if x in ("-", ""):
        return 0.0
    try:
        return float(x)
    except ValueError:
        return 0.0


def parse_option_chain_csv(path):
    """
    Returns a list of {strike, call_oi, call_chg_oi, call_iv, call_ltp,
    put_oi, put_chg_oi, put_iv, put_ltp} dicts, one per strike.
    Expects the standard NSE option-chain CSV column layout:
    [blank, OI, CHNG IN OI, VOLUME, IV, LTP, CHNG, BID QTY, BID, ASK,
     ASK QTY, STRIKE, BID QTY, BID, ASK, ASK QTY, CHNG, LTP, IV, VOLUME,
     CHNG IN OI, OI]
    """
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)  # "CALLS,,PUTS" header
        next(reader)  # column names
        for r in reader:
            if len(r) < 22:
                continue
            strike = _num(r[11])
            if strike == 0:
                continue
            rows.append({
                "strike": strike,
                "call_oi": _num(r[1]), "call_chg_oi": _num(r[2]),
                "call_iv": _num(r[4]), "call_ltp": _num(r[5]),
                "put_ltp": _num(r[17]), "put_iv": _num(r[18]),
                "put_chg_oi": _num(r[20]), "put_oi": _num(r[21]),
            })
    return rows


def compute_oi_bias(rows, spot_price=None):
    """
    Returns a summary dict with PCR, max-OI strikes (support/resistance),
    OI-change bias, and a simple LONG/SHORT/NEUTRAL lean.
    spot_price (optional): if given, restricts max-OI search to nearby
    strikes (+-10%) so far OTM open interest doesn't dominate the read.
    """
    if not rows:
        return None

    if spot_price:
        lo, hi = spot_price * 0.9, spot_price * 1.1
        near = [r for r in rows if lo <= r["strike"] <= hi]
        if near:
            rows = near

    total_call_oi = sum(r["call_oi"] for r in rows)
    total_put_oi = sum(r["put_oi"] for r in rows)
    total_call_chg = sum(r["call_chg_oi"] for r in rows)
    total_put_chg = sum(r["put_chg_oi"] for r in rows)
    pcr = (total_put_oi / total_call_oi) if total_call_oi else 0

    max_call_row = max(rows, key=lambda r: r["call_oi"])
    max_put_row = max(rows, key=lambda r: r["put_oi"])

    # Directional lean: PCR alone is weak, combine with OI-change direction
    # Call OI building up faster than Put OI => resistance strengthening => bearish lean
    # Put OI building up faster than Call OI => support strengthening => bullish lean
    if total_put_chg > total_call_chg and total_put_chg > 0:
        lean = "BULLISH"
    elif total_call_chg > total_put_chg and total_call_chg > 0:
        lean = "BEARISH"
    else:
        lean = "NEUTRAL"

    return {
        "pcr": round(pcr, 3),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "total_call_oi_change": total_call_chg,
        "total_put_oi_change": total_put_chg,
        "resistance_strike": max_call_row["strike"],
        "support_strike": max_put_row["strike"],
        "lean": lean,
    }


def snapshot_from_csv(path, symbol, spot_price=None):
    """Full pipeline: parse CSV -> compute bias -> return a snapshot dict
    ready for daily_store.append_options_snapshot()."""
    rows = parse_option_chain_csv(path)
    bias = compute_oi_bias(rows, spot_price=spot_price)
    if bias is None:
        return None
    bias["symbol"] = symbol
    bias["source_file"] = os.path.basename(path)
    bias["strikes_parsed"] = len(rows)
    return bias


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 oi_orderflow.py <csv_path> <symbol> [spot_price]")
        sys.exit(1)
    path, symbol = sys.argv[1], sys.argv[2]
    spot = float(sys.argv[3]) if len(sys.argv) > 3 else None
    snap = snapshot_from_csv(path, symbol, spot_price=spot)
    print(json.dumps(snap, indent=2))
