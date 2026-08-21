"""
range_breakout.py — Box 15: catches breakouts from consolidation
------------------------------------------------------------------------------
21 Aug 2026, Saim's priority #4 of 5. Origin: 20 Aug's manual chart
review found a genuine ~47pt NIFTY rally (24,217→24,264, 12:40-12:50 PM)
that NEITHER RSI-Reversal nor Trend-Continuation caught — RSI-Reversal
needs prior oversold-then-recovery (price was just chopping, not
oversold); Trend-Continuation needs already-aligned momentum in the
preceding candles (price was choppy: up-down-up-flat, not aligned).
This is a genuinely DIFFERENT pattern type: a sudden breakout FROM a
tight consolidation, which needs its own detector.

Two-step logic:
1. detect_consolidation(): are the last N candles genuinely tight-ranged
   (not trending, not choppy-wide) — i.e. is this a "coiled spring"?
2. detect_range_breakout(): has price now moved decisively beyond that
   tight range, with a real point-move (not just noise)?
"""


def detect_consolidation(candles, lookback=8, max_range_points=15):
    """
    Checks whether the last `lookback` candles have been trading in a
    genuinely TIGHT range — the "coiled spring" precondition for a
    breakout to be meaningful. max_range_points: how tight the
    high-low range of the lookback window must be to count as
    consolidating (15pts chosen to roughly match the ~24,210-24,217
    7pt range Saim's 20 Aug example showed before its breakout —
    conservative buffer above that).

    Returns {"is_consolidating": bool, "range_high": float,
    "range_low": float, "range_points": float}
    """
    if len(candles) < lookback:
        return {"is_consolidating": False, "range_high": None, "range_low": None, "range_points": None}

    window = candles[-lookback:]
    range_high = max(c["high"] for c in window)
    range_low = min(c["low"] for c in window)
    range_points = range_high - range_low

    return {
        "is_consolidating": range_points <= max_range_points,
        "range_high": range_high, "range_low": range_low, "range_points": round(range_points, 1),
    }


def detect_range_breakout(current_price, consolidation, breakout_confirmation_points=10):
    """
    Given a consolidation range (from detect_consolidation) and the
    current price, checks whether price has broken out DECISIVELY
    (beyond the range by at least breakout_confirmation_points — not
    just a marginal 1-2pt poke, which could be noise).

    Returns {"signal": "LONG"/"SHORT"/"NONE", "reason": str,
    "breakout_range": the consolidation range that was broken}
    """
    if not consolidation.get("is_consolidating"):
        return {"signal": "NONE", "reason": "no active consolidation to break out from"}

    range_high = consolidation["range_high"]
    range_low = consolidation["range_low"]

    if current_price >= range_high + breakout_confirmation_points:
        return {
            "signal": "LONG",
            "reason": f"breakout above {breakout_confirmation_points}pt-confirmed consolidation "
                      f"({range_low}-{range_high}, {consolidation['range_points']}pt range)",
            "breakout_range": (range_low, range_high),
        }
    elif current_price <= range_low - breakout_confirmation_points:
        return {
            "signal": "SHORT",
            "reason": f"breakdown below {breakout_confirmation_points}pt-confirmed consolidation "
                      f"({range_low}-{range_high}, {consolidation['range_points']}pt range)",
            "breakout_range": (range_low, range_high),
        }
    return {"signal": "NONE", "reason": "still within/near consolidation range"}
