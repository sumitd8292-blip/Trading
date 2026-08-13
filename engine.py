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


def score_setup(closes, highs, lows, params=None, oi_bias=None, vsa_bias=None, fii_bias=None, greeks_bias=None, smc_bias=None):
    """
    Returns a dict: {signal: LONG|SHORT|NONE, score: 0-10, reasons: [...]}
    oi_bias: optional dict from oi_orderflow.compute_oi_bias() — if given,
    contributes up to 2 points when it AGREES with the price/momentum
    signal direction (BULLISH agrees with LONG, BEARISH agrees with SHORT).
    Max achievable score is currently 8/10 (price+momentum 5, OI 2, plus a
    same-direction alignment bonus of 1) until FII/DII + Greeks + SMC are
    wired in too.
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

    # FII/DII bias layer (wired up 12 Aug 2026)
    if signal != "NONE" and fii_bias is not None and fii_bias.get("lean") != "NEUTRAL":
        f_lean = fii_bias.get("lean")
        if (signal == "LONG" and f_lean == "BULLISH") or (signal == "SHORT" and f_lean == "BEARISH"):
            score += 2
            reasons.append(f"FII/DII AGREES: {f_lean} (net {fii_bias.get('total_net_crores')} Cr "
                            f"over {fii_bias.get('days_considered')}d) (+2/2)")
        else:
            reasons.append(f"FII/DII DISAGREES: {f_lean} lean vs {signal} signal — treat with caution (0/2)")
    elif fii_bias is not None:
        f_lean = fii_bias.get("lean", "NEUTRAL")
        if signal == "NONE":
            reasons.append(f"FII/DII: {f_lean} noted, but no active price signal to apply it to (0/2)")
        else:
            reasons.append(f"FII/DII: neutral (0/2)")
    else:
        reasons.append("FII/DII bias: NOT YET INTEGRATED (0/2)")

    # OI order-flow layer (wired up 11 Aug 2026)
    if signal != "NONE" and oi_bias is not None:
        lean = oi_bias.get("lean", "NEUTRAL")
        if (signal == "LONG" and lean == "BULLISH") or (signal == "SHORT" and lean == "BEARISH"):
            score += 2
            reasons.append(f"OI order-flow AGREES: {lean} lean (PCR {oi_bias.get('pcr')}, "
                            f"resistance {oi_bias.get('resistance_strike')}, "
                            f"support {oi_bias.get('support_strike')}) (+2/2)")
        elif lean == "NEUTRAL":
            reasons.append(f"OI order-flow NEUTRAL (PCR {oi_bias.get('pcr')}) (0/2)")
        else:
            reasons.append(f"OI order-flow DISAGREES: {lean} lean vs {signal} signal — "
                            f"treat with caution (0/2)")
    elif oi_bias is not None:
        reasons.append(f"OI order-flow: no active signal to confirm ({oi_bias.get('lean')} lean noted) (0/2)")
    else:
        reasons.append("OI order-flow: NOT YET INTEGRATED (0/2)")

    # Price-momentum / VSA order-flow-proxy layer (added 12 Aug 2026)
    if signal != "NONE" and vsa_bias is not None and vsa_bias.get("lean") != "NEUTRAL":
        v_lean = vsa_bias.get("lean")
        if (signal == "LONG" and v_lean == "BULLISH") or (signal == "SHORT" and v_lean == "BEARISH"):
            score += 1
            recent = vsa_bias.get("recent") or {}
            reasons.append(f"Price-momentum (VSA) AGREES: {v_lean} "
                            f"({vsa_bias.get('bullish_signals')} bullish vs "
                            f"{vsa_bias.get('bearish_signals')} bearish bars recently, "
                            f"last: {recent.get('label')}) (+1/1)")
        else:
            reasons.append(f"Price-momentum (VSA) DISAGREES: {v_lean} lean vs {signal} signal (0/1)")
    elif vsa_bias is not None:
        reasons.append("Price-momentum (VSA): neutral/no volume data yet (0/1)")
    else:
        reasons.append("Price-momentum (VSA): NOT YET INTEGRATED (0/1)")

    # Greeks / IV-skew layer (wired up 12 Aug 2026)
    if signal != "NONE" and greeks_bias is not None and greeks_bias.get("lean") != "NEUTRAL":
        g_lean = greeks_bias.get("lean")
        if (signal == "LONG" and g_lean == "BULLISH") or (signal == "SHORT" and g_lean == "BEARISH"):
            score += 1
            reasons.append(f"Greeks/IV-skew AGREES: {g_lean} (skew {greeks_bias.get('skew_pct')}%, "
                            f"OTM put IV {greeks_bias.get('otm_put_iv')} vs "
                            f"OTM call IV {greeks_bias.get('otm_call_iv')}) (+1/1)")
        else:
            reasons.append(f"Greeks/IV-skew DISAGREES: {g_lean} lean vs {signal} signal (0/1)")
    elif greeks_bias is not None:
        g_lean2 = greeks_bias.get("lean", "NEUTRAL")
        if signal == "NONE" and g_lean2 != "NEUTRAL":
            reasons.append(f"Greeks/IV-skew: {g_lean2} noted, but no active price signal to apply it to (0/1)")
        else:
            reasons.append(f"Greeks/IV-skew: neutral (skew {greeks_bias.get('skew_pct')}%) (0/1)")
    else:
        reasons.append("Greeks (IV-skew): NOT YET INTEGRATED (0/1)")

    # SMC (market structure / BOS-CHoCH / FVG) layer (wired up 12 Aug 2026)
    if signal != "NONE" and smc_bias is not None and smc_bias.get("lean") != "NEUTRAL":
        s_lean = smc_bias.get("lean")
        structure = smc_bias.get("structure") or {}
        weight = 2 if structure.get("event") == "CHoCH" else 1  # CHoCH weighted higher than BOS
        if (signal == "LONG" and s_lean == "BULLISH") or (signal == "SHORT" and s_lean == "BEARISH"):
            score += weight
            reasons.append(f"SMC AGREES: {s_lean} ({structure.get('event')} — "
                            f"{'; '.join(smc_bias.get('reasons', []))}) (+{weight}/2)")
        else:
            reasons.append(f"SMC DISAGREES: {s_lean} lean vs {signal} signal (0/2)")
    elif smc_bias is not None:
        s_lean2 = smc_bias.get("lean", "NEUTRAL")
        if signal == "NONE" and s_lean2 != "NEUTRAL":
            reasons.append(f"SMC: {s_lean2} noted, but no active price signal to apply it to (0/2)")
        else:
            reasons.append("SMC: neutral, no clear BOS/CHoCH (0/2)")
    else:
        reasons.append("SMC structure: NOT YET INTEGRATED (0/2)")

    return {
        "signal": signal,
        "score": score,
        "max_possible_today": 13,   # price+momentum(5) + OI(2) + VSA(1) + FII/DII(2) + Greeks(1) + SMC(2, CHoCH weighted) = 13; all planned layers now wired
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
