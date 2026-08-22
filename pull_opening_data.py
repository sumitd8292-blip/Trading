"""
pull_opening_data.py — one-off research script (22 Aug 2026)
------------------------------------------------------------------------------
Run manually on VPS: python3 pull_opening_data.py
Needs DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN in environment.

Pulls multi-day 1-min historical data for NIFTY, BANKNIFTY, SENSEX
(index-level), PLUS the top-5 NIFTY-weighted stocks (Saim's 22 Aug
request to extend the opening-momentum hierarchy analysis to
individual stocks — larger effective sample size, real volume directly
available unlike index proxying). Saves to data/opening_research.json,
auto_sync_data.py pushes it to GitHub.
"""
import os
import sys
import json
import csv
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dhan_api import fetch_historical_data, download_instrument_list

# Index security IDs (confirmed this session via Dhan search)
INSTRUMENTS = {
    "NIFTY": {"security_id": "13", "exchange_segment": "IDX_I"},
    "BANKNIFTY": {"security_id": "25", "exchange_segment": "IDX_I"},
    "SENSEX": {"security_id": "51", "exchange_segment": "IDX_I"},
}

# Top-5 NIFTY-weighted stocks (confirmed 22 Aug via web search) — looked
# up dynamically by name from Dhan's instrument list, not hardcoded IDs
# (per the lesson learned from Groww's symbol-guessing issues earlier).
# FIXED 22 Aug: use exact NSE-EQUITY SEM_TRADING_SYMBOL (short form, e.g.
# "RELIANCE" not "RELIANCE INDUSTRIES") — verified via inspect_dhan_csv.py
# against real CSV data (RELIANCE: SEM_EXM_EXCH_ID=NSE, SEM_SEGMENT=E,
# SEM_INSTRUMENT_NAME=EQUITY, security_id=2885).
TOP5_STOCKS = {
    "HDFC BANK": "HDFCBANK", "ICICI BANK": "ICICIBANK", "RELIANCE INDUSTRIES": "RELIANCE",
    "INFOSYS": "INFY", "BHARTI AIRTEL": "BHARTIARTL",
}

DAYS_BACK = 60


def find_stock_security_id(trading_symbol):
    """
    Looks up a stock's NSE EQUITY security_id by EXACT trading_symbol
    match (e.g. "RELIANCE", "INFY", "HDFCBANK") — NOT a substring search
    against the full company name, which was the earlier bug (searching
    for "RELIANCE INDUSTRIES" could never match Dhan's short trading
    symbol "RELIANCE"). Filters explicitly to NSE + Equity segment
    (SEM_EXM_EXCH_ID="NSE", SEM_SEGMENT="E", SEM_INSTRUMENT_NAME="EQUITY")
    — confirmed exact field values via inspect_dhan_csv.py, 22 Aug.
    """
    csv_content = download_instrument_list()
    reader = csv.DictReader(csv_content.splitlines())
    for row in reader:
        if (row.get("SEM_EXM_EXCH_ID") == "NSE" and
                row.get("SEM_SEGMENT") == "E" and
                row.get("SEM_INSTRUMENT_NAME") == "EQUITY" and
                row.get("SEM_TRADING_SYMBOL") == trading_symbol):
            return row.get("SEM_SMST_SECURITY_ID")
    return None


def run():
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    results = {}
    for name, info in INSTRUMENTS.items():
        print(f"Fetching {name}...")
        try:
            data = fetch_historical_data(
                info["security_id"], info["exchange_segment"], "INDEX",
                f"{from_date} 09:00:00", f"{to_date} 15:30:00", interval="1"
            )
            results[name] = data
            print(f"  SUCCESS — got data for {name}")
        except Exception as e:
            results[name] = {"error": str(e)}
            print(f"  FAILED for {name}: {e}")

    print("\nLooking up top-5 NIFTY stocks' security IDs...")
    for display_name, trading_symbol in TOP5_STOCKS.items():
        try:
            sec_id = find_stock_security_id(trading_symbol)
            if not sec_id:
                print(f"  Could not find security_id for {display_name} ({trading_symbol})")
                results[display_name] = {"error": "security_id not found"}
                continue
            print(f"  {display_name} ({trading_symbol}) -> security_id={sec_id}, fetching...")
            data = fetch_historical_data(
                sec_id, "NSE_EQ", "EQUITY",
                f"{from_date} 09:00:00", f"{to_date} 15:30:00", interval="1"
            )
            results[display_name] = data
            print(f"  SUCCESS — got data for {display_name}")
        except Exception as e:
            results[display_name] = {"error": str(e)}
            print(f"  FAILED for {display_name}: {e}")

    os.makedirs("data", exist_ok=True)
    with open("data/opening_research.json", "w") as f:
        json.dump(results, f)
    print("\nSaved to data/opening_research.json")


if __name__ == "__main__":
    run()
