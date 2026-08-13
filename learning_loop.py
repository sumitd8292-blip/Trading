"""
Learning Loop
---------------
Closes the feedback cycle: record what actually happened after each
alerted signal, then periodically review which layers' agreement
correlates with wins vs losses — so the agent can flag which
confirmations are earning their weight and which aren't, instead of
trusting the rubric blindly forever.

Two pieces:
  1. record_outcome() — call this once you know how a trade played out
     (hit target, hit SL, or manually exited/no-trade), updates the
     matching entry in memory/trade_log.jsonl
  2. review_performance() — reads all entries with outcomes filled in,
     breaks down win rate by which layers agreed/disagreed/were silent,
     and produces plain-language suggestions (not automatic reweighting
     — Saim reviews and decides, per the "mutual consent" discipline
     carried over from FlowDesk)

This does NOT auto-adjust engine.py's scoring weights. It surfaces the
evidence; changing weights is a deliberate, reviewed step.
"""

import json
import os
from collections import defaultdict
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
TRADE_LOG_PATH = os.path.join(BASE, "memory", "trade_log.jsonl")


def _read_all():
    if not os.path.exists(TRADE_LOG_PATH):
        return []
    with open(TRADE_LOG_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(TRADE_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def record_outcome(symbol, date_str, outcome, points=None, exit_reason="", notes=""):
    """
    Finds the most recent trade_log.jsonl entry for (symbol, date) that
    doesn't already have an outcome recorded, and fills it in.

    outcome: "WIN" | "LOSS" | "NO_TRADE" (signal fired but Saim chose not
             to take it, or it was skipped) | "BREAKEVEN"
    points: net points gained/lost (positive for win, negative for loss),
            optional but useful for the review to compute expectancy
    exit_reason: e.g. "hit target", "hit SL", "manual exit", "EOD close"

    Returns the updated entry, or None if no matching un-outcomed entry
    was found.
    """
    entries = _read_all()
    match_idx = None
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if e.get("symbol") == symbol and e.get("outcome") is None and date_str in e.get("ts", ""):
            match_idx = i
            break

    if match_idx is None:
        return None

    entries[match_idx]["outcome"] = outcome
    entries[match_idx]["outcome_points"] = points
    entries[match_idx]["exit_reason"] = exit_reason
    entries[match_idx]["outcome_notes"] = notes
    entries[match_idx]["outcome_recorded_at"] = datetime.now().isoformat()
    _write_all(entries)
    return entries[match_idx]


def review_performance(min_trades_for_layer_stat=3):
    """
    Reads all trade_log.jsonl entries with a recorded outcome and returns
    a performance breakdown: overall stats, plus per-layer win rate when
    that layer agreed vs disagreed vs was silent/unavailable.
    """
    entries = [e for e in _read_all() if e.get("outcome") in ("WIN", "LOSS", "BREAKEVEN")]
    if not entries:
        return {"total_trades_with_outcome": 0, "message": "No outcomes recorded yet."}

    total = len(entries)
    wins = sum(1 for e in entries if e["outcome"] == "WIN")
    losses = sum(1 for e in entries if e["outcome"] == "LOSS")
    total_points = sum(e.get("outcome_points") or 0 for e in entries)

    # Per-layer breakdown: for each layer, split trades by its recorded
    # status (agree/disagree/neutral/unavailable) and compute win rate
    # within each split.
    layer_breakdown = defaultdict(lambda: defaultdict(lambda: {"count": 0, "wins": 0, "points": 0}))
    for e in entries:
        layer_status = e.get("layer_status") or {}
        outcome_is_win = e["outcome"] == "WIN"
        pts = e.get("outcome_points") or 0
        for layer, status in layer_status.items():
            bucket = layer_breakdown[layer][status]
            bucket["count"] += 1
            bucket["points"] += pts
            if outcome_is_win:
                bucket["wins"] += 1

    layer_summary = {}
    suggestions = []
    for layer, statuses in layer_breakdown.items():
        layer_summary[layer] = {}
        for status, stats in statuses.items():
            wr = (stats["wins"] / stats["count"] * 100) if stats["count"] else 0
            layer_summary[layer][status] = {
                "trades": stats["count"],
                "win_rate_pct": round(wr, 1),
                "total_points": round(stats["points"], 1),
            }
        # Suggestion logic: compare "agree" win rate vs overall, if enough samples
        agree_stats = statuses.get("agree")
        disagree_stats = statuses.get("disagree")
        overall_wr = (wins / total * 100) if total else 0
        if agree_stats and agree_stats["count"] >= min_trades_for_layer_stat:
            agree_wr = agree_stats["wins"] / agree_stats["count"] * 100
            diff = agree_wr - overall_wr
            if diff >= 15:
                suggestions.append(f"{layer}: when it AGREED, win rate was {agree_wr:.0f}% "
                                    f"vs {overall_wr:.0f}% overall ({agree_stats['count']} trades) — "
                                    f"this layer's confirmation looks genuinely valuable, consider weighting it higher")
            elif diff <= -15:
                suggestions.append(f"{layer}: when it AGREED, win rate was actually LOWER "
                                    f"({agree_wr:.0f}% vs {overall_wr:.0f}% overall, {agree_stats['count']} trades) — "
                                    f"worth investigating whether this layer's logic is backwards or noisy")
        if disagree_stats and disagree_stats["count"] >= min_trades_for_layer_stat:
            disagree_wr = disagree_stats["wins"] / disagree_stats["count"] * 100
            if disagree_wr <= overall_wr - 15:
                suggestions.append(f"{layer}: when it DISAGREED, win rate dropped to {disagree_wr:.0f}% "
                                    f"({disagree_stats['count']} trades) — the 'treat with caution' flag is earning its keep")

    return {
        "total_trades_with_outcome": total,
        "wins": wins,
        "losses": losses,
        "overall_win_rate_pct": round(wins / total * 100, 1) if total else 0,
        "total_points": round(total_points, 1),
        "avg_points_per_trade": round(total_points / total, 2) if total else 0,
        "layer_summary": layer_summary,
        "suggestions": suggestions,
    }


if __name__ == "__main__":
    result = review_performance()
    print(json.dumps(result, indent=2))
