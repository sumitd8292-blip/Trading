"""
try_gift_nifty.py — experimental probe
------------------------------------------
GIFT NIFTY trades on NSE IX (GIFT City) — a DIFFERENT exchange from the
regular NSE/BSE that Groww's trading API documents. This is uncertain:
Groww's own website displays GIFT Nifty as an info widget, but the
TRADING API's documented `exchange` parameter only lists NSE and BSE.
NSE IX may require a separate IFSC account (mostly for NRIs/FPIs), not
available through a standard domestic Groww account.

This script just TRIES a few plausible exchange/symbol combinations and
reports what actually happens — don't assume any of these are correct,
we're probing blind since this isn't documented.
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groww_api import fetch_candles

attempts = [
    {"symbol": "NIFTY", "exchange": "NSE_IX", "segment": "CASH"},
    {"symbol": "NIFTY", "exchange": "NSEIX", "segment": "CASH"},
    {"symbol": "GIFTNIFTY", "exchange": "NSE", "segment": "CASH"},
    {"symbol": "NIFTY", "exchange": "NSE", "segment": "IX"},
]

now = datetime.now()
start = (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
end = now.strftime("%Y-%m-%d %H:%M:%S")

for a in attempts:
    print(f"\n--- Trying exchange={a['exchange']}, segment={a['segment']}, symbol={a['symbol']} ---")
    try:
        candles = fetch_candles(a["symbol"], start, end, exchange=a["exchange"],
                                 segment=a["segment"], interval_minutes=5)
        print(f"SUCCESS: {len(candles)} candles. First: {candles[0] if candles else None}")
    except Exception as e:
        print(f"FAILED: {e}")
