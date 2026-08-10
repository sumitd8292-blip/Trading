"""
Order-Flow Agent — Core Engine (v0.1)
---------------------------------------
Separate system from FlowDesk. Purpose: build a self-improving, memory-backed
agent that scores NIFTY/BANKNIFTY setups using price-structure + momentum now,
and will incorporate FII/DII bias, options OI order-flow, Greeks, and SMC
structure as those data sources come online.

Design principles (per Saim's instructions):
  - Agent must NOT be a "dumb" cold-start bot — it starts with lessons already
    learned from historical backtesting (see memory/lessons.json).
  - Alert-only. This engine NEVER places trades. It only scores setups and
    (once wired up) sends Telegram alerts. Final entry decision stays manual.
  - Every signal + outcome gets logged to memory/trade_log.jsonl so the agent
    can review its own track record and adjust weights over time.
"""

import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(BASE, "memory")
DATA_DIR = os.path.join(BASE, "data")
LESSONS_PATH = os.path.join(MEMORY_DIR, "lessons.json")
TRADE_LOG_PATH = os.path.join(MEMORY_DIR, "trade_log.jsonl")

os.makedirs(MEMORY_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def ema(values, period):
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values, period=14):
    gains, losses = [0], [0]
    for i in range(1, len(values)):
        chg = values[i] - values[i - 1]
        gains.append(max(chg, 0))
        losses.append(max(-chg, 0))
    if len(values) <= period:
        return [50] * len(values)
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    rsis = [50] * (period + 1)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        rsis.append(100 - 100 / (1 + rs))
    return rsis


# ---------------------------------------------------------------------------
# Scoring rubric (v0.1 — price-structure + momentum only)
# Weights will shift once FII/DII, OI, Greeks, SMC layers are added.
# This is intentionally conservative until more confirmation layers exist.
# ---------------------------------------------------------------------------

RUBRIC_VERSION = "0.1-price-momentum-only"

# Best baseline found in backtesting (9 Aug 2026 session):
# RSI 40/60 threshold + EMA20 trend filter + SL 15 / TGT 25 -> 42.9% WR,
# +88 pts net over 90 days (positive via ~1.67:1 reward:risk, not high WR).
DEFAULT_PARAMS = {
    "rsi_period": 14,
    "rsi_lookback": 10,
    "oversold_th": 40,
    "overbought_th": 60,
    "ema_period": 20,
    "sl_points": 15,
    "target_points": 25,
}


def score_setup(closes, highs, lows, params=None):
    """
    Returns a dict: {signal: LONG|SHORT|NONE, score: 0-10, reasons: [...]}
    Pure price/momentum score for now (max achievable = 6/10 until
    FII/DII + OI + Greeks + SMC layers are wired in).
    """
    p = params or DEFAULT_PARAMS
    if len(closes) < max(p["ema_period"], p["rsi_period"]) + 5:
        return {"signal": "NONE", "score": 0, "reasons": ["insufficient data"]}

    e = ema(closes, p["ema_period"])
    r = rsi(closes, p["rsi_period"])

    i = len(closes) - 1
    above_ema = closes[i] > e[i]
    prev_above = closes[i - 1] > e[i - 1]
    recent_rsi = r[max(0, i - p["rsi_lookback"]):i]
    was_oversold = any(x < p["oversold_th"] for x in recent_rsi)
    was_overbought = any(x > p["overbought_th"] for x in recent_rsi)

    reasons = []
    signal = "NONE"
    score = 0

    long_ok = was_oversold and r[i - 1] < 50 <= r[i] and above_ema
    short_ok = was_overbought and r[i - 1] > 50 >= r[i] and not above_ema

    if long_ok:
        signal = "LONG"
        score += 3
        reasons.append("RSI recovered through 50 from oversold zone")
        score += 2
        reasons.append("Price above EMA20 (trend filter aligned)")
    elif short_ok:
        signal = "SHORT"
        score += 3
        reasons.append("RSI broke through 50 from overbought zone")
        score += 2
        reasons.append("Price below EMA20 (trend filter aligned)")
    else:
        reasons.append("No confirmed price/momentum setup")

    # Placeholder slots for future layers (currently contribute 0 — not yet built)
    reasons.append("FII/DII bias: NOT YET INTEGRATED (0/2)")
    reasons.append("OI order-flow: NOT YET INTEGRATED (0/2)")
    reasons.append("Greeks (Delta/Theta): NOT YET INTEGRATED (0/1)")
    reasons.append("SMC structure: NOT YET INTEGRATED (0/1)")

    return {
        "signal": signal,
        "score": score,
        "max_possible_today": 6,   # out of eventual 10 once all layers added
        "sl_points": p["sl_points"],
        "target_points": p["target_points"],
        "reasons": reasons,
        "rubric_version": RUBRIC_VERSION,
    }


# ---------------------------------------------------------------------------
# Memory: lessons learned (loaded at startup so agent isn't a cold-start dummy)
# ---------------------------------------------------------------------------

def load_lessons():
    if not os.path.exists(LESSONS_PATH):
        return {}
    with open(LESSONS_PATH) as f:
        return json.load(f)


def log_signal(symbol, setup_result, note=""):
    """Append a signal event to the persistent trade log (JSONL)."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "signal": setup_result.get("signal"),
        "score": setup_result.get("score"),
        "rubric_version": setup_result.get("rubric_version"),
        "reasons": setup_result.get("reasons"),
        "note": note,
        "outcome": None,   # to be filled in later once trade plays out
    }
    with open(TRADE_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


if __name__ == "__main__":
    lessons = load_lessons()
    print(f"Loaded {len(lessons)} lesson categories from memory.")
    print(f"Rubric version: {RUBRIC_VERSION}")
