"""
groww_option_chain.py — live option chain parsing + Gamma exposure
------------------------------------------------------------------------
Built from the CONFIRMED real response structure (fetched live 17 Aug
2026 via inspect_option_chain.py — docs alone weren't specific enough):

  payload = {
    "<strike>": {
      "CE": {"greeks": {delta, gamma, theta, vega, rho, iv},
             "trading_symbol", "ltp", "open_interest", "volume"},
      "PE": {... same shape ...}
    },
    ...
  }

Replaces the old manual-CSV-upload workflow (oi_orderflow.py /
greeks_bias.py) with ONE live API call that has OI + Greeks together.

NEW capability: Gamma Exposure (GEX) — sums gamma * open_interest across
strikes to show where dealer/market-maker hedging pressure concentrates.
Directly relevant to Saim's "gamma blast on expiry day" question:
  - High gamma concentration near the current spot price means small
    price moves force large hedging flows (can accelerate moves near
    that strike — the "gamma blast" effect)
  - Net GEX sign (calls vs puts) gives a rough read on whether dealer
    hedging is likely to dampen (positive GEX, "pinning") or amplify
    (negative GEX) moves — a simplified but standard retail-facing GEX
    read, not a precise market-maker model
"""

import json


def parse_option_chain(payload):
    """
    Returns a list of {strike, call: {...}, put: {...}} dicts, one per
    strike, with call/put each holding delta/gamma/theta/vega/iv/ltp/oi/volume.
    """
    # Defensive: some Groww endpoints return payload values as JSON-encoded
    # strings rather than nested objects (seen in other endpoints docs) —
    # handle that case too.
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        return []
    # Confirmed live structure (17 Aug 2026): top-level payload is
    # {"underlying_ltp": ..., "strikes": {"<strike>": {"CE":..., "PE":...}}}
    # — strikes are nested under "strikes", not at the top level.
    strikes_dict = payload.get("strikes", payload)
    rows = []
    for strike_str, sides in strikes_dict.items():
        try:
            strike = float(strike_str)
        except ValueError:
            continue

        def _extract(side):
            if not side:
                return None
            g = side.get("greeks", {}) or {}
            return {
                "delta": g.get("delta"), "gamma": g.get("gamma"),
                "theta": g.get("theta"), "vega": g.get("vega"), "iv": g.get("iv"),
                "ltp": side.get("ltp"), "oi": side.get("open_interest"),
                "volume": side.get("volume"),
            }

        rows.append({
            "strike": strike,
            "call": _extract(sides.get("CE")),
            "put": _extract(sides.get("PE")),
        })

    rows.sort(key=lambda r: r["strike"])
    return rows


def compute_gamma_exposure(rows, spot_price, strike_range_pct=10.0):
    """
    Computes total Gamma Exposure (GEX) near the money, and identifies
    the strike(s) with peak gamma concentration — the level(s) most
    likely to see accelerated moves / pinning behavior on expiry day.

    strike_range_pct: only consider strikes within this % of spot
    (far OTM/ITM gamma is negligible and adds noise).
    """
    lo, hi = spot_price * (1 - strike_range_pct / 100), spot_price * (1 + strike_range_pct / 100)
    near = [r for r in rows if lo <= r["strike"] <= hi]
    if not near:
        return None

    total_call_gex = 0
    total_put_gex = 0
    strike_gex = []

    for r in near:
        c, p = r["call"], r["put"]
        c_gex = (c["gamma"] or 0) * (c["oi"] or 0) if c else 0
        p_gex = (p["gamma"] or 0) * (p["oi"] or 0) if p else 0
        total_call_gex += c_gex
        total_put_gex += p_gex
        strike_gex.append((r["strike"], c_gex + p_gex))

    net_gex = total_call_gex - total_put_gex  # standard convention: calls positive, puts negative
    peak_strike = max(strike_gex, key=lambda x: x[1])[0] if strike_gex else None

    return {
        "net_gex": round(net_gex, 2),
        "total_call_gex": round(total_call_gex, 2),
        "total_put_gex": round(total_put_gex, 2),
        "peak_gamma_strike": peak_strike,
        "regime": "PINNING likely (positive GEX — dealers hedge against moves, dampening volatility)"
                  if net_gex > 0 else
                  "ACCELERATION likely (negative GEX — dealers hedge with moves, amplifying volatility)",
        "strikes_considered": len(near),
    }


def compute_oi_and_iv_bias(rows, spot_price):
    """Same PCR/support-resistance/IV-skew reads as the old CSV-based
    layers, but sourced from the live option-chain call (no more manual
    upload needed)."""
    total_call_oi = sum((r["call"]["oi"] or 0) for r in rows if r["call"])
    total_put_oi = sum((r["put"]["oi"] or 0) for r in rows if r["put"])
    pcr = (total_put_oi / total_call_oi) if total_call_oi else 0

    max_call_row = max((r for r in rows if r["call"]), key=lambda r: r["call"]["oi"] or 0, default=None)
    max_put_row = max((r for r in rows if r["put"]), key=lambda r: r["put"]["oi"] or 0, default=None)

    return {
        "pcr": round(pcr, 3),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "resistance_strike": max_call_row["strike"] if max_call_row else None,
        "support_strike": max_put_row["strike"] if max_put_row else None,
    }


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from groww_api import fetch_option_chain

    underlying = sys.argv[1] if len(sys.argv) > 1 else "NIFTY"
    expiry = sys.argv[2] if len(sys.argv) > 2 else "2026-08-18"

    payload = fetch_option_chain(underlying, expiry)
    spot = payload.get("underlying_ltp") if isinstance(payload, dict) else None
    if len(sys.argv) > 3:
        spot = float(sys.argv[3])  # manual override still supported
    print(f"Spot (underlying_ltp): {spot}")
    rows = parse_option_chain(payload)
    print(f"Parsed {len(rows)} strikes")

    gex = compute_gamma_exposure(rows, spot)
    print("\nGamma Exposure:")
    print(json.dumps(gex, indent=2))

    oi_iv = compute_oi_and_iv_bias(rows, spot)
    print("\nOI/PCR:")
    print(json.dumps(oi_iv, indent=2))
