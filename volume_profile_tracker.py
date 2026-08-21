"""
volume_profile_tracker.py — daily POC + rolling contract-period POC
------------------------------------------------------------------------------
21 Aug 2026: per Saim's design decision — track Volume Profile / POC at
TWO levels:
1. DAILY (resets every day) — the actionable, primary level for
   intraday decisions
2. ROLLING CONTRACT-PERIOD (accumulates across days, resets on monthly
   futures contract rollover) — for bigger support/resistance zones,
   built from the 15-day-in-one-contract example that showed genuine
   POC support behavior (12-14 Aug bounces, 17 Aug breakdown)

Saim's explicit caution: NIFTY and BANKNIFTY FUTURES are both
MONTHLY-only contracts (confirmed 18-19 Aug — no weekly futures exist
for either), so both use the SAME rollover-detection logic here. This
is separate from options' weekly-vs-monthly expiry distinction, which
doesn't affect futures volume profile.

Uses volume_profile.py's compute_volume_profile() on FUTURES candle
data (real volume, already fetched for the VSA layer — no new API
calls needed).
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DAILY_POC_LOG_PATH = os.path.join(BASE, "memory", "daily_poc_log.jsonl")
ROLLING_STATE_PATH = os.path.join(BASE, "memory", "rolling_poc_state.json")


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def _append_jsonl(path, entry):
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def compute_and_store_daily_poc(symbol, date_str, day_futures_candles, price_bucket_size=25):
    """
    Call once at end-of-day with today's futures candles (with volume).
    Computes and permanently stores today's Volume Profile POC/Value
    Area — the daily, actionable level.
    """
    from volume_profile import compute_volume_profile
    profile = compute_volume_profile(day_futures_candles, price_bucket_size)
    if not profile:
        return None

    entry = {
        "symbol": symbol, "date": date_str,
        "poc_price": profile["poc_price"], "poc_volume": profile["poc_volume"],
        "value_area_high": profile["value_area_high"], "value_area_low": profile["value_area_low"],
        "total_volume": profile["total_volume"],
        "logged_at": datetime.now().isoformat(),
    }
    _append_jsonl(DAILY_POC_LOG_PATH, entry)
    return entry


def _load_rolling_state():
    if not os.path.exists(ROLLING_STATE_PATH):
        return {}
    with open(ROLLING_STATE_PATH) as f:
        return json.load(f)


def _save_rolling_state(state):
    with open(ROLLING_STATE_PATH, "w") as f:
        json.dump(state, f)


def update_rolling_contract_poc(symbol, date_str, day_futures_candles, current_contract_expiry, price_bucket_size=25):
    """
    Call once at end-of-day: accumulates today's futures volume into the
    ROLLING profile for the current monthly contract period. Detects
    contract rollover (if current_contract_expiry differs from what was
    last stored for this symbol) and RESETS the rolling accumulation
    when a new contract period begins — per Saim's explicit requirement
    not to mix volume across different futures contracts.

    current_contract_expiry: the monthly expiry date string (YYYY-MM-DD)
    of the CURRENTLY active futures contract (from get_monthly_expiry()) —
    used purely to detect "did we roll into a new contract since
    yesterday", not as a cutoff for the data itself.
    """
    state = _load_rolling_state()
    symbol_state = state.get(symbol, {})

    if symbol_state.get("contract_expiry") != current_contract_expiry:
        # New contract period — reset the rolling accumulation
        symbol_state = {
            "contract_expiry": current_contract_expiry,
            "start_date": date_str,
            "accumulated_candles": [],
        }

    symbol_state["accumulated_candles"].extend(day_futures_candles)
    symbol_state["last_updated_date"] = date_str

    from volume_profile import compute_volume_profile
    profile = compute_volume_profile(symbol_state["accumulated_candles"], price_bucket_size)

    state[symbol] = symbol_state
    _save_rolling_state(state)

    if not profile:
        return None

    return {
        "symbol": symbol, "contract_expiry": current_contract_expiry,
        "period_start": symbol_state["start_date"], "period_end": date_str,
        "days_accumulated": len(set(c["timestamp"][:10] for c in symbol_state["accumulated_candles"])),
        "poc_price": profile["poc_price"], "poc_volume": profile["poc_volume"],
        "value_area_high": profile["value_area_high"], "value_area_low": profile["value_area_low"],
    }


def get_latest_daily_poc(symbol):
    """Returns the most recently stored daily POC entry for symbol, or None."""
    entries = [e for e in _read_jsonl(DAILY_POC_LOG_PATH) if e["symbol"] == symbol]
    if not entries:
        return None
    entries.sort(key=lambda e: e["date"])
    return entries[-1]


def get_current_rolling_poc(symbol):
    """Returns the current rolling contract-period POC state for symbol, or None."""
    state = _load_rolling_state()
    symbol_state = state.get(symbol)
    if not symbol_state or not symbol_state.get("accumulated_candles"):
        return None
    from volume_profile import compute_volume_profile
    profile = compute_volume_profile(symbol_state["accumulated_candles"])
    if not profile:
        return None
    return {
        "symbol": symbol, "contract_expiry": symbol_state["contract_expiry"],
        "period_start": symbol_state["start_date"],
        "poc_price": profile["poc_price"], "value_area_high": profile["value_area_high"],
        "value_area_low": profile["value_area_low"],
    }
