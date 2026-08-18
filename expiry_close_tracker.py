"""
expiry_close_tracker.py — pinning-release "gamma blast" in the final minutes
------------------------------------------------------------------------------
Saim's 18 Aug 2026 explanation, encoded as a specific trackable hypothesis:

Through the day, option SELLERS heavily write both calls and puts near
the ATM strike, creating a "pinning" force that suppresses natural price
movement (this is exactly what the 14:57 OI snapshot showed today —
massive dual-side writing at 24200-24250). But in the FINAL MINUTES
before close (last ~15, especially last 2-5 min), sellers start closing/
covering their positions as expiry finalizes. Once that pinning pressure
releases, the underlying momentum that was being suppressed all day can
release rapidly — a "gamma blast": a strike's premium can jump from ₹1-2
to ₹50-150+ in minutes, because Gamma is at its most extreme right at
expiry (see memory/greeks_knowledge.md Part 2).

HYPOTHESIS TO TRACK: on expiry days, is price movement in the final
~15 minutes before close SYSTEMATICALLY LARGER/FASTER than the rest of
the day's average per-minute movement? If the pinning-then-release
pattern is real, the last-minutes window should show a clear volatility
spike relative to the day's baseline — and this module measures exactly
that, plus identifies which specific strike's premium moved the most.
"""
import json
import os
from datetime import datetime, time as dtime

BASE = os.path.dirname(os.path.abspath(__file__))
EXPIRY_CLOSE_LOG_PATH = os.path.join(BASE, "memory", "expiry_close_events.jsonl")

PRE_CLOSE_WINDOW_START = dtime(15, 15)  # last ~15 min before 15:30 close
MARKET_CLOSE = dtime(15, 30)


def _read_all():
    if not os.path.exists(EXPIRY_CLOSE_LOG_PATH):
        return []
    with open(EXPIRY_CLOSE_LOG_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_all(entries):
    with open(EXPIRY_CLOSE_LOG_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def analyze_close_window(symbol, date_str, day_candles, option_rows_at_start=None, option_rows_at_close=None):
    """
    Call this once, right after market close on an expiry day, with the
    FULL day's 1-min candles (day_candles) and, if available, option
    chain snapshots taken near the start (15:15) and end (15:29) of the
    pre-close window.

    Measures: average per-minute price movement across the WHOLE day vs
    average per-minute movement in the LAST 15 minutes specifically —
    if the pinning-release pattern is real, the ratio should be
    meaningfully > 1. Also identifies, if option snapshots were
    provided, which strike's premium moved the most in % terms during
    the window (the "which strike blasted" answer Saim wants).
    """
    if not day_candles:
        return None

    def _minute_of(c):
        return datetime.fromisoformat(c["timestamp"]).time()

    whole_day_moves = [abs(day_candles[i]["close"] - day_candles[i - 1]["close"])
                        for i in range(1, len(day_candles))]
    avg_move_whole_day = sum(whole_day_moves) / len(whole_day_moves) if whole_day_moves else 0

    close_window = [c for c in day_candles if PRE_CLOSE_WINDOW_START <= _minute_of(c) <= MARKET_CLOSE]
    close_window_moves = [abs(close_window[i]["close"] - close_window[i - 1]["close"])
                           for i in range(1, len(close_window))] if len(close_window) > 1 else []
    avg_move_close_window = sum(close_window_moves) / len(close_window_moves) if close_window_moves else 0

    acceleration_ratio = round(avg_move_close_window / avg_move_whole_day, 2) if avg_move_whole_day else None

    biggest_strike_move = None
    if option_rows_at_start and option_rows_at_close:
        start_by_strike = {(r["strike"], side): r[side]["ltp"]
                            for r in option_rows_at_start for side in ("call", "put") if r.get(side)}
        best_pct = 0
        for r in option_rows_at_close:
            for side in ("call", "put"):
                if not r.get(side):
                    continue
                key = (r["strike"], side)
                start_ltp = start_by_strike.get(key)
                end_ltp = r[side]["ltp"]
                if start_ltp and start_ltp > 0 and end_ltp is not None:
                    pct_move = (end_ltp - start_ltp) / start_ltp * 100
                    if abs(pct_move) > abs(best_pct):
                        best_pct = pct_move
                        biggest_strike_move = {
                            "strike": r["strike"], "option_type": "CE" if side == "call" else "PE",
                            "start_ltp": start_ltp, "end_ltp": end_ltp, "pct_move": round(pct_move, 1),
                        }

    event = {
        "symbol": symbol, "date": date_str,
        "avg_move_whole_day": round(avg_move_whole_day, 2),
        "avg_move_close_window": round(avg_move_close_window, 2),
        "acceleration_ratio": acceleration_ratio,
        "biggest_strike_move": biggest_strike_move,
        "logged_at": datetime.now().isoformat(),
    }
    entries = _read_all()
    entries.append(event)
    _write_all(entries)
    return event


def review_acceleration_stats():
    """
    Reports whether the pinning-release pattern actually holds up across
    tracked expiry days: average acceleration ratio (how much faster the
    last 15 min moved vs the day's average), and how often a genuinely
    large strike-premium move (gamma blast) was observed.
    """
    entries = _read_all()
    if not entries:
        return {"total_expiry_days_tracked": 0, "message": "No expiry-day close events tracked yet."}

    ratios = [e["acceleration_ratio"] for e in entries if e.get("acceleration_ratio") is not None]
    big_blasts = [e for e in entries if e.get("biggest_strike_move") and abs(e["biggest_strike_move"]["pct_move"]) >= 50]

    return {
        "total_expiry_days_tracked": len(entries),
        "avg_acceleration_ratio": round(sum(ratios) / len(ratios), 2) if ratios else None,
        "days_with_50pct_plus_strike_move": len(big_blasts),
        "examples": big_blasts[-3:],  # most recent few, for a quick look
    }


if __name__ == "__main__":
    print(json.dumps(review_acceleration_stats(), indent=2))
