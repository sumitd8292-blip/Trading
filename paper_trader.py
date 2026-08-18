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
from collections import defaultdict

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


def open_paper_trade(symbol, date_str, signal, entry_price, sl_points, target_points, layer_status, score, reasons,
                      trail_trigger_points=15, trail_distance_points=15, strategy_type=None,
                      option_snapshot=None, vix_level=None):
    """
    Records a new self-generated paper trade using a TRAILING STOP exit
    (changed 17 Aug 2026 — backtest on 15 days of real NIFTY data showed
    trailing beats fixed SL/target: -50 pts vs +17.8 pts net over 25
    trades). No fixed target — SL starts trailing once price moves
    `trail_trigger_points` in favor, staying `trail_distance_points`
    behind the best price reached. Rides the trend until trailing SL
    is hit or EOD forces a close.

    strategy_type: which entry logic fired this trade — "reversal"
    (RSI-based) or "trend_continuation" — tagged so learning_loop can
    later compare which wins more often, per Saim's 18 Aug request to
    track "which strategy is better in which regime".

    option_snapshot: optional {strike, option_type, delta, theta, ltp}
    from suggest_strike() at entry time — if provided, enables REAL
    premium P&L estimation (Delta+Theta based) alongside the raw index-
    point P&L, addressing the finding that index-point profit doesn't
    always mean real rupee profit once Theta decay is accounted for.

    vix_level: India VIX reading at entry time, if available — tagged
    so learning_loop can later check whether signal quality degrades in
    high-VIX (high uncertainty) conditions.

    One open trade per (symbol, date) at a time — if one's already open
    for today, skip (avoids overlapping paper positions from repeated
    signal checks).
    """
    entries = _read_all()
    already_open = any(e["symbol"] == symbol and e["date"] == date_str and e["status"] == "OPEN" for e in entries)
    if already_open:
        return None

    initial_sl_price = entry_price - sl_points if signal == "LONG" else entry_price + sl_points

    trade = {
        "symbol": symbol,
        "date": date_str,
        "signal": signal,
        "strategy_type": strategy_type,
        "entry_price": entry_price,
        "entry_time": datetime.now().isoformat(),
        "entry_hour": datetime.now().hour,
        "current_sl_price": round(initial_sl_price, 2),
        "best_price": entry_price,
        "sl_points": sl_points,
        "trail_trigger_points": trail_trigger_points,
        "trail_distance_points": trail_distance_points,
        "layer_status": layer_status,
        "score": score,
        "reasons": reasons,
        "option_snapshot": option_snapshot,
        "vix_level": vix_level,
        "status": "OPEN",
        "outcome": None,
        "outcome_points": None,
        "exit_price": None,
        "exit_time": None,
        "estimated_premium_pnl": None,
    }
    entries.append(trade)
    _write_all(entries)
    return trade


