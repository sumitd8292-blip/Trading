"""
FII/DII Daily Positioning Layer
---------------------------------
Fetches FII (Foreign Institutional Investor) and DII (Domestic
Institutional Investor) daily net buy/sell activity from NSE, via the
`nsefin` PyPI package (pip install nsefin).

*** IMPORTANT — NETWORK REQUIREMENT ***
nseindia.com is NOT reachable from the Claude sandbox (not in the
network allowlist) — this module cannot be tested from within a Claude
session's bash tool. It CAN be tested from:
  - GitHub Actions (open internet access) — this is the intended runtime
  - The VPS once deployed (see deploy/deploy.md)
Test via a GitHub Actions run and check the Telegram/log output, same
pattern used for groww_api.py and Telegram testing.

*** BUG WORKAROUND ***
nsefin's NSEClient.get_fii_dii_activity() (and other endpoints) build
URLs as f"{BASE}{path}" where BASE="https://www.nseindia.com" and
path="api/fiidiiTradeReact" (no leading slash) — this produces the
broken URL "https://www.nseindia.comapi/fiidiiTradeReact". _get_client()
below monkey-patches the endpoints object to prepend "/" to any path
missing one, fixing this without needing to fork the library.

DATA SHAPE (per NSE's fiidiiTradeReact endpoint): a list of daily rows,
each typically {category: "FII/FPI" | "DII", date: "DD-MMM-YYYY",
buyValue: <crores>, sellValue: <crores>, netValue: <crores>}.
"""

import os
import json
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))


def _get_client():
    import nsefin
    client = nsefin.NSEClient()

    # Patch the buggy path-joining bug (missing slash between BASE and path)
    orig_get = client._get if hasattr(client, "_get") else None
    # Simplest safe fix: ensure every Endpoints string attribute starts with "/"
    for attr_name in dir(client.endpoints):
        if attr_name.startswith("_"):
            continue
        val = getattr(client.endpoints, attr_name, None)
        if isinstance(val, str) and val.startswith("api/"):
            try:
                setattr(client.endpoints, attr_name, "/" + val)
            except Exception:
                pass  # some may be read-only / dataclass frozen; ignore

    return client


def fetch_fii_dii_activity():
    """
    Returns the raw FII/DII activity data from NSE (list of dicts), or
    raises an exception with details if the fetch fails (network,
    NSE anti-bot block, or parsing issue).
    """
    client = _get_client()
    return client.get_fii_dii_activity()


def compute_fii_bias(rows, lookback_days=3):
    """
    rows: the raw list from fetch_fii_dii_activity()
    Returns a bias dict: net FII flow direction over the last
    `lookback_days` trading days -> BULLISH (net buying) / BEARISH (net
    selling) / NEUTRAL, plus the raw recent net values for transparency.
    """
    if not rows:
        return None

    fii_rows = [r for r in rows if "FII" in str(r.get("category", "")).upper()
                or "FPI" in str(r.get("category", "")).upper()]
    fii_rows = fii_rows[-lookback_days:] if len(fii_rows) > lookback_days else fii_rows
    if not fii_rows:
        return None

    net_values = []
    for r in fii_rows:
        nv = r.get("netValue")
        if nv is None:
            buy = r.get("buyValue", 0) or 0
            sell = r.get("sellValue", 0) or 0
            nv = buy - sell
        net_values.append(float(nv))

    total_net = sum(net_values)
    if total_net > 0:
        lean = "BULLISH"
    elif total_net < 0:
        lean = "BEARISH"
    else:
        lean = "NEUTRAL"

    return {
        "lean": lean,
        "total_net_crores": round(total_net, 1),
        "days_considered": len(net_values),
        "recent_net_values": [round(v, 1) for v in net_values],
    }


if __name__ == "__main__":
    try:
        rows = fetch_fii_dii_activity()
        print(f"Fetched {len(rows)} FII/DII rows.")
        bias = compute_fii_bias(rows)
        print(json.dumps(bias, indent=2))
    except Exception as e:
        print(f"FII/DII fetch FAILED: {type(e).__name__}: {e}")
