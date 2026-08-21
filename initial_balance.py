"""
initial_balance.py — first-hour range + volume-supported breakout detection
------------------------------------------------------------------------------
21 Aug 2026: per Saim's explicit instruction to research Market Profile
theory in depth and implement carefully (checked multiple times).

Initial Balance (IB) = the high-low range of the FIRST HOUR of trading
(9:15-10:15 IST for NSE). Per Market Profile theory (Dalton/Steidlmayer):
- If price BREAKS OUT of the IB with genuine volume support → a TREND
  DAY is likely developing
- If price STAYS WITHIN the IB → a RANGE/BALANCE DAY is more likely

This is the EARLIEST actionable signal for classifying a day's likely
character — available within the first hour, well before the full
day's Volume Profile can be computed.
"""
from datetime import time as dtime, datetime

IB_START = dtime(9, 15)
IB_END = dtime(10, 15)


def compute_initial_balance(day_candles, min_coverage_pct=0.7):
    """
    Given a day's candles (from market open) at ANY interval (1-min,
    5-min, 15-min), returns the Initial Balance high/low from the
    first hour. Returns None if insufficient data (fewer than
    min_coverage_pct of the expected candle count for the IB window,
    based on the ACTUAL detected candle interval — not hardcoded to
    assume 1-min bars, which was a real bug caught during testing:
    at 15-min resolution only ~4 candles exist in a 60-min window, so
    a hardcoded "30 candles minimum" always failed).
    """
    def _time_of(c):
        return datetime.fromisoformat(c["timestamp"]).time()

    ib_candles = [c for c in day_candles if IB_START <= _time_of(c) < IB_END]
    if len(ib_candles) < 2:
        return None

    # Detect actual candle interval from consecutive timestamps
    t1 = datetime.fromisoformat(ib_candles[0]["timestamp"])
    t2 = datetime.fromisoformat(ib_candles[1]["timestamp"])
    interval_minutes = max(1, (t2 - t1).total_seconds() / 60)
    expected_candles = 60 / interval_minutes

    if len(ib_candles) < expected_candles * min_coverage_pct:
        return None

    return {
        "ib_high": max(c["high"] for c in ib_candles),
        "ib_low": min(c["low"] for c in ib_candles),
        "candle_count": len(ib_candles),
        "detected_interval_minutes": interval_minutes,
    }


def detect_ib_breakout(current_price, current_volume, ib_high, ib_low,
                        avg_volume_baseline, volume_support_multiplier=1.3):
    """
    Checks whether the CURRENT candle represents a genuine, volume-
    supported break of the Initial Balance range — not just a wick
    poking through on low volume (which per theory suggests the range
    will likely hold, i.e. a range/balance day).

    volume_support_multiplier: current volume must be at least this
    many times the baseline to count as "supported" (1.3x is a
    moderate, not extreme, threshold — deliberately conservative per
    Saim's "no room for error" instruction, avoiding over-fitting to
    noise).

    Returns {"breakout": bool, "direction": "UP"/"DOWN"/None,
    "volume_supported": bool}
    """
    if current_price > ib_high:
        direction = "UP"
    elif current_price < ib_low:
        direction = "DOWN"
    else:
        return {"breakout": False, "direction": None, "volume_supported": False}

    volume_supported = (current_volume >= avg_volume_baseline * volume_support_multiplier) if avg_volume_baseline else False

    return {
        "breakout": True,
        "direction": direction,
        "volume_supported": volume_supported,
        "likely_trend_day": volume_supported,  # per theory: unsupported break = weak signal, likely fails back into range
    }
