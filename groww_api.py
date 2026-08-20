"""
Groww Direct API — Live Data Fetcher
-------------------------------------
SEPARATE from GrowwMCP. GrowwMCP only works inside Claude chat sessions.
This module uses Groww's own paid Trading/Data API (₹499+GST/month
subscription, active since 11 Aug 2026) so live data fetching can
eventually run from GitHub Actions without a Claude session open.

*** IMPORTANT LIMITATION ***
Groww's access token EXPIRES DAILY at 6 AM IST. The token needs to be
regenerated and re-uploaded to GitHub Secrets every day. Not yet
automated — Saim sends a fresh token, Claude re-encrypts it into
GROWW_API_KEY each time. Investigate Groww's TOTP-based auto-refresh
(secret + totp) for a longer-lived unattended setup later.

ENDPOINT (corrected 11 Aug 2026 — previous version used a deprecated
path/param and got 403s):
  GET https://api.groww.in/v1/historical/candles
    ?exchange=NSE&segment=CASH&groww_symbol=NSE-NIFTY
    &start_time=YYYY-MM-DD HH:MM:SS&end_time=YYYY-MM-DD HH:MM:SS
    &candle_interval=5minute
  Headers:
    Authorization: Bearer {ACCESS_TOKEN}
    Accept: application/json
    X-API-VERSION: 1.0

  groww_symbol format: "EXCHANGE-TRADINGSYMBOL" for stocks/indices (e.g.
  "NSE-NIFTY", "NSE-WIPRO"). For FNO: adds expiry/strike/CE-PE, not
  needed yet for index-only candles.

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

GROWW_API_KEY = os.environ.get("GROWW_API_KEY", "")  # daily access token (Bearer)
GROWW_API_SECRET = os.environ.get("GROWW_API_SECRET", "")  # not used by this endpoint directly

GROWW_API_BASE = "https://api.groww.in/v1"

# Map our internal interval-in-minutes to Groww's string format
_INTERVAL_MAP = {
    1: "1minute",
    5: "5minute",
    15: "15minute",
    30: "30minute",
    60: "60minute",
}


def fetch_candles(symbol, start_time, end_time, exchange="NSE", segment="CASH", interval_minutes=5, expiry=None):
    """
    symbol: plain trading symbol, e.g. "NIFTY", "RELIANCE" (gets combined
            into groww_symbol as "EXCHANGE-SYMBOL" for cash/index).
    expiry: for FUTURES (segment="FNO"), pass expiry as "DDMmmYY" (e.g.
            "28Aug25") to fetch futures candles instead of cash/index —
            groww_symbol becomes "EXCHANGE-SYMBOL-EXPIRY-FUT". Used for
            post-market-close futures momentum (futures/options trade
            15:15-15:30ish after the cash index closes, per Saim's 17
            Aug request to track that continuation as a next-day gap signal).
    start_time / end_time: 'YYYY-MM-DD HH:MM:SS' strings (IST, market hours).
    interval_minutes: one of 1, 5, 15, 30, 60.
    Returns a list of {timestamp, open, high, low, close, volume} dicts,
    or raises RuntimeError with details on failure.
    """
    if not GROWW_API_KEY:
        raise RuntimeError("GROWW_API_KEY not set (expected in environment / GitHub secret).")

    candle_interval = _INTERVAL_MAP.get(interval_minutes)
    if not candle_interval:
        raise ValueError(f"Unsupported interval_minutes: {interval_minutes}")

    if expiry:
        groww_symbol = f"{exchange}-{symbol}-{expiry}-FUT"
    else:
        groww_symbol = f"{exchange}-{symbol}"
    params = urllib.parse.urlencode({
        "exchange": exchange,
        "segment": segment,
        "groww_symbol": groww_symbol,
        "start_time": start_time,
        "end_time": end_time,
        "candle_interval": candle_interval,
    })
    url = f"{GROWW_API_BASE}/historical/candles?{params}"

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
        # Handle variable-length candle tuples (some responses omit volume)
        ts_raw, o, h, l, close = c[0], c[1], c[2], c[3], c[4]
        vol = c[5] if len(c) > 5 else None
        # Groww returns either a numeric epoch or an ISO datetime string depending
        # on the endpoint/response variant — handle all cases seen so far
        if isinstance(ts_raw, str):
            if "T" in ts_raw or "-" in ts_raw:
                ts = ts_raw[:19]  # already ISO format, just trim to seconds precision
            else:
                ts = datetime.fromtimestamp(float(ts_raw)).strftime("%Y-%m-%dT%H:%M:%S")
        else:
            ts = datetime.fromtimestamp(ts_raw).strftime("%Y-%m-%dT%H:%M:%S")
        out.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": close, "volume": vol})
    return out


if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        candles = fetch_candles("NIFTY", f"{today} 09:15:00", f"{today} 15:30:00", interval_minutes=5)
        print(f"Fetched {len(candles)} candles.")
        if candles:
            print("First:", candles[0])
            print("Last:", candles[-1])
    except Exception as e:
        print("Test fetch failed:", e)


def fetch_option_chain(underlying, expiry_date, exchange="NSE"):
    """
    Fetches the FULL option chain (all strikes, both CE/PE, with Greeks
    already included) in ONE call — much better than the old manual-CSV
    workflow. Endpoint added 17 Aug 2026 in response to Saim's request
    for continuous/live options data (relevant for expiry-day gamma
    analysis).

    underlying: e.g. "NIFTY", "BANKNIFTY"
    expiry_date: "YYYY-MM-DD"

    Returns the raw parsed JSON payload (structure not fully confirmed
    from docs alone — first live call should be inspected to confirm
    field names; this function does NOT reshape the response, callers
    should handle whatever structure comes back and we'll adapt).
    """
    if not GROWW_API_KEY:
        raise RuntimeError("GROWW_API_KEY not set (expected in environment / GitHub secret).")

    url = f"{GROWW_API_BASE}/option-chain/exchange/{exchange}/underlying/{underlying}?expiry_date={expiry_date}"

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {GROWW_API_KEY}",
        "X-API-VERSION": "1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Groww option-chain HTTP error {e.code}: {e.read().decode()[:800]}")
    except Exception as e:
        raise RuntimeError(f"Groww option-chain request failed: {e}")

    if data.get("status") != "SUCCESS":
        raise RuntimeError(f"Groww option-chain returned non-success: {data}")

    return data.get("payload")


def fetch_quote_depth(trading_symbol, exchange="NSE", segment="FNO"):
    """
    Fetches the full live quote INCLUDING market depth (5-level buy/sell
    order book) for one instrument — real order-flow data, distinct from
    OI (which is a positioning snapshot, not real-time order punching).

    Added 19 Aug 2026 per Saim's request: OI/PCR can look bullish while
    price keeps failing to move up because large SELL orders are being
    punched and absorbing buy pressure at a specific level — this needs
    actual bid/ask depth to detect, not OI.

    Returns the raw payload dict (buyBook/sellBook with 5 price levels
    each, totalBuyQty/totalSellQty, OI, volume, etc.) or raises
    RuntimeError on failure.
    """
    if not GROWW_API_KEY:
        raise RuntimeError("GROWW_API_KEY not set (expected in environment / GitHub secret).")

    url = f"{GROWW_API_BASE}/live-data/quote?exchange={exchange}&segment={segment}&trading_symbol={trading_symbol}"
    print(f"DEBUG fetch_quote_depth URL: {url}")

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {GROWW_API_KEY}",
        "X-API-VERSION": "1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Groww quote-depth HTTP error {e.code}: {e.read().decode()[:500]}")
    except Exception as e:
        raise RuntimeError(f"Groww quote-depth request failed: {e}")

    if data.get("status") != "SUCCESS":
        raise RuntimeError(f"Groww quote-depth returned non-success: {data}")

    return data.get("payload")


def fetch_ltp(exchange_symbols, segment="FNO"):
    """
    Diagnostic alternative to fetch_quote_depth (20 Aug 2026) — tries
    Groww's /v1/live-data/ltp endpoint instead, which uses a genuinely
    different request structure (exchange_symbols array with "NSE_"
    prefix combined into the symbol string, e.g. "NSE_NIFTY25APR24100PE")
    rather than separate exchange+trading_symbol params. Used to isolate
    whether repeated GA001 errors are specific to the quote/depth
    endpoint, or the symbol itself is being rejected everywhere.

    exchange_symbols: list of strings like ["NSE_NIFTY2682524300CE"]
    """
    if not GROWW_API_KEY:
        raise RuntimeError("GROWW_API_KEY not set.")

    symbols_param = ",".join(exchange_symbols)
    url = f"{GROWW_API_BASE}/live-data/ltp?segment={segment}&exchange_symbols={symbols_param}"
    print(f"DEBUG fetch_ltp URL: {url}")

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {GROWW_API_KEY}",
        "X-API-VERSION": "1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Groww LTP HTTP error {e.code}: {e.read().decode()[:500]}")
    except Exception as e:
        raise RuntimeError(f"Groww LTP request failed: {e}")

    if data.get("status") != "SUCCESS":
        raise RuntimeError(f"Groww LTP returned non-success: {data}")

    return data.get("payload")


INSTRUMENTS_CSV_URL = "https://growwapi-assets.groww.in/instruments/instrument.csv"
_INSTRUMENTS_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "instruments_cache.csv")


def download_instruments_csv(force=False):
    """
    Downloads Groww's official instruments master list (public URL, no
    auth needed) and caches it locally. This is the AUTHORITATIVE source
    for exchange_token, trading_symbol, and all other instrument
    identifiers — added 20 Aug 2026 after repeated guessing failures on
    order-flow-depth's trading_symbol. Per Saim's research finding: real
    Indian order-flow platforms (e.g. VolumeLens) use exchange_token via
    WebSocket feeds, not guessed trading_symbol strings via REST.

    Re-downloads only if the cache doesn't exist or force=True (this
    file changes daily as contracts expire/get listed, so cache for a
    trading day at most).
    """
    if not force and os.path.exists(_INSTRUMENTS_CACHE_PATH):
        return _INSTRUMENTS_CACHE_PATH

    req = urllib.request.Request(INSTRUMENTS_CSV_URL, headers={"Accept": "text/csv"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = resp.read().decode()
    except Exception as e:
        raise RuntimeError(f"Failed to download instruments CSV: {e}")

    os.makedirs(os.path.dirname(_INSTRUMENTS_CACHE_PATH), exist_ok=True)
    with open(_INSTRUMENTS_CACHE_PATH, "w") as f:
        f.write(content)
    return _INSTRUMENTS_CACHE_PATH


def find_exchange_token(underlying_symbol, strike_price, expiry_date, option_type="CE", force_refresh=False):
    """
    Looks up the AUTHORITATIVE exchange_token for a specific option
    contract from Groww's own instruments CSV — no guessing, no string
    construction. underlying_symbol e.g. "NIFTY"/"BANKNIFTY",
    expiry_date in "YYYY-MM-DD" format, option_type "CE"/"PE".

    Returns dict with exchange_token, trading_symbol, groww_symbol, or
    None if not found.
    """
    import csv as csv_module

    path = download_instruments_csv(force=force_refresh)
    with open(path) as f:
        reader = csv_module.DictReader(f)
        for row in reader:
            if (row.get("underlying_symbol") == underlying_symbol and
                    row.get("expiry_date") == expiry_date and
                    row.get("instrument_type") == option_type):
                try:
                    if float(row.get("strike_price", -1)) == float(strike_price):
                        return {
                            "exchange_token": row.get("exchange_token"),
                            "trading_symbol": row.get("trading_symbol"),
                            "groww_symbol": row.get("groww_symbol"),
                            "exchange": row.get("exchange"),
                        }
                except (ValueError, TypeError):
                    continue
    return None
