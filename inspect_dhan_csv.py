"""
inspect_dhan_csv.py — diagnostic: print real column headers + sample rows
Run on VPS: python3 inspect_dhan_csv.py
"""
import sys
import os
import csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dhan_api import download_instrument_list

content = download_instrument_list()
reader = csv.DictReader(content.splitlines())
print("COLUMN HEADERS:", reader.fieldnames)
print()
count = 0
for row in reader:
    if "RELIANCE" in str(row.get(reader.fieldnames[0], "")).upper() or any("RELIANCE" in str(v).upper() for v in row.values()):
        print(row)
        count += 1
        if count >= 3:
            break
