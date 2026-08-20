"""
dhan_diagnostic_test.py — quick standalone test for Dhan API, once Saim has credentials
------------------------------------------------------------------------------
Run: python3 dhan_diagnostic_test.py
Needs DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN set in environment first.
Completely isolated from continuous_runner.py / live trading.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dhan_api import fetch_quote_with_depth, fetch_expiry_list, fetch_option_chain

# Common Dhan security_ids for NIFTY/BANKNIFTY indices (from public references —
# VERIFY against download_instrument_list() once credentials are available,
# these are commonly cited but should be double-checked, not blindly trusted)
NIFTY_INDEX_ID = "13"
BANKNIFTY_INDEX_ID = "25"

if __name__ == "__main__":
    print("=== Testing Dhan API ===\n")

    print("1. Fetching NIFTY option chain expiry list...")
    try:
        expiries = fetch_expiry_list(NIFTY_INDEX_ID, "IDX_I")
        print("SUCCESS:", expiries)
    except Exception as e:
        print("FAILED:", e)

    print("\n2. Fetching NIFTY index quote...")
    try:
        quote = fetch_quote_with_depth(NIFTY_INDEX_ID, exchange_segment="IDX_I")
        print("SUCCESS:", quote)
    except Exception as e:
        print("FAILED:", e)