def check_open_trades(symbol, latest_candles, is_eod=False):
    """
    Checks all OPEN paper trades for `symbol` against the latest candle
    data (list of {high, low, close, timestamp}). Updates the trailing
    SL as price moves favorably, closes any trade whose trailing SL is
    hit, or force-closes at EOD if is_eod=True. Automatically records
    outcomes via learning_loop.record_outcome().

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

        h, l = latest["high"], latest["low"]
        direction = trade["signal"]
        entry = trade["entry_price"]

        # Update trailing SL based on best price reached so far
        if direction == "LONG":
            trade["best_price"] = max(trade["best_price"], h)
            if trade["best_price"] - entry >= trade["trail_trigger_points"]:
                new_sl = trade["best_price"] - trade["trail_distance_points"]
                trade["current_sl_price"] = max(trade["current_sl_price"], new_sl)
            hit_sl = l <= trade["current_sl_price"]
        else:
            trade["best_price"] = min(trade["best_price"], l)
            if entry - trade["best_price"] >= trade["trail_trigger_points"]:
                new_sl = trade["best_price"] + trade["trail_distance_points"]
                trade["current_sl_price"] = min(trade["current_sl_price"], new_sl)
            hit_sl = h >= trade["current_sl_price"]

        exit_reason = exit_price = None
        if hit_sl:
            exit_reason, exit_price = "trailing SL hit", trade["current_sl_price"]
        elif is_eod:
            exit_reason, exit_price = "EOD close", latest["close"]

        if exit_reason:
            pts = (exit_price - entry) if direction == "LONG" else (entry - exit_price)
            outcome = "WIN" if pts > 0 else ("LOSS" if pts < 0 else "BREAKEVEN")

            trade["status"] = "CLOSED"
            trade["outcome"] = outcome
            trade["outcome_points"] = round(pts, 2)
            trade["exit_price"] = exit_price
            trade["exit_time"] = datetime.now().isoformat()
            trade["exit_reason"] = exit_reason

            # Real premium P&L estimate (Delta + Theta), addressing the
            # 17 Aug finding that index-point profit doesn't always mean
            # real rupee profit — Theta decay can flip a winning index
            # trade into a losing premium trade. Only computed if an
            # option snapshot was captured at entry.
            if trade.get("option_snapshot"):
                snap = trade["option_snapshot"]
                delta = abs(snap.get("delta") or 0)
                theta = snap.get("theta")  # negative, points/day decay for the BUYER
                hold_minutes = (datetime.fromisoformat(trade["exit_time"]) -
                                 datetime.fromisoformat(trade["entry_time"])).total_seconds() / 60
                premium_move_from_delta = pts * delta
                theta_decay = (theta * (hold_minutes / 375)) if theta is not None else 0  # 375 = trading minutes/day
                trade["estimated_premium_pnl"] = round(premium_move_from_delta + theta_decay, 2)

            record_outcome(symbol, trade["date"], outcome, points=round(pts, 2), exit_reason=exit_reason,
                            notes="auto-recorded by paper_trader.py (self-generated, not necessarily a real trade Saim took; trailing-stop exit)")
            closed_this_call.append(trade)

    _write_all(entries)
    return closed_this_call


def review_by_time_and_strategy():
    """
    Breaks down closed paper trades by ENTRY HOUR (does the agent's
    signal quality vary across the trading day — e.g. more fakeouts in
    the first hour, more reliability in the last hour?) and by
    STRATEGY_TYPE (reversal vs trend_continuation — which wins more
    often, and in which time-of-day?). Addresses Saim's 18 Aug request
    to learn "which approach is better, where, and when" rather than
    treating all trades as one undifferentiated pool.
    """
    entries = [e for e in _read_all() if e["status"] == "CLOSED"]
    if not entries:
        return {"total": 0, "message": "No closed paper trades yet."}

    by_hour = defaultdict(lambda: {"count": 0, "wins": 0, "points": 0})
    by_strategy = defaultdict(lambda: {"count": 0, "wins": 0, "points": 0})
    by_strategy_and_hour = defaultdict(lambda: defaultdict(lambda: {"count": 0, "wins": 0}))

    for e in entries:
        hour = e.get("entry_hour")
        strat = e.get("strategy_type") or "unknown"
        pts = e.get("outcome_points") or 0
        is_win = e.get("outcome") == "WIN"

        if hour is not None:
            by_hour[hour]["count"] += 1
            by_hour[hour]["points"] += pts
            if is_win:
                by_hour[hour]["wins"] += 1

        by_strategy[strat]["count"] += 1
        by_strategy[strat]["points"] += pts
        if is_win:
            by_strategy[strat]["wins"] += 1

        if hour is not None:
            by_strategy_and_hour[strat][hour]["count"] += 1
            if is_win:
                by_strategy_and_hour[strat][hour]["wins"] += 1

    def _finalize(d):
        out = {}
        for k, v in d.items():
            wr = round(v["wins"] / v["count"] * 100, 1) if v["count"] else 0
            out[k] = {"trades": v["count"], "win_rate_pct": wr, "total_points": round(v.get("points", 0), 1)}
        return out

    return {
        "by_entry_hour": _finalize(by_hour),
        "by_strategy_type": _finalize(by_strategy),
        "by_strategy_and_hour": {s: _finalize(hrs) for s, hrs in by_strategy_and_hour.items()},
    }


def review_premium_pnl():
    """
    Reports accumulated REAL PREMIUM P&L (Delta+Theta based, from
    option_snapshot at entry) vs the raw INDEX-POINT P&L — addressing
    the 17 Aug finding that these can diverge significantly (a
    profitable index-point strategy can still lose real money to Theta
    decay). Only includes trades where an option snapshot was captured.
    """
    entries = [e for e in _read_all() if e["status"] == "CLOSED" and e.get("estimated_premium_pnl") is not None]
    if not entries:
        return {"total": 0, "message": "No closed paper trades with option-premium data yet."}

    index_pts_total = sum(e.get("outcome_points") or 0 for e in entries)
    premium_pts_total = sum(e["estimated_premium_pnl"] for e in entries)
    wins_by_index = sum(1 for e in entries if (e.get("outcome_points") or 0) > 0)
    wins_by_premium = sum(1 for e in entries if e["estimated_premium_pnl"] > 0)

    return {
        "total_trades": len(entries),
        "index_points_total": round(index_pts_total, 1),
        "estimated_premium_points_total": round(premium_pts_total, 1),
        "wins_by_index_points": wins_by_index,
        "wins_by_premium_pnl": wins_by_premium,
        "note": "premium P&L uses Delta (linear approx) + Theta decay over actual hold time — ignores Gamma, so treat as directional not precise",
    }


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
