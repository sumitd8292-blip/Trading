"""
risk_agent.py — fixed-fractional position sizing (Saim's priority #2 of 5)
------------------------------------------------------------------------------
21 Aug 2026: per Saim's sequential instruction. Researched standard
position-sizing methods (Fixed Fractional, Kelly Criterion, ATR-based).
Fixed Fractional chosen as the base — standard industry practice
("mathematically superior... used by proprietary firms", 1-2% risk of
account equity per trade), simple, well-understood, doesn't require
reliable historical win-rate data (unlike Kelly, which needs that and
is often too aggressive even fractionally).

Formula: num_lots = floor(risk_amount_rupees / premium_risk_per_lot)
where risk_amount_rupees = account_capital * risk_pct, and
premium_risk_per_lot = index_sl_points * abs(delta) * lot_size
(Delta converts index-point SL into an approximate premium-point risk,
consistent with how paper_trader.py already computes real premium P&L).
"""
import math

DEFAULT_RISK_PCT = 1.5  # middle of the standard 1-2% range
DEFAULT_LOT_SIZES = {"NIFTY": 75, "BANKNIFTY": 35}  # current NSE lot sizes as of 21 Aug 2026


def compute_position_size(account_capital, index_sl_points, delta, symbol="NIFTY",
                           risk_pct=DEFAULT_RISK_PCT, lot_size=None):
    """
    Returns the number of lots to trade under fixed-fractional risk
    management, given the account's total capital, this specific
    trade's SL distance (in index points), and the option's Delta.

    Returns {"num_lots": int, "risk_amount_rupees": float,
    "premium_risk_per_lot": float, "capital_at_risk_pct_actual": float}
    — num_lots is always floor()'d (never round up — per research,
    "the fractional contract you leave on the table is your margin of
    safety against model error, slippage").
    """
    if lot_size is None:
        lot_size = DEFAULT_LOT_SIZES.get(symbol, 75)

    if account_capital <= 0 or index_sl_points <= 0 or delta == 0:
        return {"num_lots": 0, "risk_amount_rupees": 0, "premium_risk_per_lot": 0,
                "capital_at_risk_pct_actual": 0, "reason": "invalid inputs"}

    risk_amount_rupees = account_capital * (risk_pct / 100)
    premium_risk_per_lot = index_sl_points * abs(delta) * lot_size
    num_lots = math.floor(risk_amount_rupees / premium_risk_per_lot) if premium_risk_per_lot > 0 else 0

    actual_risk_rupees = num_lots * premium_risk_per_lot
    actual_risk_pct = round(actual_risk_rupees / account_capital * 100, 2) if account_capital else 0

    return {
        "num_lots": num_lots,
        "risk_amount_rupees": round(risk_amount_rupees, 2),
        "premium_risk_per_lot": round(premium_risk_per_lot, 2),
        "capital_at_risk_pct_actual": actual_risk_pct,
        "lot_size_used": lot_size,
    }
