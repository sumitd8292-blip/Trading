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
from groww_option_chain import parse_option_chain, compute_gamma_exposure, compute_oi_and_iv_bias, suggest_strike, estimate_premium_move, compute_volume_profile
from divergence_tracker import detect_and_log_divergence, check_divergence_resolution
from expiry_close_tracker import analyze_close_window, PRE_CLOSE_WINDOW_START
from greeks_bias import compute_greeks_bias
from fii_dii import get_latest_manual_fii_bias
from order_flow_depth import compute_depth_imbalance, detect_absorption
from absorption_tracker import log_absorption_event, check_absorption_resolution
from groww_api import fetch_quote_depth, fetch_ltp
from order_size_anomaly import record_snapshot, check_for_anomaly
from multi_timeframe_context import get_multi_timeframe_context
from fvg_touch_tracker import check_fvg_touch, check_touch_resolution
from session_behavior_tracker import analyze_session_split
from smc import find_recent_fvgs
from footprint_proxy import classify_trade_aggression, record_footprint_sample, get_footprint_summary, check_trend_footprint_shift

LOOP_INTERVAL_SECONDS = 60  # 1-minute granularity
MARKET_OPEN = dtime(9, 0)  # CHANGED 21 Aug 2026 per Saim's request — start data
                            # collection from 9:00 (NSE pre-open session start),
                            # not 9:12, since orders genuinely get punched during
                            # the 9:00-9:15 pre-open window (order collection
                            # 9:00-9:08, price discovery/matching 9:08-9:12,
                            # buffer 9:12-9:15) and this activity is valuable
                            # data for a future pre-market/pre-order strategy.
MARKET_CLOSE = dtime(15, 40)
SYMBOLS = ["NIFTY", "BANKNIFTY"]
OPTION_CHAIN_REFRESH_LOOPS = 3  # fetch live option chain/VIX/depth every 3 loops (~3 min), not every 1 min — it's a heavier call
_option_chain_loop_counter = 0
_latest_live_oi_bias = {}   # symbol -> latest live OI/PCR dict (replaces stale manual CSV snapshot)
_latest_live_gex = {}       # symbol -> latest live Gamma Exposure dict
_latest_option_rows = {}    # symbol -> (rows, spot) — full chain, for strike suggestions in alerts
_latest_volume_profile = {} # symbol -> live option-volume activity dict
_close_window_start_snapshot = {}  # symbol -> option rows captured at ~15:15, for expiry_close_tracker
_close_window_analyzed_today = {}  # symbol -> date already analyzed (avoid re-running every loop tick)
_mtf_context = {}  # symbol -> multi-timeframe (daily/1H) trend context, refreshed periodically
_mtf_last_refresh_date = {}  # symbol -> date MTF context was last fetched (once/day is enough)
_pre_open_signal_logged_date = None  # date the pre-open signal was already logged today
_pre_open_signal_checked_date = None  # date the actual-move check was already done today
_option_gap_eod_logged_date = None  # date the EOD ATM-strike premium snapshot was logged
_option_gap_open_checked_date = None  # date the next-day-open premium check was done


def _get_atm_ce_pe_ltp(symbol):
    """Helper: finds the ATM strike's CE/PE LTP + spot from the cached
    live option chain (already fetched by refresh_live_option_chain()).
    Returns (strike, ce_ltp, pe_ltp, spot) or None if unavailable."""
    chain_data = _latest_option_rows.get(symbol)
    if not chain_data:
        return None
    rows, spot = chain_data
    atm_row = min(rows, key=lambda r: abs(r["strike"] - spot))
    if not atm_row.get("call") or not atm_row.get("put"):
        return None
    ce_ltp = atm_row["call"].get("ltp")
    pe_ltp = atm_row["put"].get("ltp")
    if ce_ltp is None or pe_ltp is None:
        return None
    return atm_row["strike"], ce_ltp, pe_ltp, spot


def check_eod_option_snapshot(symbol):
    """
    Runs once daily around 3:25-3:28 PM: captures the ATM strike's CE/PE
    premium as the "yesterday's close" reference for tomorrow's gap
    check — per Saim's 21 Aug request to track option premium moves
    overnight, not just index points.
    """
    global _option_gap_eod_logged_date
    today_str = now_ist().strftime("%Y-%m-%d")
    if _option_gap_eod_logged_date == today_str:
        return
    try:
        from option_premium_gap_tracker import log_eod_atm_snapshot
        result = _get_atm_ce_pe_ltp(symbol)
        if not result:
            return
        strike, ce_ltp, pe_ltp, spot = result
        log_eod_atm_snapshot(symbol, today_str, strike, ce_ltp, pe_ltp, spot, now_ist().isoformat())
        print(f"[{now_ist()}] {symbol}: EOD option snapshot logged — strike={strike}, CE={ce_ltp}, PE={pe_ltp}")
        _option_gap_eod_logged_date = today_str
    except Exception as e:
        print(f"[{now_ist()}] {symbol}: EOD option snapshot failed (non-fatal) — {e}")


def check_next_day_option_gap(symbol):
    """
    Runs once daily around 9:17-9:20 AM: captures the SAME ATM strike's
    CE/PE premium now, compares against yesterday's EOD snapshot.
    """
    global _option_gap_open_checked_date
    today_str = now_ist().strftime("%Y-%m-%d")
    if _option_gap_open_checked_date == today_str:
        return
    try:
        from option_premium_gap_tracker import check_next_day_open
        from datetime import timedelta
        yesterday_str = (now_ist().date() - timedelta(days=1)).isoformat()
        # also try 3 days back in case of a weekend gap
        result = _get_atm_ce_pe_ltp(symbol)
        if not result:
            return
        strike, ce_ltp, pe_ltp, spot = result
        for prev_date in [yesterday_str, (now_ist().date() - timedelta(days=3)).isoformat()]:
            closed = check_next_day_open(symbol, prev_date, today_str, ce_ltp, pe_ltp, spot, now_ist().isoformat())
            if closed:
                print(f"[{now_ist()}] {symbol}: OPTION PREMIUM GAP — CE {closed['ce_gap_points']:+.1f}pts "
                      f"({closed['ce_gap_pct']:+.1f}%), PE {closed['pe_gap_points']:+.1f}pts ({closed['pe_gap_pct']:+.1f}%)")
                break
        _option_gap_open_checked_date = today_str
    except Exception as e:
        print(f"[{now_ist()}] {symbol}: next-day option gap check failed (non-fatal) — {e}")


