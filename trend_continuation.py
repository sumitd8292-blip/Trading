"""
Trend-Continuation Detector
------------------------------
Answers exactly Saim's 17 Aug feedback: the existing RSI-reversal engine
only catches the SNAP-BACK after a trend exhausts — it structurally
cannot participate in an ongoing directional run (e.g. market opens and
sells off steadily for 2 hours, or rallies steadily for 2 hours). This
module detects that kind of move WHILE IT'S HAPPENING.

CONCEPT: "sellers are active right now, market likely continues down for
the next few minutes" — read directly from recent candle-to-candle
direction, without waiting for any oversold/overbought extreme.

This is intentionally a SEPARATE signal source from engine.py's RSI-
reversal logic — a live market can have either a reversal setup or a
trend-continuation setup active (or neither), and they call for
different targets (reversal = smaller, range-bound scalp; continuation
= larger, ride-the-move). This module only detects the ENTRY moment;
sizing/targets are handled elsewhere.
"""


def detect_trend_continuation(candles, lookback=5, min_directional_bars=4, min_move_pct=0.08):
    """
    Looks at the last `lookback` candles. If at least `min_directional_bars`
    of them moved the same direction (close > prev close, or close < prev
    close) AND the net move over the window exceeds `min_move_pct`, fires
    immediately — this is designed to catch a trend within minutes of it
    starting, not after it's already reversed.

    Returns {signal: LONG|SHORT, bars_aligned, move_pct, window_start,
    window_end} or None if no continuation move is currently active.
    """
    if len(candles) < lookback + 1:
        return None

    recent = candles[-lookback:]
    closes = [c["close"] for c in recent]

    up_bars = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    down_bars = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
    net_move_pct = (closes[-1] - closes[0]) / closes[0] * 100

    if up_bars >= min_directional_bars and net_move_pct > min_move_pct:
        return {
            "signal": "LONG",
            "bars_aligned": up_bars,
            "move_pct": round(net_move_pct, 3),
            "window_start": recent[0]["timestamp"],
            "window_end": recent[-1]["timestamp"],
        }
    elif down_bars >= min_directional_bars and net_move_pct < -min_move_pct:
        return {
            "signal": "SHORT",
            "bars_aligned": down_bars,
            "move_pct": round(net_move_pct, 3),
            "window_start": recent[0]["timestamp"],
            "window_end": recent[-1]["timestamp"],
        }
    return None


if __name__ == "__main__":
    import json
    with open("data/daily_store/NIFTY_5min_log.jsonl") as f:
        lines = [json.loads(l) for l in f]
    today = lines[-1]
    result = detect_trend_continuation(today["candles"])
    print(json.dumps(result, indent=2) if result else "No active trend-continuation move.")
