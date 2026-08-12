"""
Price Momentum / Order-Flow-Proxy Layer (VSA-based)
------------------------------------------------------
Answers the question: "order aane par, trigger hone par price ke andar
kya momentum hota hai?" — using Volume Spread Analysis (VSA), a
Wyckoff-derived method that reads EFFORT (volume) vs RESULT (candle
spread + close position) to infer institutional buying/selling without
needing true Level-2 order-book data (which retail/index data doesn't
give us anyway — see engine's earlier OI-based order-flow proxy for the
options-side equivalent).

CORE PRINCIPLE: Effort vs Result
  - High volume + wide spread + close near high  -> strong genuine demand (bullish)
  - High volume + narrow spread                  -> ABSORPTION (someone is
                                                      defending that level —
                                                      often precedes a reversal)
  - Low volume + wide spread                      -> weak/unsupported move,
                                                      unlikely to sustain
  - Low volume + narrow spread on an up-move       -> NO DEMAND (rally has no
                                                      real buying behind it —
                                                      bearish, esp. at resistance)
  - Low volume + narrow spread on a down-move      -> NO SUPPLY (decline has
                                                      no real selling behind it
                                                      — bullish, esp. at support)
  - Ultra-high volume + wide spread UP, closes off  -> BUYING CLIMAX (retail
    the high (i.e. NOT near the high)                euphoria being sold into
                                                      by smart money — bearish,
                                                      marks potential tops)
  - Ultra-high volume + wide spread DOWN, closes    -> SELLING CLIMAX (panic
    off the low (i.e. NOT near the low)              selling being absorbed by
                                                      smart money — bullish,
                                                      marks potential bottoms)

IMPORTANT DATA LIMITATION (documented 12 Aug 2026): NIFTY/BANKNIFTY index
candles from GrowwMCP do NOT currently include a volume field (indices
aren't directly traded — only futures/options are). groww_api.py's direct
fetch DOES include volume in its response. Until volume is consistently
available:
  - Functions below that need volume (climax/absorption/no-demand/no-supply)
    return None / are skipped gracefully if volume is missing.
  - A volume-free fallback (spread-relative-to-recent-range) is provided as
    a weaker proxy for "wide vs narrow" — genuine effort/result reading
    still needs real volume to be reliable, so treat the fallback as
    informational only, not a scoring input, until volume data is wired in.
"""

def _spread(candle):
    return candle["high"] - candle["low"]


def _close_position(candle):
    """0 = closed at the low, 1 = closed at the high, 0.5 = closed at midpoint."""
    spread = _spread(candle)
    if spread == 0:
        return 0.5
    return (candle["close"] - candle["low"]) / spread


def _avg_spread(candles, lookback=20):
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    return sum(_spread(c) for c in recent) / len(recent) if recent else 0


def _avg_volume(candles, lookback=20):
    vols = [c.get("volume") for c in candles[-lookback:] if c.get("volume") is not None]
    return sum(vols) / len(vols) if vols else None


def classify_bar(candles, index=-1, wide_mult=1.5, narrow_mult=0.6,
                  high_vol_mult=1.5, ultra_vol_mult=2.5, climax_off_thresh=0.35):
    """
    Classifies the candle at `index` (default: most recent) using VSA rules.
    Returns a dict: {label, direction, confidence_note} or None if there's
    not enough history to compare against.

    label is one of: "no_demand", "no_supply", "buying_climax",
    "selling_climax", "absorption_bullish", "absorption_bearish",
    "strong_demand", "strong_supply", "neutral", None (if volume missing)
    """
    if len(candles) < 21:
        return None

    c = candles[index]
    history = candles[:index] if index != -1 else candles[:-1]
    if not history:
        return None

    spread = _spread(c)
    avg_spread = _avg_spread(history)
    close_pos = _close_position(c)
    is_up = c["close"] >= c["open"]

    vol = c.get("volume")
    avg_vol = _avg_volume(history)

    if vol is None or avg_vol is None or avg_vol == 0:
        # Volume-free fallback: spread-only read (weaker signal, informational)
        wide = spread > avg_spread * wide_mult
        narrow = spread < avg_spread * narrow_mult
        return {
            "label": "wide_range" if wide else ("narrow_range" if narrow else "neutral"),
            "direction": "UP" if is_up else "DOWN",
            "confidence_note": "volume unavailable — spread-only proxy, low confidence",
            "has_volume": False,
        }

    vol_ratio = vol / avg_vol
    wide = spread > avg_spread * wide_mult
    narrow = spread < avg_spread * narrow_mult
    high_vol = vol_ratio > high_vol_mult
    ultra_vol = vol_ratio > ultra_vol_mult

    label = "neutral"
    direction = "UP" if is_up else "DOWN"

    if ultra_vol and wide and is_up and close_pos < (1 - climax_off_thresh):
        label = "buying_climax"       # bearish signal despite up-candle
    elif ultra_vol and wide and not is_up and close_pos > climax_off_thresh:
        label = "selling_climax"      # bullish signal despite down-candle
    elif high_vol and narrow and is_up:
        label = "absorption_bearish"  # heavy volume, price can't advance -> hidden selling
    elif high_vol and narrow and not is_up:
        label = "absorption_bullish"  # heavy volume, price can't fall -> hidden buying
    elif (not high_vol) and narrow and is_up:
        label = "no_demand"           # weak rally, low volume
    elif (not high_vol) and narrow and not is_up:
        label = "no_supply"           # weak decline, low volume
    elif high_vol and wide and is_up and close_pos > 0.65:
        label = "strong_demand"       # genuine, validated up-move
    elif high_vol and wide and not is_up and close_pos < 0.35:
        label = "strong_supply"       # genuine, validated down-move

    return {
        "label": label,
        "direction": direction,
        "vol_ratio": round(vol_ratio, 2),
        "close_position": round(close_pos, 2),
        "has_volume": True,
    }


def momentum_bias(candles, lookback_bars=5):
    """
    Scans the last `lookback_bars` candles and returns an overall bullish/
    bearish/neutral lean based on which VSA labels showed up, plus the
    single most recent classified bar for detail.
    """
    if len(candles) < 25:
        return {"lean": "NEUTRAL", "reason": "insufficient history", "recent": None}

    bullish_labels = {"no_supply", "selling_climax", "absorption_bullish", "strong_demand"}
    bearish_labels = {"no_demand", "buying_climax", "absorption_bearish", "strong_supply"}

    bull_count, bear_count = 0, 0
    last_signal = None
    for i in range(-lookback_bars, 0):
        result = classify_bar(candles, index=i)
        if result is None or not result.get("has_volume"):
            continue
        if result["label"] in bullish_labels:
            bull_count += 1
            last_signal = result
        elif result["label"] in bearish_labels:
            bear_count += 1
            last_signal = result

    if bull_count > bear_count:
        lean = "BULLISH"
    elif bear_count > bull_count:
        lean = "BEARISH"
    else:
        lean = "NEUTRAL"

    return {
        "lean": lean,
        "bullish_signals": bull_count,
        "bearish_signals": bear_count,
        "recent": last_signal,
    }


if __name__ == "__main__":
    import json
    with open("data/daily_store/NIFTY_5min_log.jsonl") as f:
        lines = [json.loads(l) for l in f]
    today = lines[-1]
    result = momentum_bias(today["candles"])
    print(json.dumps(result, indent=2))