def check_pre_open_signal():
    """
    Runs once daily around 9:14-9:15 AM (just before NIFTY opens):
    fetches GIFT NIFTY's current value via Dhan, compares against
    NIFTY's previous close, logs the implied gap direction — per Saim's
    21 Aug request to track whether pre-market signals predict the
    actual opening move. Requires DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN in
    the environment (not yet baked into the systemd service — this is
    the first live feature needing Dhan credentials on the VPS
    permanently, not just ad-hoc terminal testing). Fails silently
    (non-fatal) if Dhan credentials aren't set, so this doesn't disrupt
    the live Groww-powered trading system.
    """
    global _pre_open_signal_logged_date
    today_str = now_ist().strftime("%Y-%m-%d")
    if _pre_open_signal_logged_date == today_str:
        return
    try:
        from dhan_api import fetch_gift_nifty_ltp
        from pre_open_signal_tracker import log_pre_open_signal

        gift_val = fetch_gift_nifty_ltp()
        if gift_val is None:
            return

        # previous close: use yesterday's last known NIFTY close from
        # daily_store (falls back gracefully if unavailable)
        from daily_store import get_previous_close
        prev_close = get_previous_close("NIFTY")
        if prev_close is None:
            print(f"[{now_ist()}] pre-open signal: no previous close available, skipping")
            return

        event = log_pre_open_signal("NIFTY", today_str, gift_val, prev_close, now_ist().isoformat())
        if event:
            print(f"[{now_ist()}] Pre-open signal logged: GIFT NIFTY={gift_val}, prev_close={prev_close}, "
                  f"implied={event['implied_direction']} ({event['implied_gap_points']:+.1f}pts)")
        _pre_open_signal_logged_date = today_str
    except Exception as e:
        print(f"[{now_ist()}] Pre-open signal check failed (non-fatal, likely missing Dhan credentials) — {e}")


def check_pre_open_signal_resolution(candles_5min_after_open, candles_15min_after_open, open_price):
    """
    Runs once daily around 9:30 AM: checks the actual price move at
    +5min and +15min from open against the pre-open signal logged
    earlier, closing that day's tracking event.
    """
    global _pre_open_signal_checked_date
    today_str = now_ist().strftime("%Y-%m-%d")
    if _pre_open_signal_checked_date == today_str:
        return
    if not candles_5min_after_open or not candles_15min_after_open or open_price is None:
        return
    try:
        from pre_open_signal_tracker import check_actual_open_move
        closed = check_actual_open_move("NIFTY", today_str, candles_5min_after_open, candles_15min_after_open,
                                         open_price, now_ist().isoformat())
        if closed:
            print(f"[{now_ist()}] Pre-open signal RESOLVED — 5min_correct={closed['prediction_correct_5min']}, "
                  f"15min_correct={closed['prediction_correct_15min']}")
        _pre_open_signal_checked_date = today_str
    except Exception as e:
        print(f"[{now_ist()}] Pre-open signal resolution check failed (non-fatal) — {e}")
_session_split_analyzed_today = {}  # symbol -> date already analyzed


def refresh_multi_timeframe_context(symbol):
    """
    Fetches recent 60-min candle history once per day and computes just
    the 1-HOUR trend context — per Saim's 20 Aug simplification: daily
    trend removed entirely (was causing rate-limit issues fetching 30
    days of hourly data on top of all the other frequent calls). Only
    fetches ~5 days of hourly candles now (plenty for a 20-period EMA,
    much lighter than the previous 30-day daily-resample approach).
    """
    today_str = now_ist().strftime("%Y-%m-%d")
    if _mtf_last_refresh_date.get(symbol) == today_str:
        return  # already fetched today
    try:
        from datetime import timedelta
        start_date = (now_ist().date() - timedelta(days=5)).isoformat()
        end_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")
        start_str = f"{start_date} 09:15:00"
        print(f"[{now_ist()}] {symbol}: multi-timeframe fetching candles, start='{start_str}' end='{end_str}' interval=30")
        # FIX (20 Aug 2026): Groww's API rejected interval=60 with "Not
        # able to recognize candle_interval, having value 60minute" —
        # confirmed via live error message that 60-min isn't supported by
        # this endpoint (only 1/5/15/30 are). Switched to 30-min, still
        # gives genuinely useful higher-timeframe trend context.
        hourly_raw = fetch_candles(symbol, start_str, end_str, interval_minutes=30)
        if not hourly_raw:
            print(f"[{now_ist()}] {symbol}: multi-timeframe context — no hourly data returned")
            return

        ctx = get_multi_timeframe_context(hourly_raw)
        _mtf_context[symbol] = ctx
        _mtf_last_refresh_date[symbol] = today_str
        print(f"[{now_ist()}] {symbol}: multi-timeframe context — hourly={ctx['hourly'].get('trend')}")
    except Exception as e:
        print(f"[{now_ist()}] {symbol}: multi-timeframe context fetch failed (non-fatal) — {e}")
_last_signal_state = {}  # symbol -> previous tick's signal, for edge-triggered entry detection
_last_data_sync_time = None  # when memory/data was last auto-pushed to GitHub
_last_poc_signal_state = {}  # symbol -> previous tick's POC-strategy signal, edge-triggered separately
_last_naked_poc_signal_state = {}  # symbol -> previous tick's naked-POC signal, edge-triggered separately
_cached_naked_pocs = {}  # symbol -> list of naked POCs (refreshed once/day at EOD, used for live intraday checks)
_latest_vix = None          # India VIX level, refreshed alongside option chain
_latest_depth_imbalance = {}  # symbol -> order-book depth imbalance dict (real order flow, not OI)


def _build_option_trading_symbol(symbol, strike, expiry_date_str, option_type="CE"):
    """
    Builds Groww's trading_symbol format for options, e.g. "NIFTY2681824300CE"
    for NIFTY, expiry 2026-08-18, strike 24300, CE — confirmed against a
    real growwContractId seen earlier this project. Format:
    SYMBOL + YY + M(single char: 1-9 for Jan-Sep, O/N/D for Oct/Nov/Dec) + DD + STRIKE + CE/PE

    FIX (20 Aug 2026): refresh_order_flow_depth() was building this as a
    "18 AUG"-style day-month-name string, which is NOT Groww's actual
    symbol format — every order-flow-depth fetch was failing because of
    this wrong symbol string, not a real API/data availability issue.
    """
    dt = datetime.strptime(expiry_date_str, "%Y-%m-%d")
    yy = dt.strftime("%y")
    month_char = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9",
                  10: "O", 11: "N", 12: "D"}[dt.month]
    dd = dt.strftime("%d")
    return f"{symbol}{yy}{month_char}{dd}{strike:.0f}{option_type}"


