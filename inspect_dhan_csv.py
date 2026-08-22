"""
inspect_dhan_csv.py — diagnostic: print real column headers + sample rows
Run on VPS: python3 inspect_dhan_csv.py
Saves output to data/dhan_csv_inspection.json so it auto-syncs to GitHub.
"""
import sys
import os
import csv
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dhan_api import download_instrument_list

content = download_instrument_list()
reader = csv.DictReader(content.splitlines())
headers = reader.fieldnames

# FIX (22 Aug): previous version's first-5-matches were all BSE OPTIONS
# rows, not plain equity — need to specifically find EQUITY-type rows to
# see the correct SEM_SEGMENT/SEM_EXCH_INSTRUMENT_TYPE values for stocks
equity_rows = []
all_segment_values = set()
all_instrument_type_values = set()
for row in reader:
    all_segment_values.add(row.get("SEM_SEGMENT"))
    all_instrument_type_values.add(row.get("SEM_EXCH_INSTRUMENT_TYPE"))
    if (row.get("SEM_EXM_EXCH_ID") == "NSE" and "RELIANCE" in str(row.get("SEM_TRADING_SYMBOL", "")).upper()
            and row.get("SEM_INSTRUMENT_NAME") not in ("OPTSTK", "FUTSTK")):
        equity_rows.append(row)
        if len(equity_rows) >= 5:
            break

result = {
    "headers": headers,
    "equity_reliance_rows": equity_rows,
    "all_segment_values_seen": sorted(v for v in all_segment_values if v),
    "all_instrument_type_values_seen": sorted(v for v in all_instrument_type_values if v),
}

os.makedirs("data", exist_ok=True)
with open("data/dhan_csv_inspection.json", "w") as f:
    json.dump(result, f, indent=2)

print("Saved to data/dhan_csv_inspection.json")
