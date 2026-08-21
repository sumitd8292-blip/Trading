"""
volume_profile.py — POC/Value-Area from candle+volume data (no Order Flow API needed)
------------------------------------------------------------------------------
21 Aug 2026: Confirmed (via Dhan's own team on their community forum) that
the rich "Order Flow" feature (tick-by-tick executed trades, Delta, POC
per-candle) is UI-only, NOT available via any API. But we don't need it
for a genuinely useful Volume Profile / Point of Control — we already
have FUTURES candle data WITH REAL VOLUME (confirmed working since 18-19
Aug, used for the VSA layer) — that's enough to compute a classic
session/period Volume Profile ourselves: bucket volume by price level
across candles, find which price level traded the most total volume
(POC), and the range containing 70% of volume (Value Area).

This is the SAME underlying concept Saim referenced from the Leviathan
TradingView indicator (19 Aug discussion) and the "SG Orderflow"
HTF/LTF framework research (19 Aug) — genuinely buildable now with data
we already have, not blocked on order-flow-depth or Dhan's Order Flow API.
"""
from collections import defaultdict


def compute_volume_profile(candles, price_bucket_size=25):
    """
    candles: list of {close, volume, high, low, ...} — typically futures
    candles (real volume), any timeframe/period (a day, a week, N days).
    price_bucket_size: rounds prices to the nearest N points for bucketing
    (25 is reasonable for NIFTY; use larger for less granularity/noise,
    smaller for more precision).

    Returns: {poc_price, poc_volume, value_area_high, value_area_low,
    total_volume, profile} where profile is {bucket_price: volume} for
    every traded level, sorted by price.

    Approximates each candle's volume as concentrated at its CLOSE price
    (simplification — a true tick-level profile would spread volume
    across the candle's full range, but this close-price approximation
    is standard practice when only OHLCV candles are available, and is
    what most retail Volume Profile tools do without tick data).
    """
    if not candles:
        return None

    volume_by_bucket = defaultdict(float)
    for c in candles:
        vol = c.get("volume") or 0
        if vol <= 0:
            continue
        bucket = round(c["close"] / price_bucket_size) * price_bucket_size
        volume_by_bucket[bucket] += vol

    if not volume_by_bucket:
        return None

    total_volume = sum(volume_by_bucket.values())
    poc_price = max(volume_by_bucket, key=volume_by_bucket.get)
    poc_volume = volume_by_bucket[poc_price]

    # Value Area: expand outward from POC until 70% of total volume is captured
    sorted_buckets = sorted(volume_by_bucket.keys())
    poc_idx = sorted_buckets.index(poc_price)
    captured = poc_volume
    lo_idx, hi_idx = poc_idx, poc_idx
    while captured < total_volume * 0.70 and (lo_idx > 0 or hi_idx < len(sorted_buckets) - 1):
        vol_below = volume_by_bucket[sorted_buckets[lo_idx - 1]] if lo_idx > 0 else -1
        vol_above = volume_by_bucket[sorted_buckets[hi_idx + 1]] if hi_idx < len(sorted_buckets) - 1 else -1
        if vol_above >= vol_below:
            hi_idx += 1
            captured += volume_by_bucket[sorted_buckets[hi_idx]]
        else:
            lo_idx -= 1
            captured += volume_by_bucket[sorted_buckets[lo_idx]]

    return {
        "poc_price": poc_price,
        "poc_volume": round(poc_volume, 0),
        "value_area_high": sorted_buckets[hi_idx],
        "value_area_low": sorted_buckets[lo_idx],
        "total_volume": round(total_volume, 0),
        "profile": {p: round(v, 0) for p, v in sorted(volume_by_bucket.items())},
    }


def check_price_reaction_at_level(candles, level, tolerance=15, lookback_after_touch=10):
    """
    Given a price level (e.g. a POC from a prior period) and a candle
    series, checks whether/when price later "touches" that level and
    what happened afterward (bounce/reject vs breakthrough) — the
    direct test of "does POC act as support/resistance", per Saim's
    19 Aug observation about NIFTY's 6-19 Aug decline reversing near a
    marked POC level.
    """
    touches = []
    for i, c in enumerate(candles):
        if abs(c["close"] - level) <= tolerance:
            if i + lookback_after_touch < len(candles):
                after = candles[i + lookback_after_touch]
                move = after["close"] - c["close"]
                touches.append({
                    "touch_index": i, "touch_price": c["close"],
                    "price_after": after["close"], "move_points": round(move, 1),
                })
    return touches
