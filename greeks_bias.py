"""
Greeks Layer — IV Skew Directional Bias
------------------------------------------
Uses option Greeks (fetched via GrowwMCP's get_greeks_for_fno_contract —
NOTE: get_greeks_for_fno_symbol for the WHOLE chain returns empty results,
a GrowwMCP quirk discovered 12 Aug 2026; must query specific strikes
individually or in a batch of search_queries instead) to derive a
directional lean from Put-Call IV skew.

CONCEPT: IV Skew
  Same-strike Call and Put IV are forced equal by no-arbitrage (put-call
  parity) — so skew must be read by comparing OTM Call IV against OTM Put
  IV at a SIMILAR |delta| distance from ATM (not the same strike).
    - OTM Put IV > OTM Call IV (at matching |delta|) -> market is paying
      more for downside protection -> fear/hedging demand -> BEARISH lean
    - OTM Call IV > OTM Put IV -> more demand for upside exposure ->
      BULLISH lean
    - Roughly equal -> NEUTRAL

This is standard option-market sentiment reading (volatility skew), not
just a Delta/Theta lookup — Delta and Theta by themselves aren't
directional signals for the underlying (Delta already reflects price
moves, Theta reflects time decay), so skew is the genuinely useful
directional signal Greeks data provides here.
"""

import json


def find_atm_and_otm(contracts, spot_price):
    """
    contracts: list of {strikePrice, optionType, delta, iv, theta, gamma}
    Returns (atm_strike, otm_call, otm_put) where otm_call/otm_put are the
    contracts with |delta| closest to 0.3 (a common "skew reference" point)
    on their respective sides.
    """
    calls = [c for c in contracts if c.get("optionType") == "CE"]
    puts = [c for c in contracts if c.get("optionType") == "PE"]
    if not calls or not puts:
        return None, None, None

    atm_call = min(calls, key=lambda c: abs(c["strikePrice"] - spot_price))
    atm_strike = atm_call["strikePrice"]

    otm_calls = [c for c in calls if c["strikePrice"] > spot_price]
    otm_puts = [c for c in puts if c["strikePrice"] < spot_price]

    otm_call = min(otm_calls, key=lambda c: abs(abs(c.get("delta", 0)) - 0.3)) if otm_calls else None
    otm_put = min(otm_puts, key=lambda c: abs(abs(c.get("delta", 0)) - 0.3)) if otm_puts else None

    return atm_strike, otm_call, otm_put


def compute_greeks_bias(contracts, spot_price, skew_threshold_pct=3.0):
    """
    contracts: list of Greeks dicts as returned by GrowwMCP
    (strikePrice, optionType, delta, iv, theta, gamma, ...)
    Returns a bias dict with lean (BULLISH/BEARISH/NEUTRAL), the skew
    magnitude, and the reference contracts used — or None if insufficient
    data (need at least one usable OTM call and OTM put).
    """
    atm_strike, otm_call, otm_put = find_atm_and_otm(contracts, spot_price)
    if otm_call is None or otm_put is None:
        return None

    call_iv = otm_call.get("iv")
    put_iv = otm_put.get("iv")
    if call_iv is None or put_iv is None or call_iv == 0:
        return None

    skew_pct = (put_iv - call_iv) / call_iv * 100

    if skew_pct > skew_threshold_pct:
        lean = "BEARISH"   # puts richer -> downside fear
    elif skew_pct < -skew_threshold_pct:
        lean = "BULLISH"   # calls richer -> upside demand
    else:
        lean = "NEUTRAL"

    return {
        "lean": lean,
        "skew_pct": round(skew_pct, 2),
        "atm_strike": atm_strike,
        "otm_call_strike": otm_call["strikePrice"],
        "otm_call_iv": call_iv,
        "otm_call_delta": otm_call.get("delta"),
        "otm_put_strike": otm_put["strikePrice"],
        "otm_put_iv": put_iv,
        "otm_put_delta": otm_put.get("delta"),
    }


if __name__ == "__main__":
    # Example using the 5-contract NIFTY snapshot fetched 12 Aug 2026
    sample = [
        {"strikePrice": 24400.0, "optionType": "CE", "delta": 0.5628, "iv": 9.8515, "theta": -10.1521},
        {"strikePrice": 24400.0, "optionType": "PE", "delta": -0.4372, "iv": 9.8515, "theta": -10.1521},
        {"strikePrice": 24500.0, "optionType": "CE", "delta": 0.4332, "iv": 9.7485, "theta": -10.0295},
        {"strikePrice": 24500.0, "optionType": "PE", "delta": -0.5668, "iv": 9.7485, "theta": -10.0295},
        {"strikePrice": 24600.0, "optionType": "CE", "delta": 0.3094, "iv": 9.6938, "theta": -8.9372},
        {"strikePrice": 24300.0, "optionType": "PE", "delta": -0.3162, "iv": 9.9722, "theta": -9.2813},
    ]
    result = compute_greeks_bias(sample, spot_price=24519)
    print(json.dumps(result, indent=2))
