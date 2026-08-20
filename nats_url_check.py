"""
nats_url_check.py — reveals the actual NATS server URL/port Groww's
Feed tries to connect to, by monkey-patching nats.connect() to print
its arguments before the real connection attempt (which is failing
with an unhelpfully generic "Error:" from growwapi's own error handling).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nats
_original_connect = nats.connect

async def _patched_connect(*args, **kwargs):
    print("=" * 60)
    print("NATS connect() called with:")
    print("  servers:", kwargs.get("servers"))
    print("  tls:", kwargs.get("tls"))
    print("=" * 60)
    try:
        result = await _original_connect(*args, **kwargs)
        print("NATS connect() SUCCEEDED")
        return result
    except Exception as e:
        print(f"NATS connect() RAISED: {type(e).__name__}: {e!r}")
        raise

nats.connect = _patched_connect

# Now also patch the nats_client module's already-imported reference
import growwapi.groww.nats_client as nats_client_module
nats_client_module.connect = _patched_connect

from growwapi import GrowwFeed, GrowwAPI
from groww_api import find_exchange_token, fetch_option_chain
from groww_option_chain import parse_option_chain
from continuous_runner import _EXPIRY_CALCULATORS, get_next_tuesday_expiry

api_key = os.environ.get("GROWW_API_KEY")
groww = GrowwAPI(api_key)
feed = GrowwFeed(groww)

symbol = "NIFTY"
expiry = _EXPIRY_CALCULATORS.get(symbol, get_next_tuesday_expiry)()
payload = fetch_option_chain(symbol, expiry)
spot = payload.get("underlying_ltp")
rows = parse_option_chain(payload)
atm_row = min(rows, key=lambda r: abs(r["strike"] - spot))
token_info = find_exchange_token(symbol, atm_row["strike"], expiry, "CE")
print("Using exchange_token:", token_info["exchange_token"])

instruments_list = [{"exchange": "NSE", "segment": "FNO", "exchange_token": str(token_info["exchange_token"])}]

def on_data(meta):
    print("DATA RECEIVED:", meta)

try:
    feed.subscribe_market_depth(instruments_list, on_data_received=on_data)
except Exception as e:
    print(f"subscribe_market_depth raised: {type(e).__name__}: {e}")


# ADDITIONAL PATCH: intercept the error_cb itself, since growwapi's
# nats_client.py logs "Error: %s" with an exception object that
# stringifies to empty — print repr/type/args instead to see what's
# actually inside it.
import growwapi.groww.nats_client as ncm
_orig_class = ncm.GrowwFeedNatsClient if hasattr(ncm, "GrowwFeedNatsClient") else None
print("nats_client module attrs:", [a for a in dir(ncm) if not a.startswith("_")])
