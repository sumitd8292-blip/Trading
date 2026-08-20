"""
order_flow_diagnostic_agent.py — standalone, isolated order-flow debugging
------------------------------------------------------------------------------
20 Aug 2026: Saim's architectural decision — instead of enabling/disabling
order-flow-depth code INSIDE continuous_runner.py (which risks the live
trading loop every time we experiment), this is a SEPARATE, standalone
script. It does NOT touch paper_trader, engine, signals, or anything
related to live trading — it ONLY tries different approaches to fetch
market depth and logs what works / what doesn't.

Run manually whenever you want to test something:
    python3 order_flow_diagnostic_agent.py

Once something here is CONFIRMED working, only THEN do we port the
working approach back into continuous_runner.py's refresh_order_flow_depth().
Until then, continuous_runner.py's order-flow-depth stays disabled and
the live system is completely unaffected by whatever we try here.
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groww_api import fetch_quote_depth, fetch_ltp, fetch_option_chain
from groww_option_chain import parse_option_chain

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory", "order_flow_diagnostic_log.jsonl")


def log_attempt(description, request_info, result_info):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "description": description,
        "request": request_info,
        "result": result_info,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"\n=== {description} ===")
    print(f"Request: {request_info}")
    print(f"Result: {result_info}\n")


def try_quote_depth(trading_symbol, exchange="NSE", segment="FNO"):
    try:
        payload = fetch_quote_depth(trading_symbol, exchange=exchange, segment=segment)
        return {"success": True, "payload_keys": list(payload.keys()) if payload else None}
    except Exception as e:
        return {"success": False, "error": str(e)}


def try_ltp(exchange_symbols, segment="FNO"):
    try:
        payload = fetch_ltp(exchange_symbols, segment=segment)
        return {"success": True, "payload": payload}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_live_atm_symbols():
    """Fetches a fresh option chain and returns ATM CE trading_symbol
    (from the chain's own field) for NIFTY and BANKNIFTY, plus the
    strike/expiry used — for building test cases against real, currently
    listed contracts."""
    results = {}
    from continuous_runner import _EXPIRY_CALCULATORS, get_next_tuesday_expiry
    for symbol in ["NIFTY", "BANKNIFTY"]:
        expiry = _EXPIRY_CALCULATORS.get(symbol, get_next_tuesday_expiry)()
        try:
            payload = fetch_option_chain(symbol, expiry)
            spot = payload.get("underlying_ltp")
            rows = parse_option_chain(payload)
            if not rows:
                continue
            atm_row = min(rows, key=lambda r: abs(r["strike"] - spot))
            results[symbol] = {
                "spot": spot, "strike": atm_row["strike"], "expiry": expiry,
                "chain_trading_symbol": atm_row["call"].get("trading_symbol") if atm_row.get("call") else None,
            }
        except Exception as e:
            results[symbol] = {"error": str(e)}
    return results


def run_diagnostics():
    print("Fetching live ATM option data as test cases...")
    atm_data = get_live_atm_symbols()
    print(json.dumps(atm_data, indent=2))

    for symbol, data in atm_data.items():
        if "error" in data:
            continue
        strike = data["strike"]
        expiry = data["expiry"]
        chain_symbol = data["chain_trading_symbol"]

        # Test 1: the exact trading_symbol the option-chain itself returned
        if chain_symbol:
            r = try_quote_depth(chain_symbol)
            log_attempt(f"{symbol} — chain's own trading_symbol via quote/depth", chain_symbol, r)

        # Test 2: same symbol via LTP endpoint with NSE_ prefix
        if chain_symbol:
            r = try_ltp([f"NSE_{chain_symbol}"])
            log_attempt(f"{symbol} — chain's own trading_symbol via LTP", f"NSE_{chain_symbol}", r)

        # Test 3: BSE exchange instead of NSE (in case options are BSE-listed for this account)
        if chain_symbol:
            r = try_quote_depth(chain_symbol, exchange="BSE")
            log_attempt(f"{symbol} — chain's trading_symbol, BSE exchange", chain_symbol, r)

        # Test 4: try the underlying INDEX itself via quote/depth (sanity check —
        # if even NIFTY/BANKNIFTY index quote fails, the issue is more fundamental)
        r = try_quote_depth(symbol, exchange="NSE", segment="CASH")
        log_attempt(f"{symbol} — plain index symbol via quote/depth (sanity check)", symbol, r)

        # Test 5: exchange_token (authoritative, from instruments CSV lookup)
        # tried AS the trading_symbol value — unconventional but cheap to
        # test, since Groww's docs show exchange_token is what WebSocket
        # Feed actually uses successfully (confirmed via GrowwMCP: NIFTY
        # 24200 CE has exchange_token "61647", live depth data works)
        try:
            from groww_api import find_exchange_token
            token_info = find_exchange_token(symbol, strike, expiry, "CE")
            if token_info and token_info.get("exchange_token"):
                r = try_quote_depth(token_info["exchange_token"])
                log_attempt(f"{symbol} — exchange_token as trading_symbol param", token_info, r)
            else:
                log_attempt(f"{symbol} — exchange_token lookup", f"strike={strike} expiry={expiry}",
                             {"success": False, "error": "not found in instruments CSV"})
        except Exception as e:
            log_attempt(f"{symbol} — exchange_token lookup failed", "", {"success": False, "error": str(e)})


if __name__ == "__main__":
    run_diagnostics()
