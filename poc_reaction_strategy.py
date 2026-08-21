"""
poc_reaction_strategy.py — trade POC bounces, with a data-grounded fail-safe
------------------------------------------------------------------------------
21 Aug 2026: per Saim's request — a genuine, testable strategy built on
volume_profile_tracker's POC data. Directly grounded in what we
observed in real data (12-14 Aug: repeated strong bounces off POC
24,400; 17 Aug: a decisive breakdown through it, followed by a large
continuation move in the breakdown direction).

THE STRATEGY:
1. When price approaches within `approach_tolerance` points of a
   tracked POC (rolling contract-period POC is the primary reference —
   it showed the clearest multi-day support behavior; daily POC is a
   secondary/faster-reacting reference)
2. Wait for a REACTION candle — does price actually turn away from the
   level, or does it punch through?
3. If it bounces: enter in the bounce direction (LONG if bouncing UP
   off support, SHORT if rejecting DOWN off resistance)
4. THE FAIL-SAFE (Saim's "agar strategy fail ho to kya" question,
   answered directly): stop-loss is placed just beyond the POC level
   itself, not an arbitrary points-based SL. This is intentional — per
   the 17 Aug example, if price genuinely breaks through POC instead of
   bouncing, that's not a "normal" losing trade, it's evidence the
   level failed and a LARGE continuation move is more likely (the data
   showed -140 to -166pts after the 17 Aug breakdown) — so this SL
   placement means the strategy self-limits exposure exactly at the
   point its core assumption is proven wrong, rather than fighting a
   breakdown.

This is intentionally a THIRD, independent entry strategy — alongside
RSI-Reversal and Trend-Continuation (see STRATEGY_CATALOG.md) — not a
replacement. It fires under genuinely different conditions (price near
a known high-volume node) and should be tracked/tagged separately in
paper_trader.py so its own win-rate can be judged independently.
"""


def check_poc_reaction_signal(current_price, prev_candles, poc_price, approach_tolerance=20,
                               reaction_confirmation_points=8):
    """
    current_price: latest close
    prev_candles: recent candle history (list of {high, low, close}),
    most recent last — needs at least 2-3 candles to detect a reaction
    poc_price: the POC level being tested (rolling contract POC recommended)
    approach_tolerance: how close price must get to POC to count as "testing" it
    reaction_confirmation_points: how much price must move AWAY from POC
    to count as a confirmed bounce (not just noise)

    Returns {"signal": "LONG"/"SHORT"/"NONE", "reason": str, "sl_price": float}
    sl_price is placed just beyond POC (the fail-safe) — NOT a fixed
    point distance like the other two strategies.
    """
    if len(prev_candles) < 3:
        return {"signal": "NONE", "reason": "insufficient history"}

    distance_to_poc = current_price - poc_price
    was_testing_poc = any(abs(c["close"] - poc_price) <= approach_tolerance for c in prev_candles[-3:])

    if not was_testing_poc:
        return {"signal": "NONE", "reason": "price not near POC"}

    # Bounce UP off POC acting as support (price was near/below POC, now moving up away from it)
    if distance_to_poc >= reaction_confirmation_points and prev_candles[-3]["close"] <= poc_price + approach_tolerance:
        sl_price = poc_price - 5  # just beyond POC — the fail-safe: if price
        # comes back and breaks below POC, the bounce thesis is wrong, exit
        return {
            "signal": "LONG", "reason": f"bounced off POC {poc_price} support, +{distance_to_poc:.1f}pts confirmed",
            "sl_price": round(sl_price, 1), "poc_reference": poc_price,
        }

    # Rejection DOWN off POC acting as resistance
    if distance_to_poc <= -reaction_confirmation_points and prev_candles[-3]["close"] >= poc_price - approach_tolerance:
        sl_price = poc_price + 5
        return {
            "signal": "SHORT", "reason": f"rejected off POC {poc_price} resistance, {distance_to_poc:.1f}pts confirmed",
            "sl_price": round(sl_price, 1), "poc_reference": poc_price,
        }

    return {"signal": "NONE", "reason": "testing POC, no confirmed reaction yet"}


