"""
inspect_dhan_csv.py — diagnostic: print real column headers + sample rows
Run on VPS: python3 inspect_dhan_csv.py
Saves output to data/dhan_csv_inspection.json so it auto-syncs to GitHub
(fixed 22 Aug — previous version only printed to terminal, requiring
manual copy-paste, defeating the whole purpose of auto-sync).
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

matching_rows = []
for row in reader:
    if any("RELIANCE" in str(v).upper() for v in row.values() if v):
        matching_rows.append(row)
        if len(matching_rows) >= 5:
            break

result = {"headers": headers, "sample_reliance_rows": matching_rows}

os.makedirs("data", exist_ok=True)
with open("data/dhan_csv_inspection.json", "w") as f:
    json.dump(result, f, indent=2)

print("Saved to data/dhan_csv_inspection.json")
print("Headers:", headers)
