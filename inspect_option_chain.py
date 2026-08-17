"""
inspect_option_chain.py — one-time diagnostic
------------------------------------------------
Fetches the raw option chain payload and prints its structure so we can
see the ACTUAL field names Groww returns (docs alone weren't specific
enough to build a reliable parser blind). Run this once on the VPS,
share the output, and the real parser (groww_option_chain.py) gets
built to match exactly.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groww_api import fetch_option_chain

if __name__ == "__main__":
    underlying = sys.argv[1] if len(sys.argv) > 1 else "NIFTY"
    expiry = sys.argv[2] if len(sys.argv) > 2 else "2026-08-18"

    try:
        payload = fetch_option_chain(underlying, expiry)
        print(f"Type of payload: {type(payload)}")
        print(json.dumps(payload, indent=2)[:4000])
    except Exception as e:
        print(f"FAILED: {e}")