def refresh_order_flow_depth():
    """
    Fetches live market depth (5-level bid/ask order book) for the ATM
    strike of each symbol — real order-flow data (who's punching orders
    right now), distinct from OI (positioning snapshot). Per Saim's 19
    Aug request: detects when OI/PCR sentiment disagrees with what the
    actual order book shows (e.g. OI bullish but heavy sell-side depth
    absorbing buy pressure).

    FIX (20 Aug 2026): was manually GUESSING trading_symbol format across
    multiple attempts (all wrong — Groww's docs show conflicting formats
    in different places). Found the REAL fix: Groww's option-chain
    response (which we already fetch successfully every ~3 min) includes
    the exact correct trading_symbol per contract directly — no guessing
    needed. Uses that confirmed value instead.
    """
    for symbol in SYMBOLS:
        try:
            chain_data = _latest_option_rows.get(symbol)
            if not chain_data:
                continue
            rows, spot = chain_data
            atm_row = min(rows, key=lambda r: abs(r["strike"] - spot))
            if not atm_row.get("call"):
                continue
            # ATTEMPT 4 (20 Aug 2026, per Saim's go-ahead): try the
            # contractId-style NUMERIC-MONTH format instead — confirmed
            # live in a real Groww order-execution response
            # ("NIFTY2522025400CE"), a genuinely different scheme from
            # both the day-month-name guess and the option-chain's own
            # "trading_symbol" field (alpha-month) — both already failed
            # with GA001 "Invalid trading symbol".
            expiry = _EXPIRY_CALCULATORS.get(symbol, get_next_tuesday_expiry)()
            trading_symbol = _build_option_trading_symbol(symbol, atm_row["strike"], expiry, "CE")
            print(f"[{now_ist()}] {symbol}: order-flow-depth ATTEMPT 4 (numeric-month) trading_symbol='{trading_symbol}'")

            # DIAGNOSTIC (20 Aug 2026): also try the SAME symbol via the
            # LTP endpoint (genuinely different request structure —
            # exchange_symbols array with "NSE_" prefix combined into the
            # symbol string) to isolate whether GA001 is specific to the
            # quote/depth endpoint or the symbol itself is being rejected
            # everywhere. Does not block the main flow either way.
            try:
                ltp_result = fetch_ltp([f"NSE_{trading_symbol}"], segment="FNO")
                print(f"[{now_ist()}] {symbol}: LTP DIAGNOSTIC SUCCESS — {ltp_result}")
            except Exception as ltp_e:
                print(f"[{now_ist()}] {symbol}: LTP DIAGNOSTIC also failed — {ltp_e}")

            payload = fetch_quote_depth(trading_symbol, exchange="NSE", segment="FNO")
            time.sleep(0.5)  # stagger — same rate-limit reasoning as option-chain fetch
            imbalance = compute_depth_imbalance(payload)
            _latest_depth_imbalance[symbol] = imbalance

            # Footprint proxy sampling (added 19 Aug 2026, per Saim's
            # buyer/seller-objection discussion) — reuses this SAME quote
            # payload (already has last_price/bid/offer) rather than
            # needing separate WebSocket tick infrastructure. Samples the
            # UNDERLYING index price level (not the option premium) since
            # that's what Saim is actually asking about — using `spot` as
            # the price-level bucket and this option's trade as a proxy
            # tick (best-effort; a true underlying-level footprint would
            # need the underlying's own bid/ask, which indices don't have
            # since they're not directly traded — this samples the ATM
            # option's aggression as the closest available proxy).
            aggression = classify_trade_aggression(payload)
            if aggression:
                record_footprint_sample(symbol, now_ist().strftime("%Y-%m-%d"), spot, aggression,
                                         payload.get("last_trade_quantity"), now_ist().isoformat())

            # Order-size anomaly detection (added 19 Aug 2026, per Saim's
            # "news is lagging, big capital moves first" discussion — a
            # mechanical baseline-vs-spike statistical read, independent
            # of any news explanation)
            if imbalance:
                record_snapshot(symbol, imbalance["visible_buy_qty"], imbalance["visible_sell_qty"], now_ist().isoformat())
                anomaly = check_for_anomaly(symbol, imbalance["visible_buy_qty"], imbalance["visible_sell_qty"],
                                             now_ist().isoformat(), spot)
                if anomaly:
                    print(f"[{now_ist()}] {symbol}: 🚨 ORDER-SIZE ANOMALY — {anomaly['dominant_side']}-side, "
                          f"z-score={anomaly['z_score']} (current={anomaly['current_total_qty']}, "
                          f"baseline_mean={anomaly['baseline_mean']})")

            oi_bias = _latest_live_oi_bias.get(symbol)
            if imbalance and oi_bias:
                absorption = detect_absorption(oi_bias.get("lean"), imbalance)
                if absorption and absorption["absorption_detected"]:
                    print(f"[{now_ist()}] {symbol}: ⚠️ ABSORPTION DETECTED — {absorption['interpretation']} "
                          f"(visible_depth_ratio={absorption['visible_depth_ratio']}, wall={absorption['wall']})")
                    log_absorption_event(symbol, now_ist().strftime("%Y-%m-%d"), absorption, spot, now_ist().isoformat())
                elif imbalance["lean"] != "NEUTRAL":
                    print(f"[{now_ist()}] {symbol}: depth imbalance={imbalance['lean']} "
                          f"(visible_depth_ratio={imbalance['visible_depth_ratio']}), OI={oi_bias.get('lean')} — agree")
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: order-flow depth fetch failed (non-fatal) — {e}")


def refresh_vix():
    """Fetches India VIX (signal-quality context — per Saim's 18 Aug
    request to learn whether signal reliability degrades in high-VIX/
    high-uncertainty conditions). Best-effort — if the symbol/segment
    guess is wrong, fails silently and vix_level stays None elsewhere."""
    global _latest_vix
    try:
        today_str = now_ist().strftime("%Y-%m-%d")
        vix_start = min(dtime(9, 15), now_ist().time())
        candles = fetch_candles("INDIAVIX", f"{today_str} {vix_start.strftime('%H:%M:%S')}",
                                 now_ist().strftime("%Y-%m-%d %H:%M:%S"),
                                 interval_minutes=5)
        if candles:
            _latest_vix = candles[-1]["close"]
            print(f"[{now_ist()}] India VIX refreshed: {_latest_vix}")
    except Exception as e:
        print(f"[{now_ist()}] VIX fetch failed (non-fatal): {e}")


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
        time.sleep(0.5)  # stagger calls (20 Aug 2026: multiple back-to-back Groww
                          # API calls in the same tick were likely triggering 429
                          # rate-limit errors — small delay between each call)
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
        _latest_option_rows[symbol] = (rows, spot)

        # Option VOLUME profile (added 18 Aug 2026, Saim's point: options
        # generate more day-trading volume than futures, so this is a
        # genuinely separate useful signal — distinct from OI, which
        # reads carried/established positioning, Volume reads TODAY's
        # actual live trading activity)
        vol_profile = compute_volume_profile(rows, spot)
        _latest_volume_profile[symbol] = vol_profile
        vol_summary = (f"PCR-Vol={vol_profile['pcr_volume']}, most active CE={vol_profile['most_active_call_strike']}, "
                        f"most active PE={vol_profile['most_active_put_strike']}") if vol_profile else "n/a"

        print(f"[{now_ist()}] {symbol}: live option chain refreshed (expiry={expiry}) — "
              f"OI lean={lean} PCR={pcr}, GEX regime={gex.get('regime') if gex else 'n/a'}, {vol_summary}")


