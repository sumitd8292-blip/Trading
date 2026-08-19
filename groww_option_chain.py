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


def suggest_strike(rows, spot_price, direction, prefer="ATM"):
    """
    Suggests a specific tradeable strike matching the signal direction.
    direction: "LONG" (suggests a CALL) or "SHORT" (suggests a PUT)
    prefer: "ATM" (closest to spot) — could extend later to "OTM"/"ITM"

    Returns {strike, option_type, ltp, delta, iv, oi} for the suggested
    contract, or None if no usable data.
    """
    option_type = "call" if direction == "LONG" else "put"
    candidates = [r for r in rows if r.get(option_type) and r[option_type].get("delta") is not None]
    if not candidates:
        return None

    atm_row = min(candidates, key=lambda r: abs(r["strike"] - spot_price))
    side = atm_row[option_type]

    return {
        "strike": atm_row["strike"],
        "option_type": "CE" if option_type == "call" else "PE",
        "ltp": side.get("ltp"),
        "delta": side.get("delta"),
        "theta": side.get("theta"),
        "gamma": side.get("gamma"),
        "iv": side.get("iv"),
        "oi": side.get("oi"),
    }


def estimate_premium_move(suggested_strike, index_points_move):
    """
    Estimate of how much the suggested option's premium would move for a
    given index-point move.

    IMPROVED (19 Aug 2026, per Saim's question "why ignore Gamma/Theta"):
    now uses a proper 2nd-order Taylor approximation when Gamma is
    available — ΔPremium ≈ Delta×ΔS + 0.5×Gamma×(ΔS)² — which is
    meaningfully more accurate for larger index moves than the old pure-
    Delta linear estimate (Delta alone understates the move because
    Gamma means Delta itself increases as price moves in the trade's
    favor). Theta is intentionally NOT applied here — Theta is a
    time-decay effect (₹/day), not a price-move effect, and mixing it
    into a point-move estimate would conflate two different things;
    Theta decay is already handled separately in paper_trader.py's real
    premium P&L calculation (Delta+Theta over actual hold time).
    """
    if not suggested_strike or suggested_strike.get("delta") is None:
        return None
    delta = abs(suggested_strike["delta"])
    gamma = suggested_strike.get("gamma")
    linear_term = index_points_move * delta
    if gamma is not None:
        quadratic_term = 0.5 * gamma * (index_points_move ** 2)
        return round(linear_term + quadratic_term, 1)
    return round(linear_term, 1)


def compute_volume_profile(rows, spot_price, strike_range_pct=10.0):
    """
    Computes option VOLUME activity (distinct from OI — OI is
    established/carried positions, Volume is TODAY's actual trading
    activity). Per Saim's 18 Aug point: options generate more day-
    trading volume than futures, so this is a genuinely useful separate
    signal — a strike with sudden high volume but unchanged OI suggests
    active intraday trading (not new positioning), while high volume
    AND rising OI together suggest fresh, committed positioning.

    Returns total call/put volume near the money, Put/Call volume ratio
    (PCR-Volume — reads live activity, complementing PCR-OI which reads
    carried positioning), and the single most-active-by-volume strike
    on each side.
    """
    lo, hi = spot_price * (1 - strike_range_pct / 100), spot_price * (1 + strike_range_pct / 100)
    near = [r for r in rows if lo <= r["strike"] <= hi]
    if not near:
        return None

    total_call_vol = sum((r["call"]["volume"] or 0) for r in near if r["call"])
    total_put_vol = sum((r["put"]["volume"] or 0) for r in near if r["put"])
    pcr_volume = (total_put_vol / total_call_vol) if total_call_vol else 0

    most_active_call = max((r for r in near if r["call"]), key=lambda r: r["call"]["volume"] or 0, default=None)
    most_active_put = max((r for r in near if r["put"]), key=lambda r: r["put"]["volume"] or 0, default=None)

    return {
        "total_call_volume": total_call_vol,
        "total_put_volume": total_put_vol,
        "pcr_volume": round(pcr_volume, 3),
        "most_active_call_strike": most_active_call["strike"] if most_active_call else None,
        "most_active_call_volume": most_active_call["call"]["volume"] if most_active_call else None,
        "most_active_put_strike": most_active_put["strike"] if most_active_put else None,
        "most_active_put_volume": most_active_put["put"]["volume"] if most_active_put else None,
    }
