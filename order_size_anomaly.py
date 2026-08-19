"""
order_size_anomaly.py — statistical anomaly detection on order-book size
------------------------------------------------------------------------------
19 Aug 2026 discussion with Saim: news is always lagging (decision happens,
then it takes 5-15 min to be published) — but large capital moves FIRST,
and that shows up as an anomalously large order size in the order book,
before any news explains why. This is a MECHANICAL/statistical signal
(baseline vs current, a formula), not a "read the news" signal — fits
the "mechanical" tier in confidence_tiers.py, not "behavioral".

Builds a rolling baseline of typical order sizes (from the same depth
snapshots order_flow_depth.py already fetches every ~3 min) and flags
when a fresh snapshot's total visible depth is a statistical outlier
vs that baseline — regardless of WHY, purely on magnitude.
"""
import json
import os
from datetime import datetime
from collections import deque

BASE = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(BASE, "memory", "order_size_baseline.jsonl")
ANOMALY_LOG_PATH = os.path.join(BASE, "memory", "order_size_anomalies.jsonl")
BASELINE_WINDOW = 50  # rolling window of recent snapshots to build baseline from
ANOMALY_STD_THRESHOLD = 2.5  # how many std-devs above the rolling mean counts as anomalous


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def _append_jsonl(path, entry):
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def record_snapshot(symbol, visible_buy_qty, visible_sell_qty, timestamp_iso):
    """
    Call this every time order_flow_depth's 5-level depth is fetched —
    logs the total visible size (buy+sell) to build the rolling baseline.
    Trims to the last BASELINE_WINDOW entries per symbol to keep the file
    small and the baseline recent (order sizes drift over weeks/expiry
    cycles, so an old baseline isn't meaningful).
    """
    total_qty = visible_buy_qty + visible_sell_qty
    entries = _read_jsonl(BASELINE_PATH)
    entries.append({"symbol": symbol, "total_qty": total_qty, "timestamp": timestamp_iso})
    # keep only the most recent BASELINE_WINDOW per symbol
    by_symbol = {}
    for e in entries:
        by_symbol.setdefault(e["symbol"], []).append(e)
    trimmed = []
    for sym, lst in by_symbol.items():
        trimmed.extend(lst[-BASELINE_WINDOW:])
    with open(BASELINE_PATH, "w") as f:
        for e in trimmed:
            f.write(json.dumps(e) + "\n")


def check_for_anomaly(symbol, visible_buy_qty, visible_sell_qty, timestamp_iso, price):
    """
    Compares the CURRENT snapshot's total visible size against the
    rolling baseline (mean + std-dev) for this symbol. If it's a
    statistical outlier (> ANOMALY_STD_THRESHOLD std-devs above mean),
    logs an anomaly event and returns it. Returns None if not enough
    baseline history yet, or no anomaly.
    """
    entries = [e for e in _read_jsonl(BASELINE_PATH) if e["symbol"] == symbol]
    if len(entries) < 10:  # need a minimum sample before baseline is meaningful
        return None

    values = [e["total_qty"] for e in entries]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std_dev = variance ** 0.5

    current_total = visible_buy_qty + visible_sell_qty
    if std_dev == 0:
        return None

    z_score = (current_total - mean) / std_dev
    if z_score < ANOMALY_STD_THRESHOLD:
        return None

    anomaly = {
        "symbol": symbol,
        "timestamp": timestamp_iso,
        "price_at_detection": price,
        "current_total_qty": current_total,
        "baseline_mean": round(mean, 1),
        "baseline_std": round(std_dev, 1),
        "z_score": round(z_score, 2),
        "buy_qty": visible_buy_qty,
        "sell_qty": visible_sell_qty,
        "dominant_side": "BUY" if visible_buy_qty > visible_sell_qty else "SELL",
    }
    _append_jsonl(ANOMALY_LOG_PATH, anomaly)
    return anomaly


def review_anomaly_outcomes():
    """Quick count of anomalies logged so far, for later cross-reference
    against what price did afterward (via divergence_tracker-style
    follow-up, once enough anomalies accumulate to build that layer)."""
    entries = _read_jsonl(ANOMALY_LOG_PATH)
    return {"total_anomalies_logged": len(entries), "recent": entries[-5:]}


if __name__ == "__main__":
    print(json.dumps(review_anomaly_outcomes(), indent=2))
