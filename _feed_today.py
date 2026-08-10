import sys, json
sys.path.insert(0, '.')
from daily_store import append_intraday_candles

# Today's + last trading day's candles (from live GrowwMCP fetch, 10 Aug 2026 2:47 PM)
candles = []
