"""
post_close_momentum.py — next-day gap bias from post-close continuation
------------------------------------------------------------------------
Direct response to Saim's 17 Aug request: NIFTY/BANKNIFTY CASH index
closes at 15:15/15:30, but FUTURES and OPTIONS keep trading until 15:30
(and options technically later). That extra window of movement often
signals institutional positioning for the next day's open — large
players who couldn't get filled at their target price during the day
sometimes push price in the final minutes toward their desired level,
and that residual momentum frequently carries into the next morning's
gap.

This module reads the FUTURES candles (index futures = cleanest read of
this, no strike-selection noise) from a configurable "post-close window"
(default 15:15-15:30) and reports: net move in that window, direction,
and a simple next-day gap-bias label.

NOTE ON EXPIRY FORMAT: Groww's futures groww_symbol needs the contract
expiry as "DDMmmYY" (e.g. "28Aug25"). This must be the CURRENT MONTH's
NIFTY/BANKNIFTY futures expiry (usually the last Tuesday/Thursday of
the month) — pass it explicitly since we don't have a reliable way to
auto-detect it yet (Groww's Expiries API could do this later).
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groww_api import fetch_candles


def post_close_momentum(symbol, expiry, date_str=None, window_start="15:15:00", window_end="15:30:00"):
    """
    symbol: "NIFTY" or "BANKNIFTY"
    expiry: futures expiry string in "DDMmmYY" format (e.g. "26Aug25")
    date_str: "YYYY-MM-DD", defaults to today
    Returns {net_move, pct_move, direction, gap_bias, candles_seen} or
    raises if the fetch fails (e.g. wrong expiry format/date).
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")

    candles = fetch_candles(
        symbol, f"{date_str} {window_start}", f"{date_str} {window_end}",
        exchange="NSE", segment="FNO", interval_minutes=1, expiry=expiry
    )

    if not candles:
        return {"error": "no candles returned for this window — check expiry format/date"}

    open_price = candles[0]["open"]
    close_price = candles[-1]["close"]
    net_move = close_price - open_price
    pct_move = (net_move / open_price) * 100 if open_price else 0

    if pct_move > 0.05:
        direction = "UP"
        gap_bias = "Mild-to-moderate GAP-UP bias for tomorrow's open"
    elif pct_move < -0.05:
        direction = "DOWN"
        gap_bias = "Mild-to-moderate GAP-DOWN bias for tomorrow's open"
    else:
        direction = "FLAT"
        gap_bias = "No strong directional bias from post-close futures move"

    return {
        "symbol": symbol,
        "date": date_str,
        "window": f"{window_start}-{window_end}",
        "open": open_price,
        "close": close_price,
        "net_move": round(net_move, 2),
        "pct_move": round(pct_move, 3),
        "direction": direction,
        "gap_bias": gap_bias,
        "candles_seen": len(candles),
    }


if __name__ == "__main__":
    import json
    symbol = sys.argv[1] if len(sys.argv) > 1 else "NIFTY"
    expiry = sys.argv[2] if len(sys.argv) > 2 else None
    if not expiry:
        print("Usage: python3 post_close_momentum.py <SYMBOL> <EXPIRY e.g. 26Aug25>")
        sys.exit(1)
    try:
        result = post_close_momentum(symbol, expiry)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"FAILED: {e}")