def classify_bounce_conviction(bounce_candles, baseline_avg_volume):
    """
    Per Saim's 21 Aug question — "bounce back kyun hua, active-buying
    thi ya sirf seller-absence thi?" — this is a PARTIAL answer using
    what's available NOW (futures volume, already working) without
    needing the still-blocked order_flow_depth/footprint data.

    bounce_candles: the 2-3 candles during the confirmed bounce move
    baseline_avg_volume: typical average volume for this symbol/time
    (e.g. the day's average per-candle volume, or a recent N-candle avg)

    Returns "ACTIVE_PARTICIPATION" (volume during the bounce was
    genuinely elevated vs baseline — real buying/selling pressure
    showed up) or "PASSIVE_DRIFT" (volume was normal/below baseline —
    price moved mostly because the OPPOSING side simply wasn't there,
    not because of active new pressure) or "UNKNOWN" if data's missing.

    HONEST LIMITATION: this is a volume-MAGNITUDE proxy, not true
    buyer/seller aggression classification (which needs footprint/
    order-flow-depth, still blocked). Elevated volume is consistent
    with active participation but doesn't by itself prove WHICH side
    was aggressive — treat this as a coarse signal, not a definitive one.
    """
    if not bounce_candles or not baseline_avg_volume:
        return "UNKNOWN"

    bounce_avg_volume = sum(c.get("volume", 0) for c in bounce_candles) / len(bounce_candles)
    if baseline_avg_volume <= 0:
        return "UNKNOWN"

    ratio = bounce_avg_volume / baseline_avg_volume
    if ratio >= 1.5:
        return "ACTIVE_PARTICIPATION"
    elif ratio <= 0.8:
        return "PASSIVE_DRIFT"
    else:
        return "UNCLEAR"


def determine_trade_mode(day_type_classification, ib_breakout_result):
    """
    Per Market Profile theory (Dalton) verified via research 21 Aug 2026:
    decides whether to trade RESPONSIVE (fade back toward POC — our
    existing bounce logic) or INITIATIVE (go WITH a breakout — trend-
    continuation, do NOT fade) — this is the missing piece Saim
    identified: the POC-Reaction strategy previously ONLY did
    responsive/bounce trades, with no logic for when a breakout is
    genuine and should be followed instead of faded.

    day_type_classification: output of volume_profile.classify_balance_imbalance()
    ib_breakout_result: output of initial_balance.detect_ib_breakout()
    (pass None if no breakout has occurred yet today)

    Returns "RESPONSIVE" (use existing bounce/fade logic) or
    "INITIATIVE" (favor continuation in the breakout direction,
    do NOT fade) or "NEUTRAL" (insufficient signal, skip).
    """
    # A volume-supported Initial Balance breakout is the strongest,
    # earliest signal of a trend day — prioritize this
    if ib_breakout_result and ib_breakout_result.get("breakout") and ib_breakout_result.get("volume_supported"):
        return "INITIATIVE"

    # Otherwise, fall back to the day-type's balance/imbalance read
    if day_type_classification and day_type_classification.get("classification") == "IMBALANCED":
        return "INITIATIVE"

    if day_type_classification and day_type_classification.get("classification") == "BALANCED":
        return "RESPONSIVE"

    return "NEUTRAL"


