"""
multi_timeframe_context.py — daily/1-hour trend awareness
------------------------------------------------------------------------
19 Aug 2026 discussion: the agent currently reasons only on 1-min data
in isolation — it doesn't know if today's move is happening WITHIN a
multi-day downtrend, or against it. Saim's example: NIFTY has been
declining steadily since 24-Jul (confirmed via daily candles), and
today's price action needs to be read in that context — a bounce today
means something different in a multi-day downtrend than in a multi-day
uptrend.

This computes a simple EMA-based trend read on DAILY and 1-HOUR
candles, to be logged alongside every signal as CONTEXT (not a new
trigger) — answering "is this signal working with or against the
higher-timeframe trend".
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import ema


def compute_timeframe_trend(candles, ema_period=20):
    """
    candles: list of {close, ...} at ANY single timeframe (daily, 1H,
    whatever the caller fetched). Returns {trend, last_close, ema_value,
    pct_from_ema} — a simple "price vs its own EMA" read at that timeframe.
    """
    if len(candles) < ema_period:
        return {"trend": "INSUFFICIENT_DATA", "candles_available": len(candles)}

    closes = [c["close"] for c in candles]
    e = ema(closes, ema_period)
    last_close = closes[-1]
    ema_value = e[-1]
    pct_from_ema = round((last_close - ema_value) / ema_value * 100, 2)

    trend = "UP" if last_close > ema_value else "DOWN"

    return {
        "trend": trend,
        "last_close": last_close,
        "ema_value": round(ema_value, 2),
        "pct_from_ema": pct_from_ema,
    }


def get_multi_timeframe_context(daily_candles, hourly_candles):
    """
    Combines daily + 1-hour trend reads into one context dict. This is
    meant to be logged alongside every 1-min signal (via paper_trader's
    layer_status-style tagging) — NOT used to block/allow trades, just
    to give post-hoc analysis the ability to ask "did signals aligned
    with the higher-timeframe trend perform better than counter-trend
    signals" once enough data accumulates.
    """
    daily_ctx = compute_timeframe_trend(daily_candles, ema_period=20)
    hourly_ctx = compute_timeframe_trend(hourly_candles, ema_period=20)

    aligned = None
    if daily_ctx.get("trend") in ("UP", "DOWN") and hourly_ctx.get("trend") in ("UP", "DOWN"):
        aligned = daily_ctx["trend"] == hourly_ctx["trend"]

    return {
        "daily": daily_ctx,
        "hourly": hourly_ctx,
        "timeframes_aligned": aligned,
    }
