"""
positions.py — tracks Saim's open option positions (bull call spreads etc.)
------------------------------------------------------------------------------
Saim's actual open trades (added 17 Aug 2026), so their status/probability
can be re-checked anytime via GrowwMCP (Claude session) without re-explaining
the position each time.

Each tracked position: symbol, strategy type, legs (strike/side/action),
expiry. check_position() looks up current spot + Greeks of the relevant
strikes and reports current status.

NOTE: This reads live data via GrowwMCP tool calls, which only work
inside a Claude chat session — this is a reference/helper module, not
something the VPS continuous_runner calls (VPS uses groww_api.py direct
API instead, which doesn't have equivalent Greeks-lookup granularity
wired up yet for arbitrary stocks).
"""

TRACKED_POSITIONS = [
    {
        "name": "RELIANCE bull call spread",
        "symbol": "RELIANCE",
        "strategy": "bull_call_spread",
        "expiry": "2026-08-25",
        "buy_strike": 1300,
        "sell_strike": 1340,
        "added_date": "2026-08-17",
    },
    {
        "name": "ADANIPORTS bull call spread",
        "symbol": "ADANIPORTS",
        "strategy": "bull_call_spread",
        "expiry": "2026-08-25",
        "buy_strike": 1680,
        "sell_strike": 1720,
        "added_date": "2026-08-17",
    },
]


def summarize_bull_call_spread(spot, buy_leg_greeks, sell_leg_greeks, buy_strike, sell_strike):
    """
    Given current spot and Greeks dicts for both legs (as returned by
    GrowwMCP's get_greeks_for_fno_contract), returns a plain summary.
    """
    prob_max_profit = sell_leg_greeks.get("delta")  # delta of short strike ~ P(finish above it)
    breakeven_distance_pct = (sell_strike - spot) / spot * 100

    return {
        "spot": spot,
        "buy_strike": buy_strike,
        "sell_strike": sell_strike,
        "distance_to_max_profit_pct": round(breakeven_distance_pct, 2),
        "prob_reaching_max_profit_pct": round((prob_max_profit or 0) * 100, 1),
        "buy_leg_delta": buy_leg_greeks.get("delta"),
        "buy_leg_iv": buy_leg_greeks.get("iv"),
        "sell_leg_delta": sell_leg_greeks.get("delta"),
        "sell_leg_iv": sell_leg_greeks.get("iv"),
        "net_theta_per_day": round((buy_leg_greeks.get("theta", 0) or 0) - (sell_leg_greeks.get("theta", 0) or 0), 3),
    }


if __name__ == "__main__":
    import json
    print("Tracked positions:")
    print(json.dumps(TRACKED_POSITIONS, indent=2))
