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
# (per the lesson learned from Groww's symbol-guessing issues earlier)
TOP5_STOCK_NAMES = ["HDFC BANK", "ICICI BANK", "RELIANCE INDUSTRIES", "INFOSYS", "BHARTI AIRTEL"]

DAYS_BACK = 60


def find_stock_security_id(stock_name):
    """Looks up a stock's NSE equity security_id by name from Dhan's
    instrument master list — avoids guessing IDs."""
    csv_content = download_instrument_list()
    reader = csv.DictReader(csv_content.splitlines())
    for row in reader:
        if (row.get("SEM_EXM_EXCH_ID") == "NSE" and
                row.get("SEM_SEGMENT") == "E" and
                stock_name.upper() in (row.get("SEM_TRADING_SYMBOL") or "").upper()):
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
    for stock_name in TOP5_STOCK_NAMES:
        try:
            sec_id = find_stock_security_id(stock_name)
            if not sec_id:
                print(f"  Could not find security_id for {stock_name}")
                results[stock_name] = {"error": "security_id not found"}
                continue
            print(f"  {stock_name} -> security_id={sec_id}, fetching...")
            data = fetch_historical_data(
                sec_id, "NSE_EQ", "EQUITY",
                f"{from_date} 09:00:00", f"{to_date} 15:30:00", interval="1"
            )
            results[stock_name] = data
            print(f"  SUCCESS — got data for {stock_name}")
        except Exception as e:
            results[stock_name] = {"error": str(e)}
            print(f"  FAILED for {stock_name}: {e}")

    os.makedirs("data", exist_ok=True)
    with open("data/opening_research.json", "w") as f:
        json.dump(results, f)
    print("\nSaved to data/opening_research.json")


if __name__ == "__main__":
    run()
