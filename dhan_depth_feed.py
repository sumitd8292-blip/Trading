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


def stream_depth(instruments, depth_level=20, duration_seconds=15):
    """
    instruments: list of (exchange_segment_code, security_id) tuples.
    Exchange segment codes per Dhan's convention (NSE_FNO=2, NSE_EQ=1,
    IDX_I=0, etc — verify against dhanhq's own constants if available).
    depth_level: 20 or 200.
    duration_seconds: how long to listen before stopping (this is a
    streaming connection, not a single request/response).

    Returns a list of received depth snapshots.
    """
    from dhanhq import FullDepth

    ctx = get_dhan_context()

    print(f"Connecting to Dhan {depth_level}-level depth feed for {instruments}...")
    depth_client = FullDepth(ctx, instruments, depth_level)

    # ALWAYS introspect first (20 Aug fix — don't guess the callback
    # attribute name, look at what's actually there)
    all_attrs = [m for m in dir(depth_client) if not m.startswith("_")]
    print("FullDepth object's available attributes/methods:", all_attrs)

    import inspect
    for attr in all_attrs:
        try:
            val = getattr(depth_client, attr)
            if callable(val):
                try:
                    sig = inspect.signature(val)
                    print(f"  {attr}{sig}")
                except (ValueError, TypeError):
                    print(f"  {attr}(...)")
            else:
                print(f"  {attr} = {val!r}")
        except Exception as e:
            print(f"  {attr}: <error introspecting: {e}>")

    received = []

    def on_data(data):
        received.append(data)
        print(f"Depth packet received: {data}")

    # Try every plausible callback-attribute name, attach to whichever exists
    for candidate in ["on_update", "on_data", "on_message", "callback", "on_depth_update", "on_data_received"]:
        if hasattr(depth_client, candidate):
            print(f"Found callback attribute: {candidate} — attaching handler")
            setattr(depth_client, candidate, on_data)

    def run():
        for connect_method in ["connect_to_dhan_websocket_sync", "connect", "run", "start", "subscribe"]:
            if hasattr(depth_client, connect_method):
                print(f"Calling {connect_method}()...")
                try:
                    getattr(depth_client, connect_method)()
                except Exception as e:
                    print(f"{connect_method}() raised: {type(e).__name__}: {e}")
                return
        print("No recognized connect/run method found on FullDepth object.")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(duration_seconds)

    return received


if __name__ == "__main__":
    # Test with NIFTY 24200 CE (security_id 61647, confirmed via search
    # earlier this session) — exchange_segment for NSE F&O options
    result = stream_depth([(2, "61647")], depth_level=20, duration_seconds=15)
    print(f"\nTotal packets received: {len(result)}")
