"""
pull_opening_data.py — one-off research script (22 Aug 2026)
------------------------------------------------------------------------------
Run manually on VPS: python3 pull_opening_data.py
Needs DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN in environment.

Pulls multi-day 1-min historical data for NIFTY, BANKNIFTY, SENSEX
(index-level) — Saim's research request to see opening-minute momentum
across as many days as available. Saves to data/opening_research.json,
which auto_sync_data.py will push to GitHub (or run it manually right
after for immediate sync).
"""
import os
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dhan_api import fetch_historical_data

# Index security IDs (confirmed this session via Dhan search)
INSTRUMENTS = {
    "NIFTY": {"security_id": "13", "exchange_segment": "IDX_I"},
    "BANKNIFTY": {"security_id": "25", "exchange_segment": "IDX_I"},
    "SENSEX": {"security_id": "51", "exchange_segment": "IDX_I"},  # BSE Sensex — verify if this fails
}

DAYS_BACK = 60  # widened 22 Aug per Saim's request — need enough history to
                 # see BOTH up-opening and down-opening periods, not just
                 # the recent downtrend stretch (Dhan's intraday API has a
                 # ~90-day max span limit per interval, per earlier research)


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

    os.makedirs("data", exist_ok=True)
    with open("data/opening_research.json", "w") as f:
        json.dump(results, f)
    print("\nSaved to data/opening_research.json")


if __name__ == "__main__":
    run()
