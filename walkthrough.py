"""
walkthrough.py — rolling minute-by-minute simulation of today's data
------------------------------------------------------------------------
Direct response to Saim's 17 Aug request: don't just look at the full
day in hindsight — walk through it candle-by-candle AS IF LIVE, and
report exactly when trend_continuation / SMC would have fired, how many
points each captured, and be explicit about what data is and isn't
actually available for a "buyer vs seller" read.

IMPORTANT HONESTY NOTE (read before trusting the buyer/seller section):
NIFTY/BANKNIFTY INDEX candles from Groww do not include volume (indices
aren't directly traded — only futures/options are). So there is NO true
buyer-vs-seller (volume delta / order-flow) data available from this
candle series. What this script CAN show:
  - trend_continuation's candle-direction read (close > prev close = an
    up bar, not proof of "more buyers" — just price closed higher)
  - SMC structure events (BOS/CHoCH) as they would have appeared in
    real time
It CANNOT show real buyer/seller counts or volume — that would need
either (a) futures data with volume, or (b) options OI data at fine
time resolution (we only have periodic manual OI snapshots, not
continuous). This is flagged explicitly in the output rather than
faking a number.
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groww_api import fetch_candles
from trend_continuation import detect_trend_continuation
from smc import smc_bias
from telegram_notify import send_telegram_message


def walkthrough(symbol):
    today = datetime.now().strftime("%Y-%m-%d")
    candles = fetch_candles(symbol, f"{today} 09:15:00", f"{today} 15:30:00", interval_minutes=5)
    if not candles:
        return f"{symbol}: no data.\n"

    lines = [f"<b>{symbol} — minute-by-minute walkthrough, {today}</b>", ""]
    lines.append("⚠️ No true buyer/seller volume data available for index candles "
                  "(see script docstring) — direction below is CLOSE-vs-PREV-CLOSE only, "
                  "not actual order-flow.")
    lines.append("")

    active_trend = None  # tracks an open simulated trend-continuation position
    entry_price = None
    entry_time = None

    for i in range(6, len(candles) + 1):
        window = candles[:i]
        t = window[-1]["timestamp"][11:16]
        price = window[-1]["close"]

        # 1. Check trend-continuation trigger (rolling, as if live)
        tc = detect_trend_continuation(window)

        if active_trend is None and tc:
            active_trend = tc["signal"]
            entry_price = price
            entry_time = t
            lines.append(f"🟢 {t}: TREND-CONTINUATION {tc['signal']} triggers "
                          f"({tc['bars_aligned']}/5 bars aligned, {tc['move_pct']}% net move) "
                          f"@ {price:.1f}")

        elif active_trend:
            # Check for exit: SMC CHoCH against the active trend direction
            structure = (smc_bias(window).get("structure") or {})
            reversed_against = (
                (active_trend == "LONG" and structure.get("event") == "CHoCH" and structure.get("direction") == "DOWN")
                or (active_trend == "SHORT" and structure.get("event") == "CHoCH" and structure.get("direction") == "UP")
            )
            if reversed_against:
                pts = (price - entry_price) if active_trend == "LONG" else (entry_price - price)
                lines.append(f"🔴 {t}: SMC CHoCH detected AGAINST the {active_trend} trend — "
                              f"would exit here @ {price:.1f} | captured {pts:+.1f} pts "
                              f"(held {entry_time}→{t})")
                active_trend = None
                entry_price = None

    if active_trend:
        # still open at end of day
        final_price = candles[-1]["close"]
        pts = (final_price - entry_price) if active_trend == "LONG" else (entry_price - final_price)
        lines.append(f"🟡 EOD: {active_trend} trend still open, held {entry_time}→15:30 | "
                      f"unrealized {pts:+.1f} pts (would need manual exit decision)")

    if len(lines) <= 4:
        lines.append("No trend-continuation signals fired today for this symbol.")

    return "\n".join(lines)


def main():
    for symbol in ["NIFTY", "BANKNIFTY"]:
        try:
            report = walkthrough(symbol)
        except Exception as e:
            report = f"{symbol}: walkthrough failed — {e}"
        print(report)
        send_telegram_message("🔍 " + report)


if __name__ == "__main__":
    main()
