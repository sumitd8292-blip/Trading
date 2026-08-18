"""
post_close_accuracy_tracker.py — did the gap prediction come true?
------------------------------------------------------------------------
post_close_momentum.py predicts next-day gap direction from the
15:15-15:30 futures continuation window, but until now nothing checked
whether that prediction actually played out. This closes the loop:
log_prediction() saves today's prediction, check_next_day_actual() run
the following morning compares the actual open to the prediction.
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
PREDICTIONS_PATH = os.path.join(BASE, "memory", "gap_predictions.jsonl")


def _read_all():
    if not os.path.exists(PREDICTIONS_PATH):
        return []
    with open(PREDICTIONS_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(PREDICTIONS_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def log_prediction(symbol, prediction_date, direction, net_move_pts, close_price):
    """
    Call this after running post_close_momentum.py — logs the predicted
    direction for the NEXT trading day's open, to be checked later.
    """
    entries = _read_all()
    entries = [e for e in entries if not (e["symbol"] == symbol and e["prediction_date"] == prediction_date)]
    entries.append({
        "symbol": symbol,
        "prediction_date": prediction_date,
        "predicted_direction": direction,
        "predicted_move_pts": net_move_pts,
        "reference_close": close_price,
        "logged_at": datetime.now().isoformat(),
        "checked": False,
        "actual_open": None,
        "actual_gap_pts": None,
        "correct": None,
    })
    _write_all(entries)


def check_prediction(symbol, prediction_date, actual_next_day_open):
    """
    Call this the next trading morning with the actual opening price —
    marks whether the predicted direction matched the actual gap.
    """
    entries = _read_all()
    found = None
    for e in entries:
        if e["symbol"] == symbol and e["prediction_date"] == prediction_date and not e["checked"]:
            gap = actual_next_day_open - e["reference_close"]
            actual_direction = "UP" if gap > 0 else ("DOWN" if gap < 0 else "FLAT")
            e["checked"] = True
            e["actual_open"] = actual_next_day_open
            e["actual_gap_pts"] = round(gap, 1)
            e["correct"] = (e["predicted_direction"] == actual_direction) or \
                            (e["predicted_direction"] == "FLAT" and abs(gap) < 10)
            found = e
    _write_all(entries)
    return found


def review_accuracy():
    """Reports the prediction hit-rate so far — the real answer to
    'does the post-close momentum window actually predict next-day gaps'."""
    checked = [e for e in _read_all() if e["checked"]]
    if not checked:
        return {"total_checked": 0, "message": "No predictions checked yet."}
    correct = sum(1 for e in checked if e["correct"])
    return {
        "total_checked": len(checked),
        "correct": correct,
        "accuracy_pct": round(correct / len(checked) * 100, 1),
    }


if __name__ == "__main__":
    print(json.dumps(review_accuracy(), indent=2))