def check_poc_reaction_signal_v2(current_price, prev_candles, poc_price, trade_mode,
                                   approach_tolerance=20, reaction_confirmation_points=8):
    """
    Version 2 (21 Aug 2026) — mode-aware POC signal, per Saim's
    instruction to properly implement Initiative-vs-Responsive rather
    than always fading. Uses the SAME approach/confirmation logic as
    check_poc_reaction_signal(), but INTERPRETS the reaction differently
    based on trade_mode:

    - RESPONSIVE mode: behaves exactly like the original — bounce off
      POC = trade the bounce direction (fade back toward value)
    - INITIATIVE mode: a "reaction" candle moving AWAY from POC in the
      direction of the broader move is NOT treated as a fade-worthy
      bounce — instead, we look for CONTINUATION confirmation (price
      pushing further in the initiative direction) and trade WITH it,
      not against it
    - NEUTRAL mode: no signal (insufficient basis to choose either mode)
    """
    if trade_mode == "NEUTRAL":
        return {"signal": "NONE", "reason": "trade mode NEUTRAL — insufficient basis"}

    if trade_mode == "RESPONSIVE":
        # identical to the original responsive/bounce logic
        return check_poc_reaction_signal(current_price, prev_candles, poc_price,
                                          approach_tolerance, reaction_confirmation_points)

    # INITIATIVE mode: look for continuation AWAY from POC, not bounce back to it
    if len(prev_candles) < 3:
        return {"signal": "NONE", "reason": "insufficient history"}

    distance_from_poc = current_price - poc_price
    # price has moved decisively away from POC and is CONTINUING that direction
    prior_distance = prev_candles[-3]["close"] - poc_price

    if distance_from_poc >= reaction_confirmation_points and prior_distance > 0 and distance_from_poc > prior_distance:
        sl_price = poc_price + 5  # SL back toward POC — if price returns to POC, initiative thesis failed
        return {
            "signal": "LONG", "reason": f"INITIATIVE continuation above POC {poc_price}, "
                                          f"{distance_from_poc:.1f}pts and extending",
            "sl_price": round(sl_price, 1), "poc_reference": poc_price, "mode": "INITIATIVE",
        }

    if distance_from_poc <= -reaction_confirmation_points and prior_distance < 0 and distance_from_poc < prior_distance:
        sl_price = poc_price - 5
        return {
            "signal": "SHORT", "reason": f"INITIATIVE continuation below POC {poc_price}, "
                                           f"{distance_from_poc:.1f}pts and extending",
            "sl_price": round(sl_price, 1), "poc_reference": poc_price, "mode": "INITIATIVE",
        }

    return {"signal": "NONE", "reason": "INITIATIVE mode active, no confirmed continuation yet"}


def get_microburst_confirmation(approach_direction, microburst_result):
    """
    THE CONFIRMATION-LAYER INTEGRATION (21 Aug 2026, Saim's priority #3
    of 5) — the redesign proposed earlier: LTF Microburst should NOT be
    a standalone strategy, it should CONFIRM or CONTRADICT a POC
    reaction signal.

    approach_direction: "FROM_ABOVE" or "FROM_BELOW" (which way price
    was moving as it approached the POC level)
    microburst_result: output of ltf_microburst.detect_microburst() for
    the current/most-recent candle

    Logic: if the microburst fires in the OPPOSITE direction to the
    approach, it means fresh, aggressive counter-pressure just showed
    up — CONFIRMS a genuine bounce. If it fires in the SAME direction
    as the approach, it means the move has real conviction continuing
    — CONFIRMS a genuine breakdown/continuation, not a bounce.

    Returns "CONFIRMS_BOUNCE", "CONFIRMS_BREAKDOWN", or "NO_CONFIRMATION"
    (no qualifying microburst detected — genuinely uninformative, not a
    vote either way).
    """
    if not microburst_result or not microburst_result.get("is_microburst"):
        return "NO_CONFIRMATION"

    burst_direction = microburst_result["direction"]

    if approach_direction == "FROM_ABOVE":
        return "CONFIRMS_BOUNCE" if burst_direction == "BULLISH" else "CONFIRMS_BREAKDOWN"
    elif approach_direction == "FROM_BELOW":
        return "CONFIRMS_BOUNCE" if burst_direction == "BEARISH" else "CONFIRMS_BREAKDOWN"
    else:
        return "NO_CONFIRMATION"
