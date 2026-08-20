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
from groww_api import fetch_quote_depth
from order_size_anomaly import record_snapshot, check_for_anomaly
from multi_timeframe_context import get_multi_timeframe_context
from fvg_touch_tracker import check_fvg_touch, check_touch_resolution
from session_behavior_tracker import analyze_session_split
from smc import find_recent_fvgs
from footprint_proxy import classify_trade_aggression, record_footprint_sample, get_footprint_summary, check_trend_footprint_shift

LOOP_INTERVAL_SECONDS = 60  # 1-minute granularity
MARKET_OPEN = dtime(9, 12)
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
        hourly_raw = fetch_candles(symbol, f"{start_date} 09:15:00",
                                    now_ist().strftime("%Y-%m-%d %H:%M:%S"), interval_minutes=60)
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
            expiry = _EXPIRY_CALCULATORS.get(symbol, get_next_tuesday_expiry)()
            trading_symbol = _build_option_trading_symbol(symbol, atm_row["strike"], expiry, "CE")

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
    global _option_chain_loop_counter
    today = now_ist().strftime("%Y-%m-%d")
    alerted = _load_alerted()

    # Refresh live option chain (OI/PCR + Gamma Exposure) and VIX every N loops
    if _option_chain_loop_counter % OPTION_CHAIN_REFRESH_LOOPS == 0:
        refresh_live_option_chain()
        refresh_vix()
        # TEMPORARILY DISABLED (20 Aug 2026): trading_symbol construction
        # for options keeps getting Groww's exact format wrong (found TWO
        # different symbol schemes in Groww's own docs — growwContractId
        # uses numeric month/day encoding, but the Instruments API's
        # trading_symbol uses alphabetic month names and appears to omit
        # the day-of-month for monthly contracts) — guessing further risks
        # more silent failures and log noise. Needs a proper fix using
        # Groww's actual instruments-lookup API instead of manual string
        # construction. Re-enable once that's built.
        # refresh_order_flow_depth()
    _option_chain_loop_counter += 1

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

        # Multi-timeframe context refresh (once/day) + FVG-touch tracking
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

                pt_result = open_paper_trade(symbol, today, result["signal"], closes[-1],
                                              result.get("sl_points", 15), result.get("target_points", 25),
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

        key = _alert_key(symbol, today, result["signal"], result["score"])
        if key in alerted:
            print(f"[{now_ist()}] {symbol}: signal already alerted today, skipping")
            continue

        msg = format_signal_alert(symbol, result) + f"\n\nData date: {today} (live, VPS)"

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
