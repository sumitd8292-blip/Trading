"""
order_flow_depth.py — real bid/ask order-book analysis
------------------------------------------------------------------------
Saim's 19 Aug 2026 point, precisely encoded: OI/PCR is a POSITIONING
snapshot (who holds what, updated periodically) — it is NOT the same as
real-time ORDER FLOW (who is actually punching orders right now, at
which price, and who's absorbing them). His exact scenario: OI/PCR
shows bullish, price tries to rally, but at a certain level heavy SELL
orders get punched and absorb the buying — price stalls or reverses
despite "bullish" positioning data. This needs actual bid/ask MARKET
DEPTH to detect, which groww_api.fetch_quote_depth() now provides
(5-level buy/sell order book, updated live).

This module reads that depth and computes:
  - buy/sell quantity imbalance (which side has more resting size)
  - an "absorption" flag: OI/PCR sentiment vs depth imbalance DISAGREE
    (e.g. OI says bullish but sell-side depth is heavier) — this is
    the exact pattern Saim described and wants tracked
"""


def compute_depth_imbalance(quote_payload):
    """
    quote_payload: the dict returned by groww_api.fetch_quote_depth()
    (has totalBuyQty, totalSellQty, buyBook, sellBook with 5 levels each)

    Returns {total_buy_qty, total_sell_qty, imbalance_ratio, lean,
    top_level_buy_qty, top_level_sell_qty} or None if depth data missing.
    imbalance_ratio > 1 means more buy-side resting size (support),
    < 1 means more sell-side resting size (resistance/absorption).
    """
    if not quote_payload:
        return None

    total_buy = quote_payload.get("totalBuyQty")
    total_sell = quote_payload.get("totalSellQty")
    if total_buy is None or total_sell is None:
        return None

    imbalance_ratio = round(total_buy / total_sell, 3) if total_sell else None

    buy_book = quote_payload.get("buyBook", {})
    sell_book = quote_payload.get("sellBook", {})
    top_buy = buy_book.get("1", {}).get("qty")
    top_sell = sell_book.get("1", {}).get("qty")

    if imbalance_ratio is None:
        lean = "NEUTRAL"
    elif imbalance_ratio > 1.15:
        lean = "BUY_HEAVY"  # more resting buy-side size — support building
    elif imbalance_ratio < 0.87:
        lean = "SELL_HEAVY"  # more resting sell-side size — resistance/absorption
    else:
        lean = "NEUTRAL"

    return {
        "total_buy_qty": total_buy,
        "total_sell_qty": total_sell,
        "imbalance_ratio": imbalance_ratio,
        "lean": lean,
        "top_level_buy_qty": top_buy,
        "top_level_sell_qty": top_sell,
    }


def detect_absorption(oi_lean, depth_imbalance):
    """
    Compares OI/PCR positioning lean against real-time depth imbalance —
    flags Saim's exact scenario: OI says one thing, but the actual order
    book (who's punching orders right now) shows the opposite pressure.
    This is a genuinely different signal from OI-vs-price divergence
    (divergence_tracker.py) — this compares POSITIONING vs ORDER FLOW,
    not positioning vs realized price movement.

    Returns a dict describing the situation, or None if no depth data.
    """
    if not depth_imbalance or depth_imbalance["lean"] == "NEUTRAL":
        return None

    absorption_detected = (
        (oi_lean == "BULLISH" and depth_imbalance["lean"] == "SELL_HEAVY") or
        (oi_lean == "BEARISH" and depth_imbalance["lean"] == "BUY_HEAVY")
    )

    return {
        "absorption_detected": absorption_detected,
        "oi_lean": oi_lean,
        "depth_lean": depth_imbalance["lean"],
        "imbalance_ratio": depth_imbalance["imbalance_ratio"],
        "interpretation": (
            f"OI/PCR says {oi_lean} but order-book depth shows {depth_imbalance['lean']} "
            f"pressure — real orders may be absorbing the OI-implied direction"
        ) if absorption_detected else "OI positioning and order-book depth agree",
    }
