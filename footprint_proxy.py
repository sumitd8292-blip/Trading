"""
footprint_proxy.py — sampled buyer/seller aggression classification
------------------------------------------------------------------------------
19 Aug 2026: Saim wants genuine footprint-chart-style analysis (does
buyer/seller "objection" strengthen/weaken as price moves), but agreed
this doesn't need real-time WebSocket tick streaming — our EXISTING
periodic polling cadence (1-3 min, whatever we already fetch) is enough,
since "we're not in a hurry, we just need robust data for the math".

This is a SAMPLED PROXY, not a true tick-by-tick footprint: each time we
poll a quote (which already includes last_price, bid_price, offer_price
per groww_api.fetch_quote_depth), classify that snapshot's last trade as
BUYER-aggressive (traded at/near the ask) or SELLER-aggressive (traded
at/near the bid) — the standard Lee-Ready style classification — and
accumulate a running tally per price-bucket per candle. Over many
samples across a day, this builds a genuinely useful (if coarser than
true footprint) picture of where buying/selling pressure concentrated,
using data we're already fetching — no new infrastructure needed.
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
FOOTPRINT_LOG_PATH = os.path.join(BASE, "memory", "footprint_samples.jsonl")


def classify_trade_aggression(quote_payload):
    """
    Given a quote payload (from groww_api.fetch_quote_depth), classifies
    the most recent trade as BUYER_AGGRESSIVE, SELLER_AGGRESSIVE, or
    NEUTRAL based on where last_price sits relative to bid/ask.
    Standard proxy: closer to ask -> buyer paid up (aggressive buy);
    closer to bid -> seller hit the bid (aggressive sell).
    """
    last_price = quote_payload.get("last_price")
    bid_price = quote_payload.get("bid_price")
    offer_price = quote_payload.get("offer_price")

    if last_price is None or bid_price is None or offer_price is None or offer_price == bid_price:
        return None

    mid = (bid_price + offer_price) / 2
    if last_price >= mid:
        # closer to or at the ask
        proximity_to_ask = (last_price - mid) / (offer_price - mid) if offer_price != mid else 1
        return "BUYER_AGGRESSIVE" if proximity_to_ask > 0.3 else "NEUTRAL"
    else:
        proximity_to_bid = (mid - last_price) / (mid - bid_price) if mid != bid_price else 1
        return "SELLER_AGGRESSIVE" if proximity_to_bid > 0.3 else "NEUTRAL"


def record_footprint_sample(symbol, date_str, price_level, aggression, quantity, timestamp_iso):
    """
    Logs one sampled classification, bucketed by rounded price_level
    (e.g. nearest 5 or 10 points) so repeated samples at similar prices
    accumulate into a meaningful per-level tally over the day.
    """
    if not aggression or aggression == "NEUTRAL":
        return
    entry = {
        "symbol": symbol, "date": date_str, "price_level": price_level,
        "aggression": aggression, "quantity": quantity, "timestamp": timestamp_iso,
    }
    with open(FOOTPRINT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_footprint_summary(symbol, date_str, price_bucket_size=10):
    """
    Aggregates today's samples into a per-price-bucket buy/sell tally —
    the actual "footprint" picture: which price levels saw more buyer
    pressure vs seller pressure, built from accumulated samples.
    """
    if not os.path.exists(FOOTPRINT_LOG_PATH):
        return {}
    with open(FOOTPRINT_LOG_PATH) as f:
        entries = [json.loads(l) for l in f if l.strip()]

    todays = [e for e in entries if e["symbol"] == symbol and e["date"] == date_str]
    if not todays:
        return {}

    buckets = {}
    for e in todays:
        bucket = round(e["price_level"] / price_bucket_size) * price_bucket_size
        buckets.setdefault(bucket, {"buyer_samples": 0, "seller_samples": 0})
        if e["aggression"] == "BUYER_AGGRESSIVE":
            buckets[bucket]["buyer_samples"] += 1
        else:
            buckets[bucket]["seller_samples"] += 1

    for bucket, counts in buckets.items():
        total = counts["buyer_samples"] + counts["seller_samples"]
        counts["net_lean"] = "BUYER" if counts["buyer_samples"] > counts["seller_samples"] else "SELLER"
        counts["buyer_pct"] = round(counts["buyer_samples"] / total * 100, 1) if total else None

    return dict(sorted(buckets.items()))


def check_trend_footprint_shift(footprint_summary, direction):
    """
    Per Saim's exact ask: "on the way up, is seller objection
    decreasing/buyer increasing? On the way down, the opposite?" —
    checks whether buyer_pct is INCREASING across ascending price
    buckets (for an up-move) or DECREASING (for a down-move, meaning
    seller pressure is building as price falls further).
    """
    if not footprint_summary or len(footprint_summary) < 3:
        return None

    buckets_sorted = sorted(footprint_summary.items())
    buyer_pcts = [v["buyer_pct"] for _, v in buckets_sorted if v.get("buyer_pct") is not None]
    if len(buyer_pcts) < 3:
        return None

    # simple trend check: is the sequence generally increasing or decreasing?
    increases = sum(1 for i in range(1, len(buyer_pcts)) if buyer_pcts[i] > buyer_pcts[i - 1])
    decreases = sum(1 for i in range(1, len(buyer_pcts)) if buyer_pcts[i] < buyer_pcts[i - 1])

    if direction == "UP":
        interpretation = "seller objection weakening as price rises (buyer % increasing)" if increases > decreases else \
                          "seller objection still present as price rises (buyer % not consistently increasing)"
    else:
        interpretation = "buyer support weakening as price falls (buyer % decreasing)" if decreases > increases else \
                          "buyer support still present as price falls (buyer % not consistently decreasing)"

    return {"buyer_pct_sequence": buyer_pcts, "interpretation": interpretation}


FOOTPRINT_SUMMARY_PATH = os.path.join(BASE, "memory", "footprint_daily_summaries.jsonl")


def compress_and_cleanup_day(symbol, date_str, price_bucket_size=10):
    """
    Called once at end-of-day: computes the final per-price-bucket
    buyer/seller summary for the day (via get_footprint_summary), saves
    it PERMANENTLY to footprint_daily_summaries.jsonl (this is what
    answers "why is there support/resistance here — genuine buyer
    activity or forced seller objection" for as long as we keep it),
    then removes today's RAW samples from footprint_samples.jsonl (the
    minute-by-minute detail isn't needed once compressed — per Saim's
    19 Aug agreement: keep the compressed summary permanently, clean up
    raw samples daily).
    """
    summary = get_footprint_summary(symbol, date_str, price_bucket_size)
    if not summary:
        return None

    record = {
        "symbol": symbol, "date": date_str,
        "price_bucket_summary": summary,
        "compressed_at": datetime.now().isoformat(),
    }
    with open(FOOTPRINT_SUMMARY_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")

    # Remove today's raw samples for this symbol (keep other days/symbols intact)
    if os.path.exists(FOOTPRINT_LOG_PATH):
        with open(FOOTPRINT_LOG_PATH) as f:
            remaining = [json.loads(l) for l in f if l.strip()]
        remaining = [e for e in remaining if not (e["symbol"] == symbol and e["date"] == date_str)]
        with open(FOOTPRINT_LOG_PATH, "w") as f:
            for e in remaining:
                f.write(json.dumps(e) + "\n")

    return record


def get_historical_price_level_context(symbol, price_level, tolerance=15):
    """
    Looks up PERMANENT compressed summaries for any past day where this
    price level was sampled — answers "has this level shown genuine
    buyer activity before, or just forced seller defense" using
    accumulated history, not just today's data.
    """
    if not os.path.exists(FOOTPRINT_SUMMARY_PATH):
        return []
    with open(FOOTPRINT_SUMMARY_PATH) as f:
        records = [json.loads(l) for l in f if l.strip()]

    matches = []
    for r in records:
        if r["symbol"] != symbol:
            continue
        for bucket_price, data in r["price_bucket_summary"].items():
            if abs(float(bucket_price) - price_level) <= tolerance:
                matches.append({"date": r["date"], "price_bucket": bucket_price, **data})
    return matches
