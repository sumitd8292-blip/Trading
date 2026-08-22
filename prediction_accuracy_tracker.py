"""
prediction_accuracy_tracker.py — closes the "agent isn't learning from
failed predictions" gap Saim identified 22 Aug 2026.
------------------------------------------------------------------------------
Confirmed via code-audit: shortfall_diagnosis existed but was NEVER
actually called by anything; estimated_premium_pnl was post-facto only
(no explicit "predicted X, got Y, how accurate" comparison ever
computed or reviewed). This module closes that gap.

CRITICAL DESIGN POINT (Saim's explicit correction): the prediction
METHOD must match the strategy's own premise. For 5 of our 6 entry
strategies, a simple Delta-linear premium-move estimate is appropriate.
But for gamma_opening_strategy (Box 20) specifically — whose entire
premise IS that Gamma-driven acceleration produces bigger-than-Delta-
implied moves in the first minute — using plain Delta as the
"expected" baseline would make the strategy look wrong even when it's
working exactly as designed. So gamma_opening trades use the EXISTING
Delta+Gamma 2nd-order Taylor estimate (groww_option_chain.estimate_premium_move,
built 19 Aug) as their prediction baseline; all other strategies use
plain Delta.
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
PREDICTION_LOG_PATH = os.path.join(BASE, "memory", "prediction_accuracy_log.jsonl")


def compute_expected_premium_move(strategy_type, index_points_move, delta, gamma=None):
    """
    Returns the expected premium move using the CORRECT method for the
    given strategy_type — plain Delta for most strategies, Delta+Gamma
    2nd-order Taylor specifically for gamma_opening (per Saim's
    explicit distinction).
    """
    delta = abs(delta) if delta is not None else 0
    linear_term = index_points_move * delta

    if strategy_type == "gamma_opening" and gamma is not None:
        quadratic_term = 0.5 * gamma * (index_points_move ** 2)
        return round(linear_term + quadratic_term, 2), "delta_gamma"

    return round(linear_term, 2), "delta_only"


def log_trade_prediction(trade_id, symbol, strategy_type, entry_index_price, delta, gamma):
    """Call when a trade OPENS — records the prediction inputs for
    later comparison once the trade closes and the actual move is known."""
    entry = {
        "trade_id": trade_id, "symbol": symbol, "strategy_type": strategy_type,
        "entry_index_price": entry_index_price, "delta": delta, "gamma": gamma,
        "status": "OPEN",
    }
    with open(PREDICTION_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def check_prediction_accuracy(trade_id, exit_index_price, actual_premium_move):
    """
    Call when a trade CLOSES — computes the expected premium move (via
    the strategy-appropriate method) and compares against the ACTUAL
    realized premium move, producing an accuracy record.

    Returns {"expected": float, "actual": float, "accuracy_pct": float,
    "method_used": str} or None if the trade_id wasn't found.
    """
    entries = []
    if os.path.exists(PREDICTION_LOG_PATH):
        with open(PREDICTION_LOG_PATH) as f:
            entries = [json.loads(l) for l in f if l.strip()]

    for e in entries:
        if e["trade_id"] == trade_id and e["status"] == "OPEN":
            index_move = exit_index_price - e["entry_index_price"]
            expected, method = compute_expected_premium_move(
                e["strategy_type"], index_move, e["delta"], e.get("gamma"))

            e["status"] = "CLOSED"
            e["index_move"] = round(index_move, 2)
            e["expected_premium_move"] = expected
            e["actual_premium_move"] = round(actual_premium_move, 2)
            e["method_used"] = method
            # accuracy: how close actual was to expected, as a % (100% = perfect,
            # can go negative if actual moved opposite direction from expected)
            if expected != 0:
                e["accuracy_pct"] = round((1 - abs(actual_premium_move - expected) / abs(expected)) * 100, 1)
            else:
                e["accuracy_pct"] = None

            with open(PREDICTION_LOG_PATH, "w") as f:
                for entry in entries:
                    f.write(json.dumps(entry) + "\n")
            return e
    return None


def review_prediction_accuracy_by_strategy():
    """
    Aggregates prediction-accuracy across all closed trades, grouped by
    strategy_type — the actual "is the agent learning" answer: which
    strategies' premium predictions are reliable, which consistently
    over/under-predict.
    """
    if not os.path.exists(PREDICTION_LOG_PATH):
        return {"message": "No prediction data yet."}

    with open(PREDICTION_LOG_PATH) as f:
        entries = [json.loads(l) for l in f if l.strip()]
    closed = [e for e in entries if e["status"] == "CLOSED" and e.get("accuracy_pct") is not None]

    if not closed:
        return {"message": "No closed predictions with valid accuracy yet."}

    from collections import defaultdict
    by_strategy = defaultdict(list)
    for e in closed:
        by_strategy[e["strategy_type"]].append(e)

    report = {}
    for strat, trades in by_strategy.items():
        avg_accuracy = sum(t["accuracy_pct"] for t in trades) / len(trades)
        avg_expected = sum(t["expected_premium_move"] for t in trades) / len(trades)
        avg_actual = sum(t["actual_premium_move"] for t in trades) / len(trades)
        report[strat] = {
            "trade_count": len(trades), "avg_accuracy_pct": round(avg_accuracy, 1),
            "avg_expected_premium_move": round(avg_expected, 2), "avg_actual_premium_move": round(avg_actual, 2),
            "systematic_bias": "OVER-predicts" if avg_expected > avg_actual else "UNDER-predicts" if avg_expected < avg_actual else "unbiased",
        }
    return report
