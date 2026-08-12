"""
FII/DII Daily Positioning Layer — MANUAL INPUT (as of 12 Aug 2026)
----------------------------------------------------------------------
Automated NSE scraping was tried and abandoned:
  - nseindia.com is not reachable from the Claude sandbox (network allowlist)
  - The `nsefin` package has a URL-construction bug (missing "/" between
    BASE and path) that could not be patched around because its Endpoints
    class is a frozen dataclass (setattr silently fails)
  - Even if fixed, NSE's anti-bot protections make unattended scraping
    fragile from GitHub Actions / a VPS anyway
Decision (12 Aug 2026): use MANUAL data entry instead — same reliable
pattern as the options-OI CSV layer (oi_orderflow.py). Saim provides the
day's FII/DII net figures (from NSE's site, a broker app, or any source
he trusts), Claude records them here.

Storage: memory/fii_dii_manual.jsonl — one line per day, appended via
record_fii_dii(). The runner reads the latest entry automatically.
"""

import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.path.join(BASE, "memory", "fii_dii_manual.jsonl")


def record_fii_dii(date_str, fii_net_crores, dii_net_crores, source_note=""):
    """
    Appends a manually-provided day's FII/DII net figures (in Rs. Crores;
    positive = net buying, negative = net selling). Idempotent by date —
    re-recording the same date overwrites the earlier entry.
    """
    entries = []
    if os.path.exists(STORE_PATH):
        with open(STORE_PATH) as f:
            entries = [json.loads(l) for l in f if l.strip()]
    entries = [e for e in entries if e["date"] != date_str]
    entries.append({
        "date": date_str,
        "fii_net_crores": fii_net_crores,
        "dii_net_crores": dii_net_crores,
        "source_note": source_note,
        "recorded_at": datetime.now().isoformat(),
    })
    entries.sort(key=lambda e: e["date"])
    with open(STORE_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return entries[-1]


def get_latest_manual_fii_bias(lookback_days=3):
    """
    Returns a bias dict from the most recent `lookback_days` manually
    recorded entries: BULLISH (net FII buying) / BEARISH (net FII selling)
    / NEUTRAL, or None if nothing has been recorded yet.
    """
    if not os.path.exists(STORE_PATH):
        return None
    with open(STORE_PATH) as f:
        entries = [json.loads(l) for l in f if l.strip()]
    if not entries:
        return None

    recent = entries[-lookback_days:]
    total_fii_net = sum(e["fii_net_crores"] for e in recent)

    if total_fii_net > 0:
        lean = "BULLISH"
    elif total_fii_net < 0:
        lean = "BEARISH"
    else:
        lean = "NEUTRAL"

    return {
        "lean": lean,
        "total_net_crores": round(total_fii_net, 1),
        "days_considered": len(recent),
        "recent_dates": [e["date"] for e in recent],
    }


if __name__ == "__main__":
    bias = get_latest_manual_fii_bias()
    print(json.dumps(bias, indent=2) if bias else "No manual FII/DII data recorded yet.")
