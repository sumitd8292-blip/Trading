"""
run_agent_check.py — GitHub Actions entry point (WORK IN PROGRESS)

IMPORTANT LIMITATION (documented 10 Aug 2026):
GrowwMCP, the live market-data source used during Claude chat sessions, is
only reachable from within a Claude session — it CANNOT be called from
GitHub Actions (or any external server). This script therefore cannot yet
pull live NIFTY/BANKNIFTY prices on its own from GitHub's infrastructure.

Two ways forward (pick one, not yet decided):
  1. Use a market-data API GitHub Actions CAN reach directly — e.g. Dhan's
     paid Data API (₹499+GST/month, discussed earlier) or another
     broker/vendor API with a public REST endpoint.
  2. Keep live scoring inside Claude chat sessions (where GrowwMCP works),
     and use GitHub Actions only for things that don't need live data —
     e.g. sending a scheduled reminder, running backtests on already-saved
     historical data, or processing FII/DII files once uploaded to the repo.

Until one of those is wired up, this script is a placeholder that verifies
the Telegram connection works end-to-end from GitHub's servers (which DO
have internet access to api.telegram.org, unlike the Claude sandbox).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telegram_notify import send_telegram_message


def main():
    msg = (
        "🔧 Order-Flow Agent — GitHub Actions test run.\n"
        "This confirms the workflow + Telegram secrets are wired correctly.\n"
        "Live price-data automation is NOT yet connected (GrowwMCP only "
        "works inside Claude chat sessions) — see run_agent_check.py notes."
    )
    result = send_telegram_message(msg)
    print("Telegram send result:", result)
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
