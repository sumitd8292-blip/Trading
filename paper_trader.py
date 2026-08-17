"""
paper_trader.py — self-generated paper trades for faster learning
------------------------------------------------------------------------
Direct response to Saim's 17 Aug feedback: waiting for him to manually
report every trade outcome is too slow — the agent already has price
action, all its own analysis layers, and a full rubric. It should
generate its OWN paper trades from every signal it produces (whether or
not Saim actually takes that trade), track them to completion (SL/
target/EOD), and feed outcomes into learning_loop.py automatically.
This builds a continuous stream of training data even on days Saim
personally can't or doesn't trade — much faster than manual reporting.

FLOW:
  1. Whenever engine.score_setup() produces a real signal (LONG/SHORT,
     not NONE), open_paper_trade() records it: entry price, SL, target,
     timestamp, and the full layer_status (so learning_loop can later
     analyze which layers were right).
  2. Each subsequent loop tick, check_open_trades() checks all OPEN
     paper trades against the latest candle: did price hit SL or
     target? If yes, close it and call learning_loop.record_outcome()
     automatically — no manual input needed.
  3. At end of day, any still-open trade is closed at the EOD price
     (marked BREAKEVEN or WIN/LOSS based on final P&L) so nothing stays
     open overnight (index/stock options expire same-day relevance).

This is intentionally SEPARATE from "real" trades Saim actually takes —
paper trades are the agent's own self-generated learning data, distinct
from Saim's actual executed positions (tracked in positions.py).
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
PAPER_TRADES_PATH = os.path.join(BASE, "memory", "paper_trades.jsonl")


def _read_all():
    if not os.path.exists(PAPER_TRADES_PATH):
        return []
    with open(PAPER_TRADES_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(PAPER_TRADES_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def open_paper_trade(symbol, date_str, signal, entry_price, sl_points, target_points, layer_status, score, reasons):
    """
    Records a new self-generated paper trade. One open trade per
    (symbol, date) at a time — if one's already open for today, skip
    (avoids overlapping paper positions from repeated signal checks).
    """
    entries = _read_all()
    already_open = any(e["symbol"] == symbol and e["date"] == date_str and e["status"] == "OPEN" for e in entries)
    if already_open:
        return None

    if signal == "LONG":
        sl_price = entry_price - sl_points
        target_price = entry_price + target_points
    else:  # SHORT
        sl_price = entry_price + sl_points
        target_price = entry_price - target_points

    trade = {
        "symbol": symbol,
        "date": date_str,
        "signal": signal,
        "entry_price": entry_price,
        "entry_time": datetime.now().isoformat(),
        "sl_price": round(sl_price, 2),
        "target_price": round(target_price, 2),
        "sl_points": sl_points,
        "target_points": target_points,
        "layer_status": layer_status,
        "score": score,
        "reasons": reasons,
        "status": "OPEN",
        "outcome": None,
        "outcome_points": None,
        "exit_price": None,
        "exit_time": None,
    }
    entries.append(trade)
    _write_all(entries)
    return trade


def check_open_trades(symbol, latest_candles, is_eod=False):
    """
    Checks all OPEN paper trades for `symbol` against the latest candle
    data (list of {high, low, close, timestamp}). Closes any that hit
    SL/target, or force-closes at EOD if is_eod=True. Automatically
    records outcomes via learning_loop.record_outcome().

    Returns a list of trades that were closed this call (for logging/alerting).
    """
    import sys
    sys.path.insert(0, BASE)
    from learning_loop import record_outcome

    entries = _read_all()
    closed_this_call = []
    latest = latest_candles[-1]

    for trade in entries:
        if trade["symbol"] != symbol or trade["status"] != "OPEN":
            continue

        hit_sl = hit_target = False
        if trade["signal"] == "LONG":
            hit_target = latest["high"] >= trade["target_price"]
            hit_sl = latest["low"] <= trade["sl_price"]
        else:
            hit_target = latest["low"] <= trade["target_price"]
            hit_sl = latest["high"] >= trade["sl_price"]

        exit_reason = None
        exit_price = None
        if hit_target and hit_sl:
            # Ambiguous same-candle hit — assume SL first (conservative)
            exit_reason, exit_price = "hit SL (same-candle ambiguity, conservative)", trade["sl_price"]
        elif hit_target:
            exit_reason, exit_price = "hit target", trade["target_price"]
        elif hit_sl:
            exit_reason, exit_price = "hit SL", trade["sl_price"]
        elif is_eod:
            exit_reason, exit_price = "EOD close", latest["close"]

        if exit_reason:
            pts = (exit_price - trade["entry_price"]) if trade["signal"] == "LONG" else (trade["entry_price"] - exit_price)
            outcome = "WIN" if pts > 0 else ("LOSS" if pts < 0 else "BREAKEVEN")

            trade["status"] = "CLOSED"
            trade["outcome"] = outcome
            trade["outcome_points"] = round(pts, 2)
            trade["exit_price"] = exit_price
            trade["exit_time"] = datetime.now().isoformat()
            trade["exit_reason"] = exit_reason

            record_outcome(symbol, trade["date"], outcome, points=round(pts, 2), exit_reason=exit_reason,
                            notes="auto-recorded by paper_trader.py (self-generated, not necessarily a real trade Saim took)")
            closed_this_call.append(trade)

    _write_all(entries)
    return closed_this_call


def summary():
    """Quick summary of all paper trades so far."""
    entries = _read_all()
    closed = [e for e in entries if e["status"] == "CLOSED"]
    open_count = sum(1 for e in entries if e["status"] == "OPEN")
    wins = sum(1 for e in closed if e["outcome"] == "WIN")
    total_pts = sum(e.get("outcome_points") or 0 for e in closed)
    return {
        "total_trades": len(entries),
        "open": open_count,
        "closed": len(closed),
        "wins": wins,
        "win_rate_pct": round(wins / len(closed) * 100, 1) if closed else None,
        "total_points": round(total_pts, 1),
    }


if __name__ == "__main__":
    print(json.dumps(summary(), indent=2))
