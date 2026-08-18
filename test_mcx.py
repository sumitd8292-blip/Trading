"""
test_mcx.py — quick test: does our option-chain code work on MCX commodities?
------------------------------------------------------------------------------
Saim's 18 Aug idea: MCX commodity market trades much later than NSE
(often till 11:30 PM), so it's a live 24x7-ish testbed we can use to
verify our code works RIGHT NOW instead of waiting for tomorrow's NSE
open. Run this directly: python3 test_mcx.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groww_api import fetch_option_chain
from groww_option_chain import parse_option_chain, compute_gamma_exposure, compute_volume_profile

for underlying, expiry, exchange in [
    ("CRUDEOILM", "2026-08-19", "MCX"),
    ("CRUDEOILM", "2026-09-17", "MCX"),
    ("GOLDM", "2026-08-28", "MCX"),
    ("SILVERM", "2026-08-24", "MCX"),
]:
    print(f"\n--- Trying {underlying} expiry={expiry} exchange={exchange} ---")
    try:
        payload = fetch_option_chain(underlying, expiry, exchange=exchange)
        rows = parse_option_chain(payload)
        print(f"Strikes parsed: {len(rows)}")
        if rows:
            spot = payload.get("underlying_ltp")
            print(f"Spot: {spot}")
            print(f"Sample row: {rows[0]}")
            gex = compute_gamma_exposure(rows, spot)
            print(f"GEX: {gex}")
            vol = compute_volume_profile(rows, spot)
            print(f"Volume profile: {vol}")
    except Exception as e:
        print(f"FAILED: {e}")
