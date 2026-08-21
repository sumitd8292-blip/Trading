"""
dhan_api.py — Dhan (DhanHQ) API base, COMPLETELY ISOLATED from live trading
------------------------------------------------------------------------------
20 Aug 2026: Saim's decision — build a Dhan-integration core NOW, ready to
test, while Groww continues powering the LIVE trading system untouched.
If Dhan's market-depth/order-flow access proves more reliable (Groww's
own has been stuck for a full day — see order-flow-depth investigation
in memory), Saim can switch and cancel Groww's ₹499+GST/month
subscription. Until then, this file is NOT imported by continuous_runner.py
or anything live — pure standalone testing ground, same safe pattern as
order_flow_diagnostic_agent.py.

Setup needed before this can be tested (Saim hasn't done this yet):
1. Open a Dhan account (dhan.co) if not already have one
2. Go to Dhan Web -> Profile -> DhanHQ Trading APIs -> generate an
   access token (24-hour validity, or API-key based for 1-year validity
   with daily token refresh via TOTP — same daily-refresh pattern as
   Groww, so no better/worse on that front)
3. Set environment variables DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN

Docs confirmed (20 Aug 2026): base URL https://api.dhan.co/v2, headers
'access-token' (JWT) + 'client-id'. GET /marketfeed/quote gives a REST
SNAPSHOT of live quote + FULL market depth + option chain + Greeks in
ONE call — this is notably simpler than Groww's split REST(broken)/
WebSocket(also broken) situation, worth testing once credentials exist.
"""
import json
import os
import urllib.request
import urllib.error

DHAN_API_BASE = "https://api.dhan.co/v2"
DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN")


def _request(method, path, params=None, body=None):
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        raise RuntimeError("DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not set in environment — "
                            "Dhan account + API token needed first (see module docstring).")

    url = f"{DHAN_API_BASE}{path}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{query}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "access-token": DHAN_ACCESS_TOKEN,
        "client-id": DHAN_CLIENT_ID,
    }

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Dhan API HTTP error {e.code}: {e.read().decode()[:500]}")
    except Exception as e:
        raise RuntimeError(f"Dhan API request failed: {e}")


def fetch_quote_with_depth(security_id, exchange_segment="NSE_FNO"):
    """
    Fetches live quote + FULL market depth (REST snapshot, not
    WebSocket) for one instrument. exchange_segment examples:
    NSE_EQ (equity), NSE_FNO (F&O), NSE_INDEX (index).
    security_id: Dhan's internal numeric instrument ID (from their
    instrument master CSV, similar concept to Groww's exchange_token —
    see fetch_instrument_list()).
    """
    body = {exchange_segment: [int(security_id)]}
    return _request("POST", "/marketfeed/quote", body=body)


def fetch_option_chain(underlying_scrip, underlying_segment, expiry):
    """
    Fetches option chain (with Greeks) for an underlying — e.g. NIFTY,
    BANKNIFTY. underlying_scrip is Dhan's security_id for the
    underlying index, underlying_segment e.g. "IDX_I", expiry in
    "YYYY-MM-DD" format.
    """
    body = {
        "UnderlyingScrip": int(underlying_scrip),
        "UnderlyingSeg": underlying_segment,
        "Expiry": expiry,
    }
    return _request("POST", "/optionchain", body=body)


def fetch_expiry_list(underlying_scrip, underlying_segment):
    """Fetches available expiry dates for an underlying's option chain."""
    body = {"UnderlyingScrip": int(underlying_scrip), "UnderlyingSeg": underlying_segment}
    return _request("POST", "/optionchain/expirylist", body=body)


def fetch_historical_data(security_id, exchange_segment, instrument, from_date, to_date, interval="1"):
    """
    Fetches historical intraday OHLC candles.
    interval: "1", "5", "15", "25", "60" (minutes) or similar per Dhan's docs.
    """
    body = {
        "securityId": str(security_id),
        "exchangeSegment": exchange_segment,
        "instrument": instrument,
        "interval": interval,
        "fromDate": from_date,
        "toDate": to_date,
    }
    return _request("POST", "/charts/intraday", body=body)


def download_instrument_list():
    """
    Downloads Dhan's instrument master (needed to look up security_id
    for NIFTY/BANKNIFTY options by strike/expiry — same authoritative-
    lookup pattern used for Groww's exchange_token, to avoid guessing).
    Dhan publishes this as a CSV, URL confirmed in their docs under
    'Annexure' — https://images.dhan.co/api-data/api-scrip-master.csv
    """
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    req = urllib.request.Request(url, headers={"Accept": "text/csv"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode()


if __name__ == "__main__":
    print("Dhan API base module — run with DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN set to test.")
    print("Example: fetch_quote_with_depth(security_id, exchange_segment='NSE_FNO')")


GIFT_NIFTY_SECURITY_ID = "5024"  # confirmed 21 Aug 2026 via Dhan search: "GIFTNIFTY-INDEX", segment IDX_I


def fetch_gift_nifty_ltp():
    """
    Fetches GIFT NIFTY's current LTP — confirmed working 21 Aug 2026
    (₹24,294.00 fetched successfully). This is the overnight-sentiment
    signal Saim wants combined with pre-open order-flow to predict
    NIFTY's opening direction (pre_open_signal_tracker.py).
    """
    body = {"IDX_I": [int(GIFT_NIFTY_SECURITY_ID)]}
    result = _request("POST", "/marketfeed/ltp", body=body)
    try:
        return result["data"]["IDX_I"][GIFT_NIFTY_SECURITY_ID]["last_price"]
    except (KeyError, TypeError):
        return None
