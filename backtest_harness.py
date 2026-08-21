"""
backtest_harness.py — systematic, repeatable backtest against a fixed dataset
------------------------------------------------------------------------------
21 Aug 2026: per Saim's instruction (#1 of 5 sequential items), building
the "biggest structural gap" identified 20 Aug — a standing harness that
automatically re-tests the CURRENT engine.py logic against a FIXED
historical dataset, producing a CONSISTENT report every time, so any
future strategy change can be compared apples-to-apples against a
known baseline (not ad-hoc, not re-explained from scratch each time).

Uses the REAL engine.score_setup() function — not a reimplementation —
so this genuinely reflects whatever the live strategy currently is.
Historical OI/FII/Greeks bias are NOT available for backtesting (only
live going-forward per STRATEGY_CATALOG.md) — runs with those as None,
same honest limitation as walkthrough.py.

Trade simulation mirrors paper_trader.py's real exit logic (trailing
stop) as closely as possible, using ONLY past-visible data at each
point (no lookahead — closes[:i+1] at candle i, never future candles).
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import score_setup

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(BASE, "data", "nifty_15d_5min.json")
HARNESS_RESULTS_LOG = os.path.join(BASE, "memory", "harness_run_log.jsonl")


def load_dataset(path=None):
    """Loads a fixed candle dataset (list of {timestamp, open, high, low, close, volume})."""
    path = path or DEFAULT_DATASET
    with open(path) as f:
        return json.load(f)


def run_harness(dataset_path=None, sl_points=15, target_points=25, min_history=25):
    """
    Walks through the dataset candle-by-candle, calling the REAL
    engine.score_setup() at each point using ONLY data visible up to
    that candle (no lookahead), simulates trade entry (edge-triggered,
    matching live logic) and exit (fixed SL/target — trailing-stop
    simulation is a known simplification here, since trailing needs
    tick-level granularity beyond what 5-min candles give cleanly).

    Returns a report dict: {total_trades, wins, losses, win_rate_pct,
    net_points, trades: [...]} — the CONSISTENT metrics to compare
    across harness runs.
    """
    candles = load_dataset(dataset_path)
    if len(candles) < min_history + 5:
        return {"error": f"dataset too small ({len(candles)} candles, need at least {min_history + 5})"}

    trades = []
    open_trade = None
    prev_signal = "NONE"

    for i in range(min_history, len(candles)):
        window = candles[:i + 1]  # only past-visible data, no lookahead
        closes = [c["close"] for c in window]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]

        # FIX (found via testing, 21 Aug): force-close any open trade at
        # end-of-day (matching live continuous_runner.py behavior) —
        # without this, trades were carrying across overnight gaps,
        # producing unrealistic exits and inflating trade-count
        # (caught: 3 trades/day vs documented ~1.5/day baseline)
        current_date = window[-1]["timestamp"][:10]
        is_last_candle_of_day = (i + 1 >= len(candles)) or (candles[i + 1]["timestamp"][:10] != current_date)

        result = score_setup(closes, highs, lows)
        signal = result["signal"]

        # Check open trade for exit first (SL/target hit, or EOD force-close)
        if open_trade:
            current_price = closes[-1]
            exited = False
            if open_trade["direction"] == "LONG":
                if current_price <= open_trade["sl_price"]:
                    open_trade["exit_price"] = open_trade["sl_price"]
                    open_trade["outcome"] = "LOSS"
                    open_trade["outcome_points"] = -sl_points
                    exited = True
                elif current_price >= open_trade["target_price"]:
                    open_trade["exit_price"] = open_trade["target_price"]
                    open_trade["outcome"] = "WIN"
                    open_trade["outcome_points"] = target_points
                    exited = True
            else:  # SHORT
                if current_price >= open_trade["sl_price"]:
                    open_trade["exit_price"] = open_trade["sl_price"]
                    open_trade["outcome"] = "LOSS"
                    open_trade["outcome_points"] = -sl_points
                    exited = True
                elif current_price <= open_trade["target_price"]:
                    open_trade["exit_price"] = open_trade["target_price"]
                    open_trade["outcome"] = "WIN"
                    open_trade["outcome_points"] = target_points
                    exited = True

            if not exited and is_last_candle_of_day:
                # Force-close at EOD, matching live behavior — outcome
                # based on actual close-vs-entry, not SL/target
                open_trade["exit_price"] = current_price
                raw_points = (current_price - open_trade["entry_price"]) if open_trade["direction"] == "LONG" \
                    else (open_trade["entry_price"] - current_price)
                open_trade["outcome"] = "WIN" if raw_points > 0 else ("LOSS" if raw_points < 0 else "FLAT")
                open_trade["outcome_points"] = round(raw_points, 1)
                open_trade["exit_reason"] = "EOD_FORCE_CLOSE"
                exited = True

            if exited:
                trades.append(open_trade)
                open_trade = None

        # Edge-triggered entry (matches live continuous_runner.py logic)
        # — do NOT open new trades on the last candle of the day (no
        # time left for the trade to develop before forced EOD close)
        is_fresh_signal = signal != "NONE" and signal != prev_signal
        prev_signal = signal

        if is_fresh_signal and open_trade is None and not is_last_candle_of_day:
            entry_price = closes[-1]
            if signal == "LONG":
                sl_price = entry_price - sl_points
                target_price = entry_price + target_points
            else:
                sl_price = entry_price + sl_points
                target_price = entry_price - target_points
            open_trade = {
                "direction": signal, "entry_price": entry_price, "entry_time": window[-1]["timestamp"],
                "sl_price": sl_price, "target_price": target_price, "score": result["score"],
            }

    total = len(trades)
    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    net_points = sum(t["outcome_points"] for t in trades)

    return {
        "total_trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate_pct": round(wins / total * 100, 1) if total else None,
        "net_points": net_points,
        "trades": trades,
        "dataset_used": dataset_path or DEFAULT_DATASET,
        "candles_processed": len(candles),
    }


def log_harness_run(report, label=""):
    """Saves a harness run's summary (not full trade list) permanently,
    for before/after comparison across strategy changes."""
    entry = {
        "timestamp": datetime.now().isoformat(), "label": label,
        "total_trades": report.get("total_trades"), "win_rate_pct": report.get("win_rate_pct"),
        "net_points": report.get("net_points"), "dataset_used": report.get("dataset_used"),
    }
    with open(HARNESS_RESULTS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


if __name__ == "__main__":
    report = run_harness()
    print(json.dumps({k: v for k, v in report.items() if k != "trades"}, indent=2))
    log_harness_run(report, label="manual run")
