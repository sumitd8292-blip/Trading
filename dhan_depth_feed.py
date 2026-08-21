"""
dhan_depth_feed.py — Dhan 20/200-level market depth via official FullDepth class
------------------------------------------------------------------------------
20 Aug 2026: Saim's request — get as close to DEXT's native, low-latency
data as possible. Uses the OFFICIAL dhanhq Python library's FullDepth
class (WebSocket-based, wss://depth-api-feed.dhan.co/twentydepth or
wss://full-depth-api.dhan.co/twohundreddepth) rather than hand-rolling
binary packet parsing — Dhan's own library already handles this
correctly, unlike the situation we hit with Groww's less-documented
WebSocket/NATS layer.

20-level depth: up to 50 instruments per connection.
200-level depth: only 1 instrument per connection (much deeper, but
one-at-a-time).

Install: pip install dhanhq --break-system-packages
(separate from growwapi — no conflict, both can coexist)

Completely isolated from continuous_runner.py / live trading, same safe
pattern as all other diagnostic tools — nothing here affects the live
Groww-powered system until Saim explicitly decides to switch.
"""
import os
import sys
import time
import threading


def get_dhan_context():
    from dhanhq import DhanContext
    client_id = os.environ.get("DHAN_CLIENT_ID")
    access_token = os.environ.get("DHAN_ACCESS_TOKEN")
    if not client_id or not access_token:
        raise RuntimeError("DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not set in environment.")
    return DhanContext(client_id, access_token)


def stream_depth(instruments, depth_level=20, duration_seconds=30):
    """
    instruments: list of (exchange_segment_code, security_id) tuples.
    Exchange segment codes confirmed live (20 Aug): NSE=1, NSE_FNO=2.
    depth_level: 20 or 200.
    duration_seconds: how long to listen before stopping (increased to
    30s — first test with 15s got 0 packets despite successful
    subscription, may just need more time, or market may be closed).

    FIXED (20 Aug 2026) based on live introspection of the real
    FullDepth object: the correct callback attribute is `on_ticks`
    (not on_update/on_data/etc — those don't exist), and the correct
    blocking entry point is `run_forever()` (not `connect()`, which is
    an async coroutine).
    """
    from dhanhq import FullDepth

    ctx = get_dhan_context()
    received = []

    def on_data(data):
        received.append(data)
        print(f"Depth packet received: {data}")

    print(f"Connecting to Dhan {depth_level}-level depth feed for {instruments}...")
    depth_client = FullDepth(ctx, instruments, depth_level)
    # Set callback immediately after construction, before starting the loop —
    # in case the internal loop reads on_ticks only once at startup
    depth_client.on_ticks = on_data

    def run():
        try:
            depth_client.run_forever()
        except Exception as e:
            print(f"run_forever() raised: {type(e).__name__}: {e}")

    t = threading.Thread(target=run, daemon=True)
    t.start()

    for i in range(duration_seconds):
        time.sleep(1)
        if received:
            print(f"First packet arrived after {i+1}s")
            break
        # re-set the callback each second in case FullDepth's internal
        # loop checks for it repeatedly rather than caching a reference
        depth_client.on_ticks = on_data

    return received


if __name__ == "__main__":
    # FIX (21 Aug 2026): was hardcoded to yesterday's ATM strike (61647,
    # NIFTY 24200 CE) — with today's gap-down open (spot ~24245), that
    # strike is no longer ATM. Confirmed via Dhan search (live, this
    # session) that today's correct near-ATM strike is NIFTY 24250 CE,
    # securityId=61671, 25-Aug-2026 expiry. Using this directly rather
    # than dynamic lookup (the earlier dynamic-lookup attempt incorrectly
    # mixed in Groww's token system, which is NOT compatible with Dhan's
    # security_id numbering — a proper Dhan-native instrument search
    # function is a future improvement, this hardcoded value is
    # confirmed correct for TODAY specifically).
    print("Using today's confirmed ATM strike: NIFTY 24250 CE, securityId=61671")
    print(f"\nListening for 20s on exchange_token=61671...")
    result = stream_depth([(2, "61671")], depth_level=20, duration_seconds=20)
    print(f"\nTotal packets received: {len(result)}")
