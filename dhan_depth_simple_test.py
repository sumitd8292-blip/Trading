"""
dhan_depth_simple_test.py — no-threading test to isolate the 0-packets mystery
------------------------------------------------------------------------------
21 Aug 2026: dhan_depth_feed.py's threaded approach (run_forever() called
from a background thread) consistently receives 0 packets despite every
other check being confirmed correct (symbol, callback attribute, method
name, market open, subscription accepted). Python's asyncio has known
gotchas when an event loop is created in one thread but run from
another — this test eliminates that variable entirely by running
DIRECTLY in the main thread, no threading.Thread wrapper at all.

WARNING: this will BLOCK/HANG (that's run_forever()'s nature) — press
Ctrl+C after a few seconds once you see output (or don't see any).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dhanhq import DhanContext, FullDepth

client_id = os.environ.get("DHAN_CLIENT_ID")
access_token = os.environ.get("DHAN_ACCESS_TOKEN")
ctx = DhanContext(client_id, access_token)

instruments = [(2, "61671")]  # today's confirmed NIFTY 24250 CE
depth_client = FullDepth(ctx, instruments, 20)

packet_count = [0]

def on_data(data):
    packet_count[0] += 1
    print(f"PACKET #{packet_count[0]}: {data}")

depth_client.on_ticks = on_data

print("Starting run_forever() DIRECTLY in main thread (no threading wrapper).")
print("This will hang — press Ctrl+C after ~10-15 seconds to stop and see if any packets arrived.")
print(f"Total packets so far: {packet_count[0]}")

try:
    depth_client.run_forever()
except KeyboardInterrupt:
    print(f"\nStopped by user. Total packets received: {packet_count[0]}")
