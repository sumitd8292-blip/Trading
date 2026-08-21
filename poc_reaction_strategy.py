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
