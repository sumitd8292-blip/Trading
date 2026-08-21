"""
portfolio_agent.py — multi-position/capital-allocation awareness
------------------------------------------------------------------------------
21 Aug 2026: per Saim's priority #2 of 5. Researched portfolio-level
risk guardrails (industry-standard): max single position size, max
total margin utilization, max concurrent positions, correlation-
awareness across positions (avoiding over-concentration in correlated
instruments).

For us specifically: NIFTY and BANKNIFTY are both broad Indian equity
indices and are HIGHLY correlated (both move with overall market
sentiment) — having both open in the SAME direction simultaneously is
NOT true diversification, it's concentrated risk on the same
underlying bet (India-market-up or India-market-down), even though
they're technically two different "symbols".
"""

MAX_CONCURRENT_POSITIONS = 2  # currently only 2 symbols tracked (NIFTY, BANKNIFTY)
MAX_TOTAL_CAPITAL_AT_RISK_PCT = 2.5  # combined risk across ALL open positions, even if
                                       # each individual trade's own risk_pct is within limits


def check_correlation_risk(open_positions):
    """
    open_positions: list of {symbol, direction} for currently open trades.
    Flags if NIFTY and BANKNIFTY are BOTH open in the SAME direction —
    this is concentrated risk (same underlying India-market bet), not
    genuine diversification, even though they're different symbols.
    """
    symbols_directions = {p["symbol"]: p["direction"] for p in open_positions}
    if "NIFTY" in symbols_directions and "BANKNIFTY" in symbols_directions:
        if symbols_directions["NIFTY"] == symbols_directions["BANKNIFTY"]:
            return {
                "correlated_risk": True,
                "reason": f"Both NIFTY and BANKNIFTY open {symbols_directions['NIFTY']} — "
                          f"same underlying India-market direction bet, not true diversification",
            }
    return {"correlated_risk": False, "reason": None}


def check_can_open_new_position(open_positions, new_symbol, new_direction,
                                  new_position_risk_pct, account_capital):
    """
    THE gatekeeper function — call before opening any new trade.
    Checks: (1) max concurrent positions, (2) total capital-at-risk
    across ALL open positions + the new one, (3) correlation risk
    (warns but does NOT block — Saim's system is alert-only/paper-
    trading, so this is informational, matching the "manual
    confirmation required" pattern already used elsewhere).

    Returns {"can_open": bool, "reasons": [list of blocking/warning reasons]}
    """
    reasons = []
    can_open = True

    if len(open_positions) >= MAX_CONCURRENT_POSITIONS:
        can_open = False
        reasons.append(f"BLOCKED: already at max concurrent positions ({MAX_CONCURRENT_POSITIONS})")

    # Already-open-same-symbol check (paper_trader.py already does this
    # separately, but the Portfolio Agent should be aware of it too for
    # a complete picture)
    if any(p["symbol"] == new_symbol for p in open_positions):
        can_open = False
        reasons.append(f"BLOCKED: {new_symbol} already has an open position")

    existing_risk_pct = sum(p.get("risk_pct", 0) for p in open_positions)
    total_risk_pct_if_opened = existing_risk_pct + new_position_risk_pct
    if total_risk_pct_if_opened > MAX_TOTAL_CAPITAL_AT_RISK_PCT:
        can_open = False
        reasons.append(f"BLOCKED: total capital-at-risk would be {total_risk_pct_if_opened:.2f}% "
                        f"(existing {existing_risk_pct:.2f}% + new {new_position_risk_pct:.2f}%), "
                        f"exceeds max {MAX_TOTAL_CAPITAL_AT_RISK_PCT}%")

    hypothetical_positions = open_positions + [{"symbol": new_symbol, "direction": new_direction}]
    corr = check_correlation_risk(hypothetical_positions)
    if corr["correlated_risk"]:
        reasons.append(f"WARNING (not blocking): {corr['reason']}")

    return {"can_open": can_open, "reasons": reasons}
