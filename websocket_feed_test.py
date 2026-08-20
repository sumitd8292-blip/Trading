"""
websocket_feed_test.py — tests Groww's actual WebSocket Feed for market depth
------------------------------------------------------------------------------
20 Aug 2026: Saim's research found real Indian order-flow platforms
(VolumeLens etc.) use Groww's WEBSOCKET Feed (GrowwFeed class,
exchange_token-based subscription), NOT the REST /v1/live-data/quote
endpoint we've been struggling with. This is a standalone test of that
approach — requires the official `growwapi` Python SDK.

Install: pip install growwapi --break-system-packages

Completely isolated from the live trading system — safe to run/test
anytime without touching continuous_runner.py.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_websocket_feed(exchange_token, segment="FNO"):
    """
    Attempts to fetch market depth via GrowwFeed (WebSocket-based),
    using an exchange_token found via groww_api.find_exchange_token().
    This is a BLOCKING call per Groww's docs, so it runs for a short
    fixed duration then reports whatever it received.
    """
    try:
        from growwapi import GrowwFeed, GrowwAPI
    except ImportError:
        print("growwapi package not installed. Run: pip install growwapi --break-system-packages")
        return None

    api_key = os.environ.get("GROWW_API_KEY")
    if not api_key:
        print("GROWW_API_KEY not set in environment.")
        return None

    groww = GrowwAPI(api_key)
    feed = GrowwFeed(groww)

    received = {}

    def on_data_received(meta):
        print("Data received via WebSocket:", meta)
        received["data"] = feed.get_market_depth()
        received["got_data"] = True

    instruments_list = [{"exchange": "NSE", "segment": segment, "exchange_token": str(exchange_token)}]
    print(f"Subscribing to exchange_token={exchange_token} via WebSocket...")

    import threading
    import time as time_module

    def run_feed():
        feed.subscribe_market_depth(instruments_list, on_data_received=on_data_received)

    t = threading.Thread(target=run_feed, daemon=True)
    t.start()
    time_module.sleep(10)  # wait up to 10s for data

    if received.get("got_data"):
        print("SUCCESS — WebSocket Feed returned data:", received["data"])
    else:
        print("No data received within 10s — WebSocket Feed may need different setup, or market is closed.")

    return received.get("data")


if __name__ == "__main__":
    import sys as sys_module
    from groww_api import find_exchange_token
    from continuous_runner import _EXPIRY_CALCULATORS, get_next_tuesday_expiry
    from groww_api import fetch_option_chain
    from groww_option_chain import parse_option_chain

    symbol = sys_module.argv[1] if len(sys_module.argv) > 1 else "NIFTY"
    expiry = _EXPIRY_CALCULATORS.get(symbol, get_next_tuesday_expiry)()
    payload = fetch_option_chain(symbol, expiry)
    spot = payload.get("underlying_ltp")
    rows = parse_option_chain(payload)
    atm_row = min(rows, key=lambda r: abs(r["strike"] - spot))
    strike = atm_row["strike"]

    print(f"Testing {symbol} ATM strike={strike} expiry={expiry}")
    token_info = find_exchange_token(symbol, strike, expiry, "CE")
    print("Token info from instruments CSV:", token_info)

    if token_info and token_info.get("exchange_token"):
        test_websocket_feed(token_info["exchange_token"])
    else:
        print("Could not find exchange_token — cannot test WebSocket feed.")
