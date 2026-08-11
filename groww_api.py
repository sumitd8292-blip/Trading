"""
Groww Direct API — Live Data Fetcher
-------------------------------------
SEPARATE from GrowwMCP. GrowwMCP only works inside Claude chat sessions.
This module uses Groww's own paid Trading/Data API (₹499+GST/month
subscription, api.groww.in) so live data fetching can eventually run from
GitHub Actions without a Claude session open.

*** IMPORTANT LIMITATION (found 11 Aug 2026) ***
Groww's access token EXPIRES DAILY at 6 AM IST. This means the token Saim
provides needs to be regenerated and re-uploaded to GitHub Secrets every
day before it can be used — full unattended 24x7 automation is NOT
possible with this token type alone. Options going forward:
  1. Saim manually regenerates + sends the token each morning (Claude
     updates the GitHub secret each time) — simple but still needs a
     human step daily.
  2. Investigate whether Groww offers a longer-lived API key + secret
     pair for programmatic (non-interactive) daily refresh — check
     Groww's API docs "User" / "Annexures" sections for a token-refresh
     endpoint using GROWW_API_SECRET.
Not yet resolved — flagging here for the next work session.

ENDPOINT (per Groww's documented cURL API, groww.in/trade-api/docs/curl):
  GET https://api.groww.in/v1/historical/candle/range
    ?exchange=NSE&segment=CASH&trading_symbol=NIFTY
    &start_time=YYYY-MM-DD HH:MM:SS&end_time=YYYY-MM-DD HH:MM:SS
  Headers:
    Authorization: Bearer {ACCESS_TOKEN}
    Accept: application/json
    X-API-VERSION: 1.0

  NOTE: Groww's docs mark this endpoint "deprecated, use Get Historical
  Candle Data instead" but did not surface the exact replacement path in
  available documentation as of 11 Aug 2026 — using this one since it is
  still live and documented with a full working example. Revisit if it
  stops working.

Response shape (documented):
  {
    "status": "SUCCESS",
    "payload": {
      "candles": [[epoch_seconds, open, high, low, close, volume], ...],
      "interval_in_minutes": 5
    }
  }
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime

GROWW_API_KEY = os.environ.get("GROWW_API_KEY", "")  # the daily access token (Bearer)
GROWW_API_SECRET = os.environ.get("GROWW_API_SECRET", "")  # not used by this endpoint directly

GROWW_API_BASE = "https://api.groww.in/v1"


def fetch_candles(trading_symbol, start_time, end_time, exchange="NSE", segment="CASH"):
    """
    start_time / end_time: 'YYYY-MM-DD HH:MM:SS' strings (IST, market hours).
    Returns a list of {timestamp, open, high, low, close, volume} dicts,
    or raises RuntimeError with details on failure.
    """
    if not GROWW_API_KEY:
        raise RuntimeError("GROWW_API_KEY not set (expected in environment / GitHub secret).")

    params = urllib.parse.urlencode({
        "exchange": exchange,
        "segment": segment,
        "trading_symbol": trading_symbol,
        "start_time": start_time,
        "end_time": end_time,
    })
    url = f"{GROWW_API_BASE}/historical/candle/range?{params}"

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {GROWW_API_KEY}",
        "X-API-VERSION": "1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Groww API HTTP error {e.code}: {e.read().decode()[:500]}")
    except Exception as e:
        raise RuntimeError(f"Groww API request failed: {e}")

    if data.get("status") != "SUCCESS":
        raise RuntimeError(f"Groww API returned non-success: {data}")

    raw_candles = data.get("payload", {}).get("candles", [])
    out = []
    for c in raw_candles:
        ts_epoch, o, h, l, close, vol = c
        ts = datetime.fromtimestamp(ts_epoch).strftime("%Y-%m-%dT%H:%M:%S")
        out.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": close, "volume": vol})
    return out


if __name__ == "__main__":
    # Quick connectivity test — fetches today's NIFTY candles (index quoting
    # may need a different trading_symbol/exchange convention; adjust once
    # a real test run shows the correct symbol format for indices).
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        candles = fetch_candles("NIFTY", f"{today} 09:15:00", f"{today} 15:30:00")
        print(f"Fetched {len(candles)} candles.")
        if candles:
            print("First:", candles[0])
            print("Last:", candles[-1])
    except Exception as e:
        print("Test fetch failed:", e)
