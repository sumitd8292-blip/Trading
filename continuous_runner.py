"""
continuous_runner.py — VPS entry point (runs 24x7, active only during market hours)
--------------------------------------------------------------------------------------
This is the VPS version of the agent — replaces the GitHub-Actions-based
run_agent_check.py for live automation, because Groww's API requires a
registered STATIC IP, which GitHub Actions can't provide (random IP per
run) but a VPS can (one fixed IP, registered once in Groww's dashboard).

What it does, every LOOP_INTERVAL_SECONDS (default 60 = 1-minute, per
Saim's 11 Aug 2026 request for finer granularity):
  1. Fetches today's candles so far for NIFTY + BANKNIFTY via Groww's
     direct API (groww_api.py)
  2. Saves them into data/daily_store/ (same format as before)
  3. Scores the setup via engine.py (price+momentum, plus OI order-flow
     if a snapshot is available)
  4. Sends a Telegram alert if the (symbol,date,signal,score) combo
     hasn't been alerted yet today (dedup, same as before)
  5. Sleeps until market hours if run outside 9:15-15:30 IST, Mon-Fri

Run this under systemd (see deploy.md) so it restarts automatically and
survives reboots / crashes.
"""

import time
import sys
import os
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist():
    return datetime.now(IST)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from daily_store import append_intraday_candles
from engine import score_setup, log_signal
from telegram_notify import send_telegram_message, format_signal_alert
from groww_api import fetch_candles, fetch_option_chain
from run_agent_check import latest_oi_bias, _alert_key, _load_alerted, _mark_alerted
from paper_trader import open_paper_trade, check_open_trades
from price_momentum import momentum_bias
from smc import smc_bias as get_smc_bias
from groww_option_chain import parse_option_chain, compute_gamma_exposure, compute_oi_and_iv_bias

LOOP_INTERVAL_SECONDS = 60  # 1-minute granularity
MARKET_OPEN = dtime(9, 12)
MARKET_CLOSE = dtime(15, 40)
SYMBOLS = ["NIFTY", "BANKNIFTY"]
OPTION_CHAIN_REFRESH_LOOPS = 5  # fetch live option chain every 5 loops (~5 min), not every 1 min — it's a heavier call
_option_chain_loop_counter = 0
_latest_live_oi_bias = {}   # symbol -> latest live OI/PCR dict (replaces stale manual CSV snapshot)
_latest_live_gex = {}       # symbol -> latest live Gamma Exposure dict


def get_next_tuesday_expiry(from_date=None):
    """
    NIFTY (and SENSEX) have WEEKLY expiry, currently on Tuesdays
    (observed: 11-Aug, 18-Aug, 25-Aug 2026 are all Tuesdays). Returns
    today's date if today IS a Tuesday (expiry day itself), else the
    next upcoming Tuesday, formatted as YYYY-MM-DD.
    NOTE: NSE could change the weekly expiry day again — if fetches
    start failing with "no data", this is the first thing to check.
    """
    from datetime import timedelta
    d = from_date or now_ist().date()
    days_ahead = (1 - d.weekday()) % 7  # Monday=0 ... Tuesday=1
    target = d + timedelta(days=days_ahead)
    return target.strftime("%Y-%m-%d")


def get_monthly_expiry(from_date=None):
    """
    BANKNIFTY has MONTHLY expiry (unlike NIFTY/SENSEX which are weekly)
    — per Saim's 18 Aug 2026 correction. Currently falls on the LAST
    Tuesday of the month. Returns that date; if it has already passed
    this month, rolls to next month's last Tuesday.
    """
    from datetime import timedelta
    import calendar
    d = from_date or now_ist().date()

    def last_tuesday_of_month(year, month):
        last_day = calendar.monthrange(year, month)[1]
        last_date = datetime(year, month, last_day).date()
        offset = (last_date.weekday() - 1) % 7  # back up to Tuesday=1
        return last_date - timedelta(days=offset)

    this_month_expiry = last_tuesday_of_month(d.year, d.month)
    if d <= this_month_expiry:
        return this_month_expiry.strftime("%Y-%m-%d")
    # already passed — roll to next month
    next_month = d.month + 1 if d.month < 12 else 1
    next_year = d.year if d.month < 12 else d.year + 1
    return last_tuesday_of_month(next_year, next_month).strftime("%Y-%m-%d")


# Per-symbol expiry calculators — NIFTY/SENSEX weekly, BANKNIFTY monthly
_EXPIRY_CALCULATORS = {
    "NIFTY": get_next_tuesday_expiry,
    "BANKNIFTY": get_monthly_expiry,
}


