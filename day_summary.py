"""
day_summary.py — one-off / on-demand full-day analysis report
------------------------------------------------------------------
Fetches today's full-day candles (NIFTY + BANKNIFTY), runs them through
every layer, and sends a detailed Telegram summary: overall bias,
key hourly moves, VSA buyer/seller reads, SMC structure events, and
every point where the engine's rubric would have fired (even sub-threshold).

Run manually on the VPS: python3 day_summary.py
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groww_api import fetch_candles
from engine import score_setup, ema, rsi
from price_momentum import momentum_bias, classify_bar
from smc import smc_bias, detect_structure
from run_agent_check import latest_oi_bias, latest_greeks_bias
from fii_dii import get_latest_manual_fii_bias
from telegram_notify import send_telegram_message


def analyze_symbol(symbol):
    today = datetime.now().strftime("%Y-%m-%d")
    candles = fetch_candles(symbol, f"{today} 09:15:00", f"{today} 15:30:00", interval_minutes=5)
    if not candles:
        return f"{symbol}: no data available for today.\n"

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    day_open = candles[0]["open"]
    day_close = closes[-1]
    day_high = max(highs)
    day_low = min(lows)
    pct_move = (day_close - day_open) / day_open * 100

    # Hour-by-hour snapshot (every ~12 candles = 1 hour on 5-min data)
    hourly = []
    for i in range(0, len(candles), 12):
        chunk = candles[i:i+12]
        if not chunk:
            continue
        t = chunk[0]["timestamp"][11:16]
        o, c = chunk[0]["open"], chunk[-1]["close"]
        move = c - o
        hourly.append(f"{t}: {o:.1f}→{c:.1f} ({move:+.1f})")

    vsa = momentum_bias(candles)
    smc = smc_bias(candles)
    oi = latest_oi_bias(symbol)
    greeks = latest_greeks_bias(symbol)
    fii = get_latest_manual_fii_bias()

    result = score_setup(closes, highs, lows, oi_bias=oi, vsa_bias=vsa, fii_bias=fii,
                          greeks_bias=greeks, smc_bias=smc)

    lines = [f"<b>{symbol} — {today}</b>"]
    lines.append(f"Open {day_open:.1f} | High {day_high:.1f} | Low {day_low:.1f} | Close {day_close:.1f}")
    lines.append(f"Day move: {pct_move:+.2f}%")
    lines.append("")
    lines.append("<b>Hourly:</b>")
    lines.extend(hourly[:7])
    lines.append("")
    lines.append(f"<b>SMC structure:</b> {smc.get('lean')} "
                  f"({(smc.get('structure') or {}).get('event') or 'no BOS/CHoCH'})")
    lines.append(f"<b>VSA (buyer/seller read):</b> {vsa.get('lean')} "
                  f"({vsa.get('bullish_signals')} bullish vs {vsa.get('bearish_signals')} bearish bars)")
    if oi:
        lines.append(f"<b>OI order-flow:</b> {oi.get('lean')} (PCR {oi.get('pcr')})")
    if greeks:
        lines.append(f"<b>Greeks/IV-skew:</b> {greeks.get('lean')} (skew {greeks.get('skew_pct')}%)")
    if fii:
        lines.append(f"<b>FII/DII:</b> {fii.get('lean')} (net {fii.get('total_net_crores')} Cr)")
    lines.append("")
    lines.append(f"<b>Engine's final read:</b> Signal={result['signal']}, Score={result['score']}/{result['max_possible_today']}")
    for r in result["reasons"]:
        lines.append(f"• {r}")

    return "\n".join(lines)


def main():
    for symbol in ["NIFTY", "BANKNIFTY"]:
        try:
            report = analyze_symbol(symbol)
        except Exception as e:
            report = f"{symbol}: analysis failed — {e}"
        print(report)
        send_telegram_message("📊 " + report)


if __name__ == "__main__":
    main()
