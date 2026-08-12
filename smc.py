"""
SMC Layer — Smart Money Concepts (Market Structure + Fair Value Gaps)
------------------------------------------------------------------------
Pure price-action layer (no volume needed — complements VSA which does
need volume). Implements the core SMC toolkit used to read "smart money"
footprints from swing structure alone:

1. SWING POINTS (fractals): a candle is a swing high if its high is the
   highest among `lookback` candles on either side; swing low similarly.
2. BOS (Break of Structure): price closes beyond the most recent swing
   high (bullish BOS) or swing low (bearish BOS) IN THE DIRECTION of the
   prevailing trend — a continuation signal.
3. CHoCH (Change of Character): price closes beyond a swing point AGAINST
   the prevailing trend — the first sign smart money may be reversing
   the trend, generally weighted more heavily than a same-direction BOS.
4. FVG (Fair Value Gap / imbalance): a 3-candle pattern where candle 1's
   high is below candle 3's low (bullish FVG — an untraded price gap
   that price often returns to "fill") or candle 1's low is above
   candle 3's high (bearish FVG). Large, unfilled FVGs mark zones smart
   money left behind and often act as support/resistance on return.

None of this requires Level-2 data — it's read entirely from OHLC swing
structure, which is exactly what's available from GrowwMCP/Groww candles.
"""


def find_swing_points(candles, lookback=3):
    """
    Returns two lists of indices: (swing_high_indices, swing_low_indices).
    A candle at index i is a swing high if its high is >= all highs in
    [i-lookback, i+lookback]; swing low is the mirror on lows.
    """
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    n = len(candles)

    swing_highs, swing_lows = [], []
    for i in range(lookback, n - lookback):
        window_highs = highs[i - lookback:i + lookback + 1]
        window_lows = lows[i - lookback:i + lookback + 1]
        if highs[i] == max(window_highs):
            swing_highs.append(i)
        if lows[i] == min(window_lows):
            swing_lows.append(i)
    return swing_highs, swing_lows


def detect_structure(candles, lookback=3):
    """
    Looks at the most recent swing high and swing low, and checks whether
    the LATEST close has broken beyond either of them. Determines the
    prevailing trend from the sequence of the last two swing highs/lows
    (higher-highs+higher-lows = uptrend, lower-highs+lower-lows =
    downtrend) to classify a break as BOS (continuation) or CHoCH
    (reversal).

    Returns a dict: {event: "BOS"|"CHoCH"|None, direction: "UP"|"DOWN",
    trend: "UP"|"DOWN"|"UNCLEAR", broken_level: float} or None if not
    enough swing history exists yet.
    """
    swing_highs, swing_lows = find_swing_points(candles, lookback=lookback)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    last_close = candles[-1]["close"]
    last_swing_high_idx = swing_highs[-1]
    last_swing_low_idx = swing_lows[-1]
    last_swing_high = candles[last_swing_high_idx]["high"]
    last_swing_low = candles[last_swing_low_idx]["low"]

    # Determine prevailing trend from the last two swing highs and lows
    prev_swing_high = candles[swing_highs[-2]]["high"]
    prev_swing_low = candles[swing_lows[-2]]["low"]

    higher_high = last_swing_high > prev_swing_high
    higher_low = last_swing_low > prev_swing_low
    lower_high = last_swing_high < prev_swing_high
    lower_low = last_swing_low < prev_swing_low

    if higher_high and higher_low:
        trend = "UP"
    elif lower_high and lower_low:
        trend = "DOWN"
    else:
        trend = "UNCLEAR"

    # Has the latest close broken beyond a swing point AFTER it formed?
    event, direction, broken_level = None, None, None
    if last_swing_high_idx < len(candles) - 1 and last_close > last_swing_high:
        direction = "UP"
        broken_level = last_swing_high
        event = "BOS" if trend == "UP" else ("CHoCH" if trend == "DOWN" else "BOS")
    elif last_swing_low_idx < len(candles) - 1 and last_close < last_swing_low:
        direction = "DOWN"
        broken_level = last_swing_low
        event = "BOS" if trend == "DOWN" else ("CHoCH" if trend == "UP" else "BOS")

    return {"event": event, "direction": direction, "trend": trend, "broken_level": broken_level}


def find_recent_fvgs(candles, lookback_bars=15, min_gap_pct=0.02):
    """
    Scans the last `lookback_bars` candles for 3-candle Fair Value Gaps.
    min_gap_pct: minimum gap size as a % of price to count (filters noise).
    Returns a list of {type: "bullish"|"bearish", gap_low, gap_high, index}.
    """
    fvgs = []
    start = max(2, len(candles) - lookback_bars)
    for i in range(start, len(candles)):
        c1, c3 = candles[i - 2], candles[i]
        if c1["high"] < c3["low"]:
            gap_size_pct = (c3["low"] - c1["high"]) / c1["high"] * 100
            if gap_size_pct >= min_gap_pct:
                fvgs.append({"type": "bullish", "gap_low": c1["high"], "gap_high": c3["low"], "index": i})
        elif c1["low"] > c3["high"]:
            gap_size_pct = (c1["low"] - c3["high"]) / c3["high"] * 100
            if gap_size_pct >= min_gap_pct:
                fvgs.append({"type": "bearish", "gap_low": c3["high"], "gap_high": c1["low"], "index": i})
    return fvgs


def smc_bias(candles, lookback=3):
    """
    Combines structure (BOS/CHoCH) and recent FVGs into an overall
    BULLISH/BEARISH/NEUTRAL lean. CHoCH is weighted more heavily than a
    same-direction BOS since it flags a potential trend reversal.
    """
    if len(candles) < (lookback * 2 + 5):
        return {"lean": "NEUTRAL", "reason": "insufficient history for swing detection"}

    structure = detect_structure(candles, lookback=lookback)
    fvgs = find_recent_fvgs(candles)

    lean = "NEUTRAL"
    reasons = []

    if structure and structure["event"]:
        if structure["event"] == "CHoCH":
            lean = "BULLISH" if structure["direction"] == "UP" else "BEARISH"
            reasons.append(f"CHoCH detected: {structure['direction']} break of "
                            f"{structure['broken_level']:.1f} against {structure['trend']} trend")
        elif structure["event"] == "BOS":
            lean = "BULLISH" if structure["direction"] == "UP" else "BEARISH"
            reasons.append(f"BOS detected: {structure['direction']} break of "
                            f"{structure['broken_level']:.1f} continuing {structure['trend']} trend")

    if fvgs:
        last_fvg = fvgs[-1]
        reasons.append(f"Recent {last_fvg['type']} FVG at {last_fvg['gap_low']:.1f}-{last_fvg['gap_high']:.1f}")

    return {
        "lean": lean,
        "structure": structure,
        "recent_fvg_count": len(fvgs),
        "last_fvg": fvgs[-1] if fvgs else None,
        "reasons": reasons,
    }


if __name__ == "__main__":
    import json
    with open("data/daily_store/NIFTY_5min_log.jsonl") as f:
        lines = [json.loads(l) for l in f]
    today = lines[-1]
    result = smc_bias(today["candles"])
    print(json.dumps(result, indent=2, default=str))
