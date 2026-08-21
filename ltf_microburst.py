"""
ltf_microburst.py — directional volume-spike detection (futures data)
------------------------------------------------------------------------------
21 Aug 2026: Built after discussing two TradingView indicators (Market
Sessions & Volume Profile by Leviathan — already implemented via
volume_profile.py; LTF Volume Microburst Bubbles by Zeiierman) together
with the SEBI/Copthall CAS-manipulation case (13 Aug 2026: three sharp
IEP spikes, each concentrated in a 2-13 second window, driven by a
single entity's aggressive orders — a textbook "microburst" signature).

CONCEPT (adapted from Zeiierman's approach): rather than looking only
at a candle's TOTAL volume, compare each candle's volume against a
recent baseline (EMA-style), and require the candle to also show
genuine DIRECTIONAL body strength (filters out high-volume
indecision/wick-dominated candles — a spike with no direction isn't a
microburst, it's noise/absorption). Bullish and bearish qualifying
spikes are tracked separately and combined into a directional score.

HONEST SCOPE: this detects volume-CONCENTRATION anomalies using candle
data (already working, futures volume). It does NOT detect the
order-CANCELLATION-rate pattern SEBI found in the Copthall case (place
huge orders, cancel a third after price moves) — that specifically
needs order-book/order-level data, which needs order-flow-depth
(still blocked on Groww/Dhan). This module covers the volume-spike
half of that mechanism, not the spoof-and-cancel half.
"""


def compute_volume_baseline(candles, ema_period=20):
    """Simple EMA of volume over recent candles — the 'normal' baseline
    each new candle's volume gets compared against."""
    volumes = [c.get("volume", 0) for c in candles]
    if len(volumes) < ema_period:
        return None
    multiplier = 2 / (ema_period + 1)
    ema = sum(volumes[:ema_period]) / ema_period
    for v in volumes[ema_period:]:
        ema = (v - ema) * multiplier + ema
    return ema


def compute_directional_efficiency(candle):
    """
    How much of the candle's full range was 'used' for directional
    movement, vs wasted on wicks/indecision. Per Zeiierman's concept:
    body_size / total_range. Returns 0-1 (1 = pure directional move, no
    wicks at all; near 0 = mostly indecision/wicks).
    """
    total_range = candle["high"] - candle["low"]
    if total_range <= 0:
        return 0
    body_size = abs(candle["close"] - candle["open"]) if "open" in candle else abs(candle["close"] - candle.get("close", candle["close"]))
    return round(body_size / total_range, 2)


def detect_microburst(candle, baseline_volume, spike_threshold=2.0, min_directional_efficiency=0.5):
    """
    Checks ONE candle against the baseline for a qualifying microburst.
    spike_threshold: how many multiples of baseline volume counts as a spike
    min_directional_efficiency: minimum body/range ratio to qualify
    (filters wick-dominated high-volume candles — e.g. absorption, not
    a genuine directional burst)

    Returns {"is_microburst": bool, "direction": "BULLISH"/"BEARISH"/None,
    "volume_ratio": float, "directional_efficiency": float}
    """
    if not baseline_volume or baseline_volume <= 0:
        return {"is_microburst": False, "direction": None, "volume_ratio": None, "directional_efficiency": None}

    volume_ratio = candle.get("volume", 0) / baseline_volume
    directional_efficiency = compute_directional_efficiency(candle)

    is_spike = volume_ratio >= spike_threshold
    is_directional = directional_efficiency >= min_directional_efficiency

    if not (is_spike and is_directional):
        return {"is_microburst": False, "direction": None, "volume_ratio": round(volume_ratio, 2),
                "directional_efficiency": directional_efficiency}

    direction = "BULLISH" if candle["close"] >= candle.get("open", candle["close"]) else "BEARISH"
    return {"is_microburst": True, "direction": direction, "volume_ratio": round(volume_ratio, 2),
            "directional_efficiency": directional_efficiency}


def scan_for_microbursts(candles, ema_period=20, spike_threshold=2.0, min_directional_efficiency=0.5):
    """
    Scans a full candle series, returns all qualifying microburst events
    with their index/timestamp — the direct tool for finding SEBI-
    Copthall-style concentrated spike moments in our own historical or
    live data.
    """
    events = []
    for i in range(ema_period, len(candles)):
        baseline = compute_volume_baseline(candles[max(0, i - ema_period - 5):i], ema_period)
        result = detect_microburst(candles[i], baseline, spike_threshold, min_directional_efficiency)
        if result["is_microburst"]:
            events.append({
                "index": i, "timestamp": candles[i].get("timestamp"),
                "close": candles[i]["close"], **result,
            })
    return events
