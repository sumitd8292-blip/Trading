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

    IMPROVED (19 Aug 2026, per Saim's question "does it use all 5
    levels or just the top?"): now explicitly sums buy/sell quantity
    across ALL 5 visible price levels (visible_depth_ratio) — this is
    the immediate, actionable order-book picture, distinct from
    totalBuyQty/totalSellQty which are the EXCHANGE'S whole-book
    aggregate (much larger numbers, includes orders far from the
    current price, less relevant for detecting an immediate defended
    level). Also identifies the single HEAVIEST level on each side (the
    "wall") — which price and how much size, since a big order sitting
    at one specific level (not spread evenly) is exactly the "someone
    punched 15000 at this exact price" scenario Saim described.

    Returns both the whole-book aggregate ratio AND the 5-level visible
    ratio, plus the detected wall (if any).
    """
    if not quote_payload:
        return None

    total_buy = quote_payload.get("totalBuyQty")
    total_sell = quote_payload.get("totalSellQty")

    buy_book = quote_payload.get("buyBook", {})
    sell_book = quote_payload.get("sellBook", {})

    visible_buy_qty = sum((buy_book.get(str(i), {}).get("qty") or 0) for i in range(1, 6))
    visible_sell_qty = sum((sell_book.get(str(i), {}).get("qty") or 0) for i in range(1, 6))
    visible_depth_ratio = round(visible_buy_qty / visible_sell_qty, 3) if visible_sell_qty else None

    # Find the single heaviest level on each side — the "wall"
    buy_levels = [(buy_book.get(str(i), {}).get("price"), buy_book.get(str(i), {}).get("qty") or 0) for i in range(1, 6)]
    sell_levels = [(sell_book.get(str(i), {}).get("price"), sell_book.get(str(i), {}).get("qty") or 0) for i in range(1, 6)]
    heaviest_buy = max(buy_levels, key=lambda x: x[1], default=(None, 0))
    heaviest_sell = max(sell_levels, key=lambda x: x[1], default=(None, 0))

    whole_book_ratio = round(total_buy / total_sell, 3) if (total_buy is not None and total_sell) else None

    if visible_depth_ratio is None:
        lean = "NEUTRAL"
    elif visible_depth_ratio > 1.15:
        lean = "BUY_HEAVY"  # more resting buy-side size in visible depth — support building
    elif visible_depth_ratio < 0.87:
        lean = "SELL_HEAVY"  # more resting sell-side size in visible depth — resistance/absorption
    else:
        lean = "NEUTRAL"

    return {
        "visible_buy_qty": visible_buy_qty,
        "visible_sell_qty": visible_sell_qty,
        "visible_depth_ratio": visible_depth_ratio,  # sum of all 5 levels each side — the one that matters most
        "whole_book_ratio": whole_book_ratio,          # exchange-wide aggregate, broader context
        "lean": lean,
        "heaviest_buy_level": {"price": heaviest_buy[0], "qty": heaviest_buy[1]},
        "heaviest_sell_level": {"price": heaviest_sell[0], "qty": heaviest_sell[1]},
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
        "visible_depth_ratio": depth_imbalance["visible_depth_ratio"],
        "wall": depth_imbalance["heaviest_sell_level"] if depth_imbalance["lean"] == "SELL_HEAVY" else depth_imbalance["heaviest_buy_level"],
        "interpretation": (
            f"OI/PCR says {oi_lean} but order-book depth (all 5 levels) shows {depth_imbalance['lean']} "
            f"pressure — biggest wall at price {depth_imbalance['heaviest_sell_level']['price'] if depth_imbalance['lean']=='SELL_HEAVY' else depth_imbalance['heaviest_buy_level']['price']} "
            f"(qty {depth_imbalance['heaviest_sell_level']['qty'] if depth_imbalance['lean']=='SELL_HEAVY' else depth_imbalance['heaviest_buy_level']['qty']}) "
            f"— real orders may be absorbing the OI-implied direction there"
        ) if absorption_detected else "OI positioning and order-book depth agree",
    }
