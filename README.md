# Order-Flow Agent (NIFTY/BANKNIFTY)

Self-improving, memory-backed trading signal agent — separate from FlowDesk.
Alert-only (no auto-trading). Scores intraday setups using price/momentum now,
with FII/DII bias, options OI order-flow, Greeks, and SMC layers to be added.

## Structure
- `engine.py` — scoring engine + indicators (EMA, RSI) + memory logging
- `daily_store.py` — appends each trading day's NIFTY/BANKNIFTY data persistently
- `memory/lessons.json` — pre-loaded historical backtest findings
- `memory/trade_log.jsonl` — every scored signal, for future review/learning
- `data/daily_store/` — accumulating daily price data (5-min candles + EOD)
- `data/*.json` — 7-year historical NIFTY/BANKNIFTY daily datasets

## Status (10 Aug 2026)
Price+momentum layer only. Current default baseline: RSI 40/60 + EMA20 trend
filter + SL15/TGT25 (best backtested result: 42.9% win rate, +88 pts/90 days).
Max score capped at 6/10 until FII/DII, OI, Greeks, SMC layers are added.

See full roadmap and findings log in the working notes (kept outside this repo).