def refresh_live_option_chain():
    """
    Fetches live option chain for NIFTY (weekly expiry) + BANKNIFTY
    (monthly expiry — see _EXPIRY_CALCULATORS), computes OI/PCR and
    Gamma Exposure, and updates the module-level caches used by
    run_once(). Called every OPTION_CHAIN_REFRESH_LOOPS iterations (not
    every loop — it's a heavier call than a plain candle fetch).
    """
    for symbol in SYMBOLS:
        expiry = _EXPIRY_CALCULATORS.get(symbol, get_next_tuesday_expiry)()
        try:
            payload = fetch_option_chain(symbol, expiry)
            spot = payload.get("underlying_ltp") if isinstance(payload, dict) else None
            rows = parse_option_chain(payload)
            if not rows or not spot:
                print(f"[{now_ist()}] {symbol}: option chain empty/no spot (expiry={expiry})")
                continue
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: option chain fetch failed for {expiry} — {e}")
            continue

        oi_iv = compute_oi_and_iv_bias(rows, spot)
        pcr = oi_iv["pcr"]
        lean = "BEARISH" if pcr > 1.1 else ("BULLISH" if pcr < 0.9 else "NEUTRAL")
        _latest_live_oi_bias[symbol] = {
            "lean": lean, "pcr": pcr,
            "resistance_strike": oi_iv["resistance_strike"],
            "support_strike": oi_iv["support_strike"],
        }
        gex = compute_gamma_exposure(rows, spot)
        _latest_live_gex[symbol] = gex
        print(f"[{now_ist()}] {symbol}: live option chain refreshed (expiry={expiry}) — "
              f"OI lean={lean} PCR={pcr}, GEX regime={gex.get('regime') if gex else 'n/a'}")


def is_market_hours(now=None):
    now = now or now_ist()
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def run_once():
    global _option_chain_loop_counter
    today = now_ist().strftime("%Y-%m-%d")
    alerted = _load_alerted()

    # Refresh live option chain (OI/PCR + Gamma Exposure) every N loops
    if _option_chain_loop_counter % OPTION_CHAIN_REFRESH_LOOPS == 0:
        refresh_live_option_chain()
    _option_chain_loop_counter += 1

    for symbol in SYMBOLS:
        try:
            candles = fetch_candles(symbol, f"{today} 09:15:00",
                                     now_ist().strftime("%Y-%m-%d %H:%M:%S"),
                                     interval_minutes=1)
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: fetch failed — {e}")
            continue

        if not candles:
            print(f"[{now_ist()}] {symbol}: no candles yet")
            continue

        append_intraday_candles(symbol, candles, interval_label="1min")

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        # Prefer live option-chain OI (refreshed every ~5 min) over the old
        # manual CSV snapshot — falls back to the manual snapshot only if
        # live fetch hasn't succeeded yet this run
        oi_bias = _latest_live_oi_bias.get(symbol) or latest_oi_bias(symbol)
        vsa_bias = momentum_bias(candles)
        s_bias = get_smc_bias(candles)
        result = score_setup(closes, highs, lows, oi_bias=oi_bias, vsa_bias=vsa_bias, smc_bias=s_bias, candles_for_trend=candles)
        log_signal(symbol, result, note=f"VPS continuous run, {today}")

        # Self-generated paper trading (added 17 Aug 2026, Saim's request for
        # faster learning): check/close any open paper trade against latest
        # candle every tick, and open a NEW one whenever a fresh signal fires
        # — independent of whether a Telegram alert was sent (dedup only
        # controls Telegram noise, not the learning data).
        closed = check_open_trades(symbol, candles, is_eod=(now_ist().time() >= MARKET_CLOSE))
        for c in closed:
            print(f"[{now_ist()}] {symbol}: PAPER TRADE CLOSED — {c['outcome']} {c['outcome_points']:+.1f} pts ({c['exit_reason']})")

        if result["signal"] != "NONE":
            open_paper_trade(symbol, today, result["signal"], closes[-1],
                              result.get("sl_points", 15), result.get("target_points", 25),
                              result.get("layer_status", {}), result["score"], result["reasons"])

        if result["signal"] == "NONE":
            print(f"[{now_ist()}] {symbol}: no signal ({len(candles)} candles)")
            continue

        key = _alert_key(symbol, today, result["signal"], result["score"])
        if key in alerted:
            print(f"[{now_ist()}] {symbol}: signal already alerted today, skipping")
            continue

        msg = format_signal_alert(symbol, result) + f"\n\nData date: {today} (live, VPS)"
        send_result = send_telegram_message(msg)
        print(f"[{now_ist()}] {symbol}: ALERT SENT — {send_result.get('ok')}")
        if send_result.get("ok"):
            _mark_alerted(key)
            alerted.add(key)


def main():
    print(f"[{now_ist()}] continuous_runner starting. Loop interval: {LOOP_INTERVAL_SECONDS}s")
    while True:
        try:
            if is_market_hours():
                run_once()
            else:
                print(f"[{now_ist()}] outside market hours, sleeping")
        except Exception as e:
            print(f"[{now_ist()}] UNEXPECTED ERROR: {e}")
        time.sleep(LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
