"""
gamma_opening_strategy.py — Box 20: 6th entry strategy
------------------------------------------------------------------------------
22 Aug 2026, built after extensive cross-validated research this session
(8 instruments × 43 days each, ALL showing the identical structural
pattern: morning-dominant, 09:15's first minute captures roughly 2/3 of
the entire 5-minute opening window's total movement, then decays fast).

THE STRATEGY: at market open, combine (1) the ALREADY-VERIFIED "first
minute dominates" timing pattern with (2) our EXISTING live GEX regime
detection (ACCELERATION = negative GEX, dealer hedging amplifies moves;
PINNING = positive GEX, dealer hedging dampens moves) to decide whether
today's open is a genuine gamma-explosion candidate, then enter a trade
in the FIRST MINUTE capturing the direction the market is already
showing, sized against the VERIFIED historical expected-move for that
specific instrument (not a guessed fixed target — per Saim's earlier
explicit rejection of fixed targets).

Per-instrument expected first-minute move (avg pts, from 43-day real
data, 22 Aug research) — used as the TARGET reference, not the SL
(Saim's principle: target should reflect what typically happens, not
an arbitrary number):
"""

# Verified average first-minute (09:15 candle) absolute move, per
# instrument, from the 43-day hierarchical analysis (22 Aug 2026)
VERIFIED_FIRST_MINUTE_AVG_MOVE = {
    "NIFTY": 26.69,
    "BANKNIFTY": 105.1,
    "SENSEX": 105.4,
}


def check_gamma_opening_signal(symbol, first_candle, gex_regime, prev_close):
    """
    Call ONCE per day, right after the 09:15 candle completes.

    symbol: "NIFTY" or "BANKNIFTY" (SENSEX not currently in our live
    trading universe, only used for the research comparison)
    first_candle: the 09:15 1-min candle {open, high, low, close}
    gex_regime: the live GEX regime string already computed by
    groww_option_chain.py (contains "ACCELERATION" or "PINNING")
    prev_close: previous day's closing price (for gap-direction context)

    Returns {"signal": "LONG"/"SHORT"/"NONE", "reason": str,
    "target_points": float, "sl_points": float}

    Logic: only fires if (a) GEX regime is ACCELERATION (amplifying —
    PINNING regime dampens moves, working AGAINST this strategy's
    premise, so we explicitly skip those days) AND (b) the first
    candle already shows a clear directional move (not a doji/flat
    open, which wouldn't have genuine gamma-explosion momentum to
    capture). Target = verified historical average for that instrument
    (not guessed). SL = half the target (matching our existing ~1.67:1
    R:R baseline design, conservative given untested-live status).
    """
    if "ACCELERATION" not in (gex_regime or ""):
        return {"signal": "NONE", "reason": "GEX regime is not ACCELERATION — gamma-explosion premise doesn't apply today"}

    move = first_candle["close"] - first_candle["open"]
    if abs(move) < 3:  # too flat/indecisive to trust as a genuine directional open
        return {"signal": "NONE", "reason": f"first candle too flat ({move:+.1f}pts) — no clear direction to capture"}

    direction = "LONG" if move > 0 else "SHORT"
    expected_move = VERIFIED_FIRST_MINUTE_AVG_MOVE.get(symbol, 30)

    return {
        "signal": direction,
        "reason": f"gamma-explosion open: GEX={gex_regime[:30]}, first-candle move={move:+.1f}pts, "
                   f"targeting verified-avg {expected_move}pts",
        "target_points": round(expected_move, 1),
        "sl_points": round(expected_move / 2, 1),
    }
