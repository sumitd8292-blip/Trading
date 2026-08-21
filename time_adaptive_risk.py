"""
time_adaptive_risk.py — SL/target scaled to time-of-day volatility
------------------------------------------------------------------------------
21 Aug 2026: Saim's observation, TESTED against real 4-day 1-min NIFTY
data (10, 11, 12, 21 Aug — only days with continuous logging available):
average per-minute price movement is NOT uniform across the day.

  MORNING   (9:15-11:00): avg 4.09 pts/min  (highest, consistent all 4 days)
  MIDDAY    (11:00-14:00): avg 2.54 pts/min (lowest, consistent all 4 days)
  AFTERNOON (14:00-15:15): avg 3.16 pts/min (middling)

A FIXED 15pt SL/25pt target (calibrated against the whole-day average)
is systematically mismatched: too tight during high-volatility morning
(gets stopped by normal noise) and effectively too wide/slow during
low-volatility midday (price just drifts near entry without decisively
reaching either SL or target) — exactly the "trades just show losses"
symptom Saim flagged.

HONEST LIMITATION: multipliers are calibrated from only 4 days of data.
Should be RECALIBRATED periodically as more days accumulate (now
straightforward since auto_sync_data.py pushes live data to GitHub
daily) — treat these as a reasonable starting adjustment, not a
permanently fixed constant.
"""
from datetime import time as dtime

# Ratio of this window's avg volatility vs the overall 3-window average (3.26 pts/min)
TIME_VOLATILITY_MULTIPLIERS = [
    (dtime(9, 15), dtime(11, 0), 1.25),   # morning — wider SL/target (more room needed)
    (dtime(11, 0), dtime(14, 0), 0.78),   # midday — tighter SL/target (less movement available)
    (dtime(14, 0), dtime(15, 15), 0.97),  # afternoon — close to baseline
]
DEFAULT_MULTIPLIER = 1.0  # outside the three windows above (e.g. extended session)


def get_time_volatility_multiplier(current_time):
    """Returns the calibrated multiplier for the given time-of-day."""
    for start, end, mult in TIME_VOLATILITY_MULTIPLIERS:
        if start <= current_time < end:
            return mult
    return DEFAULT_MULTIPLIER


def get_time_adjusted_sl_target(base_sl_points, base_target_points, current_time):
    """
    Scales both SL and target by the time-of-day multiplier — preserves
    the underlying reward:risk RATIO (still ~1.67:1 if base was 15/25)
    while sizing the absolute point-distances to match how much the
    market actually tends to move in that specific window.
    """
    mult = get_time_volatility_multiplier(current_time)
    return {
        "sl_points": round(base_sl_points * mult, 1),
        "target_points": round(base_target_points * mult, 1),
        "multiplier_used": mult,
        "time_window": _window_label(current_time),
    }


def _window_label(current_time):
    for start, end, mult in TIME_VOLATILITY_MULTIPLIERS:
        if start <= current_time < end:
            return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
    return "outside-calibrated-windows"