def is_market_hours(now=None):
    now = now or now_ist()
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def run_once():
    global _option_chain_loop_counter, _last_data_sync_time
    today = now_ist().strftime("%Y-%m-%d")
    alerted = _load_alerted()

    now_t = now_ist().time()

    # Auto-sync accumulated data to GitHub every 15 min (added 21 Aug
    # 2026, per Saim's explicit request — so Claude can `git pull` and
    # directly inspect real, current data without Saim ever needing to
    # copy-paste large outputs back into a chat session again)
    if _last_data_sync_time is None or (now_ist() - _last_data_sync_time).total_seconds() >= 900:
        try:
            from auto_sync_data import sync_data_to_github
            sync_result = sync_data_to_github()
            if sync_result.get("status") == "synced":
                print(f"[{now_ist()}] Data auto-synced to GitHub")
            _last_data_sync_time = now_ist()
        except Exception as e:
            print(f"[{now_ist()}] Data auto-sync failed (non-fatal) — {e}")

    # Refresh live option chain (OI/PCR + Gamma Exposure) and VIX every N loops
    if _option_chain_loop_counter % OPTION_CHAIN_REFRESH_LOOPS == 0:
        refresh_live_option_chain()
        refresh_vix()
        # RE-ENABLED (20 Aug 2026): fixed by using the trading_symbol
        # already present in the option-chain response instead of
        # RE-ENABLED (20 Aug 2026), trying ATTEMPT 4 — numeric-month
        # contractId-style format, confirmed against a real Groww order
        # response ("NIFTY2522025400CE"). Both previous formats (guessed
        # day-month-name, and option-chain's own "trading_symbol" field
        # with alpha-month) failed with GA001. This is genuinely
        # different — testing per Saim's go-ahead.
        # RE-DISABLED (20 Aug 2026): 4 different symbol formats tried
        # (day-month-name guess, option-chain's own alpha-month
        # trading_symbol, numeric-month matching Groww's own docs
        # example) — ALL rejected with identical GA001 across BOTH
        # /v1/live-data/quote AND /v1/live-data/ltp endpoints (confirmed
        # via diagnostic isolation test). This proves it's not an
        # endpoint-specific issue and not a format-guessing issue — the
        # symbol itself is being rejected consistently. Needs direct
        # Groww support contact with concrete failing examples, not more
        # guessing. Core system (candles, option chain, VSA, multi-
        # timeframe, paper trading) confirmed healthy and unaffected.
        # refresh_order_flow_depth()
    _option_chain_loop_counter += 1

    # Pre-open / EOD option-premium-gap checks (added 21 Aug 2026, moved
    # here to run AFTER refresh_live_option_chain() so they always use
    # fresh same-cycle option-chain data, not a stale/empty prior cycle)
    if dtime(9, 0) <= now_t <= dtime(9, 20):
        check_pre_open_signal()
        check_next_day_option_gap("NIFTY")

    if dtime(15, 25) <= now_t <= dtime(15, 32):
        check_eod_option_snapshot("NIFTY")

    for symbol in SYMBOLS:
        try:
            fetch_start = min(dtime(9, 15), now_ist().time())
            candles = fetch_candles(symbol, f"{today} {fetch_start.strftime('%H:%M:%S')}",
                                     now_ist().strftime("%Y-%m-%d %H:%M:%S"),
                                     interval_minutes=1)
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: fetch failed — {e}")
            continue

        if not candles:
            print(f"[{now_ist()}] {symbol}: no candles yet")
            continue

        append_intraday_candles(symbol, candles, interval_label="1min")
        time.sleep(0.5)  # stagger before the next call for this symbol (rate-limit mitigation)

        # Pre-open signal resolution check (added 21 Aug 2026): once enough
        # post-open candles exist for NIFTY specifically, check whether
        # GIFT NIFTY's implied direction matched the actual move
        if symbol == "NIFTY" and len(candles) >= 16 and now_ist().time() >= dtime(9, 30):
            open_price = candles[0]["close"] if candles[0]["timestamp"][11:16] == "09:15" else None
            price_5min = next((c["close"] for c in candles if c["timestamp"][11:16] == "09:20"), None)
            price_15min = next((c["close"] for c in candles if c["timestamp"][11:16] == "09:30"), None)
            if open_price and price_5min and price_15min:
                check_pre_open_signal_resolution(price_5min, price_15min, open_price)

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        # Prefer live option-chain OI (refreshed every ~5 min) over the old
        # manual CSV snapshot — falls back to the manual snapshot only if
        # live fetch hasn't succeeded yet this run
        oi_bias = _latest_live_oi_bias.get(symbol) or latest_oi_bias(symbol)

        # VSA/volume layer (fixed 18 Aug 2026): index candles never have
        # volume (NIFTY/BANKNIFTY aren't directly traded, only their
        # futures/options are) — confirmed live via GrowwMCP (volume: null
        # on every candle). Fetch FUTURES candles in parallel (which DO
        # have real volume) and use those for VSA instead of the index.
        #
        # BUG FIX (19 Aug 2026): was using _EXPIRY_CALCULATORS[symbol]
        # (weekly Tuesday for NIFTY) for the FUTURES contract — but NIFTY
        # index futures only exist as MONTHLY contracts (near/mid/far
        # month), there is no such thing as a weekly futures contract
        # (only OPTIONS have weekly expiry). Using a weekly date here
        # would silently fail on any week where that Tuesday isn't also
        # the monthly expiry, since no such futures contract exists.
        # Futures must always use the MONTHLY expiry regardless of symbol.
        try:
            futures_expiry_raw = get_monthly_expiry()
            futures_expiry_fmt = datetime.strptime(futures_expiry_raw, "%Y-%m-%d").strftime("%d%b%y")
            fut_start = min(dtime(9, 15), now_ist().time())
            futures_candles = fetch_candles(symbol, f"{today} {fut_start.strftime('%H:%M:%S')}",
                                             now_ist().strftime("%Y-%m-%d %H:%M:%S"),
                                             segment="FNO", interval_minutes=1, expiry=futures_expiry_fmt)
            vsa_bias = momentum_bias(futures_candles) if futures_candles else momentum_bias(candles)
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: futures fetch for VSA failed, falling back to index (no volume) — {e}")
            vsa_bias = momentum_bias(candles)

        s_bias = get_smc_bias(candles)

        # LTF Volume Microburst detection (added 21 Aug 2026) — checks
        # only the LATEST futures candle against recent baseline, since
        # this runs every loop tick already (no extra API calls, reuses
        # futures_candles fetched above for VSA)
        try:
            from ltf_microburst import scan_for_microbursts
            if futures_candles and len(futures_candles) >= 25:
                recent_events = scan_for_microbursts(futures_candles[-25:], ema_period=20)
                # only report if the VERY LAST candle is a fresh microburst
                if recent_events and recent_events[-1]["index"] == len(futures_candles[-25:]) - 1:
                    ev = recent_events[-1]
                    print(f"[{now_ist()}] {symbol}: LTF MICROBURST — {ev['direction']}, "
                          f"volume={ev['volume_ratio']}x baseline, directional_efficiency={ev['directional_efficiency']}")
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: LTF microburst check failed (non-fatal) — {e}")

        # Multi-timeframe context refresh — RE-ENABLED with diagnostic
        # logging (20 Aug 2026) to capture the exact params + error
        # message and finally diagnose the persistent HTTP 400.
        refresh_multi_timeframe_context(symbol)
        try:
            fvgs = find_recent_fvgs(candles, lookback_bars=100)  # wider lookback for full-day FVG history
            touch_event = check_fvg_touch(symbol, today, candles, fvgs, vsa_bias, now_ist().isoformat())
            if touch_event:
                print(f"[{now_ist()}] {symbol}: FVG TOUCHED — {touch_event['fvg_type']} gap "
                      f"[{touch_event['gap_low']:.1f}-{touch_event['gap_high']:.1f}], VSA={touch_event['vsa_at_touch']}")
            fvg_closed = check_touch_resolution(symbol, closes[-1], now_ist().isoformat(),
                                                 is_eod=(now_ist().time() >= MARKET_CLOSE))
            for fc in fvg_closed:
                print(f"[{now_ist()}] {symbol}: FVG TOUCH RESOLVED — {fc['outcome']}, {fc['move_points']:+.1f}pts")
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: FVG touch tracking failed (non-fatal) — {e}")

        # Session-split analysis (once/day, after market close)
        if now_ist().time() >= MARKET_CLOSE and _session_split_analyzed_today.get(symbol) != today:
            try:
                split = analyze_session_split(symbol, today, candles)
                if split:
                    print(f"[{now_ist()}] {symbol}: SESSION SPLIT — regular_range={split['regular_range']}, "
                          f"extended_range={split['extended_range']} ({split['extended_share_of_total_range_pct']}% of total)")
            except Exception as e:
                print(f"[{now_ist()}] {symbol}: session split analysis failed (non-fatal) — {e}")
            _session_split_analyzed_today[symbol] = today

            # Opening-impact analysis (added 21 Aug 2026, per Saim's
            # hypothesis: pre-market position adjustments release all at
            # once at 9:15 open, producing the day's single biggest move
            # in the first few minutes — tests this using price data
            # alone, the order-flow-depth-based "why" comes later once
            # that's unblocked)
            try:
                from opening_impact_tracker import analyze_opening_impact
                opening_event = analyze_opening_impact(symbol, today, candles)
                if opening_event:
                    print(f"[{now_ist()}] {symbol}: OPENING IMPACT — opening_range={opening_event['opening_range']}, "
                          f"biggest_elsewhere={opening_event['max_other_5min_range']} at {opening_event['max_other_window_time']}, "
                          f"opening_was_biggest={opening_event['is_opening_the_biggest']}")
            except Exception as e:
                print(f"[{now_ist()}] {symbol}: opening impact analysis failed (non-fatal) — {e}")

            # Volume Profile / POC — daily + rolling contract-period
            # (added 21 Aug 2026, per Saim's design decision: track both
            # levels, using FUTURES candles (real volume, already
            # confirmed working) — fetches the full day's futures data
            # once at EOD, no extra per-minute API calls)
            try:
                from volume_profile_tracker import compute_and_store_daily_poc, update_rolling_contract_poc
                futures_expiry_raw = get_monthly_expiry()
                futures_expiry_fmt = datetime.strptime(futures_expiry_raw, "%Y-%m-%d").strftime("%d%b%y")
                day_futures = fetch_candles(symbol, f"{today} 09:15:00",
                                             now_ist().strftime("%Y-%m-%d %H:%M:%S"),
                                             segment="FNO", interval_minutes=1, expiry=futures_expiry_fmt)
                if day_futures:
                    daily_poc = compute_and_store_daily_poc(symbol, today, day_futures)
                    rolling_poc = update_rolling_contract_poc(symbol, today, day_futures, futures_expiry_raw)
                    if daily_poc:
                        print(f"[{now_ist()}] {symbol}: DAILY POC — {daily_poc['poc_price']} "
                              f"(VA: {daily_poc['value_area_low']}-{daily_poc['value_area_high']})")
                    if rolling_poc:
                        print(f"[{now_ist()}] {symbol}: ROLLING CONTRACT POC ({rolling_poc['days_accumulated']} days) — "
                              f"{rolling_poc['poc_price']} (VA: {rolling_poc['value_area_low']}-{rolling_poc['value_area_high']})")

                    # Naked POC tracking (added 21 Aug 2026, per Saim's
                    # research-then-implement instruction) — checks which
                    # prior daily POCs remain unretested (potential
                    # "magnet" levels per Market Profile theory)
                    try:
                        from naked_poc_tracker import get_naked_pocs, log_day_range, load_day_ranges
                        day_high = max(c["close"] for c in day_futures)
                        day_low = min(c["close"] for c in day_futures)
                        log_day_range(symbol, today, day_high, day_low)
                        day_ranges = load_day_ranges(symbol)
                        naked_pocs = get_naked_pocs(symbol, today, day_ranges)
                        _cached_naked_pocs[symbol] = naked_pocs  # cache for live intraday checks
                        if naked_pocs:
                            top3 = naked_pocs[:3]
                            print(f"[{now_ist()}] {symbol}: NAKED POCs (top 3 by age) — " +
                                  ", ".join(f"{n['poc_price']}({n['sessions_unvisited']}d)" for n in top3))
                    except Exception as naked_e:
                        print(f"[{now_ist()}] {symbol}: naked POC tracking failed (non-fatal) — {naked_e}")
            except Exception as e:
                print(f"[{now_ist()}] {symbol}: volume profile POC calculation failed (non-fatal) — {e}")

            # Footprint compress-and-cleanup (per Saim's 19 Aug agreement:
            # keep the compressed per-price-level summary PERMANENTLY —
            # it's what explains WHY a level is support/resistance — but
            # clean up the raw minute-by-minute samples daily, since
            # they're not needed once compressed)
            try:
                from footprint_proxy import compress_and_cleanup_day
                compress_and_cleanup_day(symbol, today)
            except Exception as e:
                print(f"[{now_ist()}] {symbol}: footprint compress/cleanup failed (non-fatal) — {e}")

        # FIX (19 Aug 2026, Saim caught this): greeks_bias and fii_bias
        # were NEVER passed to score_setup() here — engine.py correctly
        # reported "NOT YET INTEGRATED" for both even though live Gamma/
        # OI data and (if provided) manual FII data actually exist.
        # Convert the already-fetched live option-chain rows into the
        # flat {strikePrice, optionType, delta, iv, ...} shape
        # greeks_bias.compute_greeks_bias() expects, and wire in FII/DII.
        # FIX (19 Aug 2026): wrapped in try/except — this was unguarded
        # and could crash the whole loop for a symbol if option-chain
        # data was malformed/stale, silently halting signal generation.
        greeks_bias_val = None
        try:
            chain_data_for_greeks = _latest_option_rows.get(symbol)
            if chain_data_for_greeks:
                rows, spot = chain_data_for_greeks
                flat_contracts = []
                for r in rows:
                    for side, opt_type in (("call", "CE"), ("put", "PE")):
                        if r.get(side):
                            flat_contracts.append({
                                "strikePrice": r["strike"], "optionType": opt_type,
                                "delta": r[side].get("delta"), "iv": r[side].get("iv"),
                                "theta": r[side].get("theta"), "gamma": r[side].get("gamma"),
                            })
                greeks_bias_val = compute_greeks_bias(flat_contracts, spot)
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: greeks_bias computation failed (non-fatal) — {e}")

        try:
            fii_bias_val = get_latest_manual_fii_bias()
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: fii_bias fetch failed (non-fatal) — {e}")
            fii_bias_val = None

        result = score_setup(closes, highs, lows, oi_bias=oi_bias, vsa_bias=vsa_bias, smc_bias=s_bias,
                              greeks_bias=greeks_bias_val, fii_bias=fii_bias_val, candles_for_trend=candles)
        log_signal(symbol, result, note=f"VPS continuous run, {today}")

        # Divergence hypothesis-tracking (added 18 Aug 2026, Saim's explicit
        # request): when live OI lean disagrees with the short-term price
        # trend, log it and watch whether price eventually moves in OI's
        # direction — pure observation, does NOT feed into scoring.
        if oi_bias and len(closes) >= 6:
            recent_direction = "UP" if closes[-1] > closes[-6] else "DOWN"
            now_iso = now_ist().isoformat()
            gex_ctx = _latest_live_gex.get(symbol)
            expiry_str = _EXPIRY_CALCULATORS.get(symbol, get_next_tuesday_expiry)()
            days_to_exp = (datetime.strptime(expiry_str, "%Y-%m-%d").date() - now_ist().date()).days
            detect_and_log_divergence(symbol, today, oi_bias.get("lean"), recent_direction, closes[-1], now_iso,
                                       gex_context=gex_ctx, days_to_expiry=days_to_exp)
            div_closed = check_divergence_resolution(symbol, today, closes[-1], now_iso,
                                                       is_eod=(now_ist().time() >= MARKET_CLOSE))
            for d in div_closed:
                print(f"[{now_ist()}] {symbol}: DIVERGENCE EVENT CLOSED — resolved={d['resolved']}, "
                      f"{d['resolution_minutes']}min, {d['resolution_move_points']:+.1f}pts")

            absorp_closed = check_absorption_resolution(symbol, today, closes[-1], now_iso,
                                                          is_eod=(now_ist().time() >= MARKET_CLOSE))
            for a in absorp_closed:
                print(f"[{now_ist()}] {symbol}: ABSORPTION EVENT CLOSED — {a['resolved_direction']}, "
                      f"{a['resolution_minutes']}min, {a['resolution_move_points']:+.1f}pts")

        # Self-generated paper trading (added 17 Aug 2026, Saim's request for
        # faster learning): check/close any open paper trade against latest
        # candle every tick, and open a NEW one whenever a fresh signal fires
        # — independent of whether a Telegram alert was sent (dedup only
        # controls Telegram noise, not the learning data).
        closed = check_open_trades(symbol, candles, is_eod=(now_ist().time() >= MARKET_CLOSE))
        for c in closed:
            print(f"[{now_ist()}] {symbol}: PAPER TRADE CLOSED — {c['outcome']} {c['outcome_points']:+.1f} pts ({c['exit_reason']})")

        # Expiry-close "gamma blast" tracker (added 18 Aug 2026, Saim's
        # explanation of the pinning-release pattern in the final minutes
        # before close): capture an option-chain snapshot at the start of
        # the pre-close window (~15:15), then once market has closed,
        # compare it against the latest snapshot and the day's price
        # candles to measure whether the last-15-min move was genuinely
        # faster than the day's average (see expiry_close_tracker.py).
        now_t = now_ist().time()
        if now_t >= PRE_CLOSE_WINDOW_START and symbol not in _close_window_start_snapshot:
            chain_data = _latest_option_rows.get(symbol)
            if chain_data:
                _close_window_start_snapshot[symbol] = chain_data[0]  # rows only
                print(f"[{now_ist()}] {symbol}: captured pre-close-window option snapshot for gamma-blast tracking")

        if now_t >= MARKET_CLOSE and _close_window_analyzed_today.get(symbol) != today:
            chain_data = _latest_option_rows.get(symbol)
            start_rows = _close_window_start_snapshot.get(symbol)
            end_rows = chain_data[0] if chain_data else None

            # Determine expiry_type: does EVERY symbol we track expire today,
            # or just this one? (25 Aug 2026 is the first day NIFTY-weekly
            # and BANKNIFTY-monthly coincide — per Saim's 18 Aug warning,
            # this MUST be tagged distinctly so it doesn't corrupt the
            # weekly-only baseline)
            todays_expiries = {s: _EXPIRY_CALCULATORS.get(s, get_next_tuesday_expiry)() for s in SYMBOLS}
            symbols_expiring_today = [s for s, exp in todays_expiries.items() if exp == today]
            expiry_type = "weekly_and_monthly_combined" if len(symbols_expiring_today) > 1 else "weekly_only"

            event = analyze_close_window(symbol, today, candles, option_rows_at_start=start_rows,
                                          option_rows_at_close=end_rows, expiry_type=expiry_type)
            if event:
                print(f"[{now_ist()}] {symbol}: EXPIRY-CLOSE analysis ({expiry_type}) — "
                      f"acceleration_ratio={event['acceleration_ratio']}, biggest_strike_move={event['biggest_strike_move']}")
            _close_window_analyzed_today[symbol] = today

        # Edge-triggered entry (fixed 19 Aug 2026, replacing a blunt time-
        # cooldown after Saim's sharp pushback: "a fixed cooldown isn't
        # learning anything, it's just a rule I imposed"). The real bug
        # was that the signal check is LEVEL-triggered (fires every tick
        # the condition remains true) instead of EDGE-triggered (should
        # only fire once, when the condition freshly becomes true) — this
        # is what caused 51 trades/day (a borderline-true condition kept
        # re-opening trades every tick after each SL hit). Now only opens
        # a NEW paper trade when the signal actually TRANSITIONS into
        # LONG/SHORT from something else (NONE, or the opposite side) —
        # a continuously-true signal from the previous tick does not
        # re-trigger a new entry.
        prev_signal = _last_signal_state.get(symbol, "NONE")
        is_fresh_signal = result["signal"] != "NONE" and result["signal"] != prev_signal
        _last_signal_state[symbol] = result["signal"]

        # POC-Reaction strategy check (added 21 Aug 2026) — THIRD,
        # independent entry strategy alongside RSI-Reversal and
        # Trend-Continuation. Uses the rolling contract-period POC
        # (clearer multi-day support/resistance signal per 12-17 Aug
        # verification). Edge-triggered from the start (built correctly
        # this time, avoiding the level-triggered bug found 20 Aug).
        try:
            from poc_reaction_strategy import check_poc_reaction_signal_v2, classify_bounce_conviction, determine_trade_mode
            from volume_profile_tracker import get_current_rolling_poc
            from volume_profile import compute_volume_profile, classify_balance_imbalance
            from initial_balance import compute_initial_balance, detect_ib_breakout

            rolling_poc = get_current_rolling_poc(symbol)
            if rolling_poc and len(closes) >= 6:
                # Determine trade mode (RESPONSIVE vs INITIATIVE) — the
                # missing piece Saim identified 21 Aug, per Market Profile
                # theory (verified via research + 16 test scenarios before
                # wiring live): a genuine breakout should be traded WITH,
                # not faded like a normal bounce.
                trade_mode = "RESPONSIVE"  # safe default
                try:
                    day_profile = compute_volume_profile(futures_candles) if futures_candles else None
                    day_classification = None
                    if day_profile and futures_candles:
                        day_high = max(c["close"] for c in futures_candles)
                        day_low = min(c["close"] for c in futures_candles)
                        day_classification = classify_balance_imbalance(day_profile, day_high, day_low)

                    ib_result = None
                    if futures_candles:
                        ib = compute_initial_balance(futures_candles)
                        if ib:
                            baseline_vol = sum(c.get("volume", 0) for c in futures_candles[-20:]) / min(20, len(futures_candles))
                            ib_result = detect_ib_breakout(closes[-1], futures_candles[-1].get("volume", 0),
                                                            ib["ib_high"], ib["ib_low"], baseline_vol)

                    trade_mode = determine_trade_mode(day_classification, ib_result)
                except Exception as mode_e:
                    print(f"[{now_ist()}] {symbol}: trade-mode determination failed, defaulting RESPONSIVE — {mode_e}")

                recent_candles = [{"close": c} for c in closes[-6:]]
                poc_result = check_poc_reaction_signal_v2(closes[-1], recent_candles, rolling_poc["poc_price"], trade_mode)
                poc_signal = poc_result["signal"]

                prev_poc_signal = _last_poc_signal_state.get(symbol, "NONE")
                is_fresh_poc_signal = poc_signal != "NONE" and poc_signal != prev_poc_signal
                _last_poc_signal_state[symbol] = poc_signal

                if is_fresh_poc_signal:
                    print(f"[{now_ist()}] {symbol}: TRADE MODE = {trade_mode}")
                    # Bounce-conviction classification (per Saim's "kyun
                    # bounce hua" question — active buying/selling vs
                    # passive absence, using volume magnitude as a
                    # partial proxy since full order-flow is still blocked).
                    # Uses futures_candles (real volume, already fetched
                    # for VSA earlier this loop iteration) — NOT the main
                    # index `candles`, which never has volume.
                    conviction = "UNKNOWN"
                    try:
                        if 'futures_candles' in dir() and futures_candles and len(futures_candles) >= 20:
                            recent_vol_candles = futures_candles[-3:]
                            baseline = sum(c.get("volume", 0) for c in futures_candles[-20:]) / 20
                            conviction = classify_bounce_conviction(recent_vol_candles, baseline)
                    except Exception:
                        pass

                    print(f"[{now_ist()}] {symbol}: POC SIGNAL — {poc_signal}: {poc_result['reason']}, "
                          f"SL={poc_result['sl_price']}, conviction={conviction}")
                    poc_sl_points = abs(closes[-1] - poc_result["sl_price"])
                    poc_trade = open_paper_trade(symbol, today, poc_signal, closes[-1],
                                                  poc_sl_points, poc_sl_points * 2,
                                                  {"poc_reference": poc_result["poc_reference"]}, 0,
                                                  [poc_result["reason"]], strategy_type=f"poc_reaction_{trade_mode.lower()}")
                    if poc_trade:
                        print(f"[{now_ist()}] {symbol}: POC PAPER TRADE OPENED — entry={closes[-1]}, SL={poc_result['sl_price']}")
                        # Send Telegram alert (was previously missing —
                        # POC trades opened silently with no alert at all)
                        try:
                            poc_msg = (
                                f"<b>Order-Flow Agent Signal</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Strategy: <b>poc_reaction ({trade_mode})</b>\n"
                                f"Signal: <b>{poc_signal}</b>\n"
                                f"POC Reference: {poc_result['poc_reference']}\n"
                                f"Reason: {poc_result['reason']}\n"
                                f"Bounce Conviction: <b>{conviction}</b> (volume-magnitude proxy — "
                                f"NOT true buyer/seller aggression, that needs order-flow-depth still blocked)\n"
                                f"SL: {poc_result['sl_price']} (fail-safe — just beyond POC)\n\n"
                                f"⚠️ Alert-only. Manual confirmation required before entry."
                            )
                            send_telegram_message(poc_msg)
                        except Exception as alert_e:
                            print(f"[{now_ist()}] {symbol}: POC alert send failed (non-fatal) — {alert_e}")
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: POC reaction strategy check failed (non-fatal) — {e}")

        # Naked POC live trading-signal check (added 21 Aug 2026, per
        # Saim's "go ahead and implement it" — reuses the cached naked-
        # POC list computed at EOD, checks it every tick like the
        # rolling-POC reaction check above. All 3 use-cases from
        # research: entry-zone (bounce/breakdown reaction, mode-aware)
        # + target-suggestion (further naked POCs in trade direction).
        try:
            from naked_poc_tracker import check_naked_poc_signal
            cached_naked_pocs = _cached_naked_pocs.get(symbol, [])
            if cached_naked_pocs and len(closes) >= 6:
                recent_candles = [{"close": c} for c in closes[-6:]]
                # reuse the same trade_mode computed above for POC-reaction
                naked_result = check_naked_poc_signal(closes[-1], recent_candles, cached_naked_pocs,
                                                        trade_mode=trade_mode if 'trade_mode' in dir() else "RESPONSIVE")
                naked_signal = naked_result["signal"]

                prev_naked_signal = _last_naked_poc_signal_state.get(symbol, "NONE")
                is_fresh_naked_signal = naked_signal != "NONE" and naked_signal != prev_naked_signal
                _last_naked_poc_signal_state[symbol] = naked_signal

                if is_fresh_naked_signal:
                    print(f"[{now_ist()}] {symbol}: NAKED POC SIGNAL — {naked_signal}: {naked_result['reason']}, "
                          f"targets={naked_result.get('suggested_targets', [])}")
                    naked_sl_points = abs(closes[-1] - naked_result["sl_price"])
                    naked_trade = open_paper_trade(symbol, today, naked_signal, closes[-1],
                                                     naked_sl_points, naked_sl_points * 2,
                                                     {"naked_poc_reference": naked_result["naked_poc_used"],
                                                      "suggested_targets": naked_result.get("suggested_targets", [])},
                                                     0, [naked_result["reason"]], strategy_type="naked_poc")
                    if naked_trade:
                        print(f"[{now_ist()}] {symbol}: NAKED-POC PAPER TRADE OPENED — entry={closes[-1]}, "
                              f"SL={naked_result['sl_price']}")
                        try:
                            naked_msg = (
                                f"<b>Order-Flow Agent Signal</b>\n"
                                f"Symbol: {symbol}\n"
                                f"Strategy: <b>naked_poc</b>\n"
                                f"Signal: <b>{naked_signal}</b>\n"
                                f"Naked POC: {naked_result['naked_poc_used']}\n"
                                f"Reason: {naked_result['reason']}\n"
                                f"Suggested Targets (further naked POCs): {naked_result.get('suggested_targets', [])}\n"
                                f"SL: {naked_result['sl_price']}\n\n"
                                f"⚠️ Alert-only. Manual confirmation required before entry."
                            )
                            send_telegram_message(naked_msg)
                        except Exception as naked_alert_e:
                            print(f"[{now_ist()}] {symbol}: Naked-POC alert send failed (non-fatal) — {naked_alert_e}")
        except Exception as e:
            print(f"[{now_ist()}] {symbol}: Naked POC signal check failed (non-fatal) — {e}")

        if is_fresh_signal:
            print(f"[{now_ist()}] {symbol}: FRESH SIGNAL detected — {result['signal']}, attempting to open paper trade...")
            try:
                # Tag which entry logic actually fired (reversal vs trend-continuation)
                # — per Saim's 18 Aug request to learn which wins more, and where/when
                strategy_type = "trend_continuation" if any("TREND-CONTINUATION" in r for r in result["reasons"]) else "reversal"

                # Capture an option snapshot at entry (for real premium P&L tracking)
                option_snapshot = None
                chain_data = _latest_option_rows.get(symbol)
                if chain_data:
                    rows, spot = chain_data
                    sugg = suggest_strike(rows, spot, result["signal"])
                    if sugg:
                        option_snapshot = {
                            "strike": sugg["strike"], "option_type": sugg["option_type"],
                            "delta": sugg["delta"], "ltp": sugg["ltp"], "theta": sugg.get("theta"),
                        }

                # Time-adaptive SL/target (added 21 Aug 2026, per Saim's
                # verified observation: morning ~1.6x more volatile than
                # midday — a fixed 15/25 SL/target mismatches this,
                # causing midday trades to drift without hitting either
                # level cleanly)
                from time_adaptive_risk import get_time_adjusted_sl_target
                adjusted = get_time_adjusted_sl_target(
                    result.get("sl_points", 15), result.get("target_points", 25), now_ist().time())
                print(f"[{symbol}] Time-adjusted risk ({adjusted['time_window']}, {adjusted['multiplier_used']}x): "
                      f"SL={adjusted['sl_points']}, Target={adjusted['target_points']}")

                pt_result = open_paper_trade(symbol, today, result["signal"], closes[-1],
                                              adjusted["sl_points"], adjusted["target_points"],
                                              result.get("layer_status", {}), result["score"], result["reasons"],
                                              strategy_type=strategy_type, option_snapshot=option_snapshot, vix_level=_latest_vix)
                if pt_result is None:
                    print(f"[{now_ist()}] {symbol}: open_paper_trade() returned None — likely blocked "
                          f"(already an OPEN trade for {symbol}/{today} in paper_trades.jsonl)")
                else:
                    print(f"[{now_ist()}] {symbol}: PAPER TRADE OPENED — entry={closes[-1]}, strategy={strategy_type}")
            except Exception as e:
                import traceback
                print(f"[{now_ist()}] {symbol}: PAPER TRADE OPEN FAILED — {e}")
                print(traceback.format_exc())

        if result["signal"] == "NONE":
            print(f"[{now_ist()}] {symbol}: no signal ({len(candles)} candles)")
            continue

        # FIX (20 Aug 2026): alert-dedup was keyed on symbol+date+signal+SCORE
        # — meaning every minor score fluctuation (e.g. 4->5->4) during a
        # SUSTAINED signal sent a NEW Telegram alert, even though
        # paper-trading correctly recognized it as the same trade
        # (direction-only check). This is exactly why Saim saw many
        # Telegram alerts but only 2-3 paper trades — the two systems
        # were using different definitions of "new signal". Now aligned:
        # alerts also key on direction only (is_fresh_signal), matching
        # paper-trading's edge-triggered logic — one alert per genuine
        # signal transition, not per score wobble.
        if not is_fresh_signal:
            print(f"[{now_ist()}] {symbol}: signal continues from previous tick (score may have changed), not re-alerting")
            continue

        key = _alert_key(symbol, today, result["signal"], result["score"])
        if key in alerted:
            print(f"[{now_ist()}] {symbol}: signal already alerted today, skipping")
            continue

        # Explicit strategy tagging (added 21 Aug 2026, per Saim's
        # request: alerts were ambiguous about which strategy fired —
        # now derived and passed explicitly rather than left implicit
        # in the reasons text.
        alert_strategy_type = "trend_continuation" if any("TREND-CONTINUATION" in r for r in result["reasons"]) else "reversal"
        msg = format_signal_alert(symbol, result, strategy_type=alert_strategy_type) + f"\n\nData date: {today} (live, VPS)"

        # Strike suggestion (added 18 Aug 2026, Saim's request): tell him
        # WHICH strike to actually look at, its current premium, Delta,
        # and a rough estimate of how much that premium would move if the
        # index reaches its SL/target distance — using the cached live
        # option chain (refreshed every ~5 min in refresh_live_option_chain()).
        chain_data = _latest_option_rows.get(symbol)
        if chain_data:
            rows, spot = chain_data
            strike_sugg = suggest_strike(rows, spot, result["signal"])
            if strike_sugg:
                sl_pts = result.get("sl_points", 15)
                move_at_sl = estimate_premium_move(strike_sugg, sl_pts)
                msg += (f"\n\n<b>Suggested strike:</b> {strike_sugg['strike']:.0f} {strike_sugg['option_type']}\n"
                        f"LTP: {strike_sugg['ltp']} | Delta: {strike_sugg['delta']} | IV: {strike_sugg['iv']}\n"
                        f"Est. premium move for {sl_pts}pt index move: ~{move_at_sl} "
                        f"(Delta+Gamma estimate; excludes Theta time-decay)")
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
