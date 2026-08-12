# Order-Flow Agent (NIFTY/BANKNIFTY)

Self-improving, memory-backed trading signal agent — separate from FlowDesk.
Alert-only (no auto-trading). Scores intraday setups using price/momentum now,
with FII/DII bias, options OI order-flow, Greeks, and SMC layers to be added.

## Structure
- `engine.py` — scoring engine + indicators (EMA, RSI) + memory logging
- `daily_store.py` — appends each trading day's NIFTY/BANKNIFTY data persistently,
  supports multiple intervals (5min default, 1min planned) via `interval_label` param
- `telegram_notify.py` — sends alert-only signals to Telegram
- `groww_api.py` — STUB for Groww's direct paid API (separate from GrowwMCP), so
  live data can eventually be fetched from GitHub Actions without a Claude session.
  Not yet wired up — awaiting API key + docs from Saim.
- `run_agent_check.py` — GitHub Actions entry point; scores latest stored day, sends
  Telegram alert if signal found. Currently reads whatever's in data/daily_store/
  (populated from Claude sessions via GrowwMCP) — does not fetch live data itself yet.
- `.github/workflows/agent_run.yml` — scheduled + manually-triggerable GitHub Action
- `memory/lessons.json` — pre-loaded historical backtest findings
- `memory/trade_log.jsonl` — every scored signal, for future review/learning
- `data/daily_store/` — accumulating daily price data (candles + EOD)
- `data/*.json` — 7-year historical NIFTY/BANKNIFTY daily datasets

## Status (10 Aug 2026, evening)
Price+momentum layer only. Current default baseline: RSI 40/60 + EMA20 trend
filter + SL15/TGT25 (best backtested result: 42.9% win rate, +88 pts/90 days).
Max score capped at 6/10 until FII/DII, OI, Greeks, SMC layers are added.

Verified end-to-end: real (non-test) LONG signal (5/6) generated for NIFTY +
BANKNIFTY on 10 Aug 2026 and delivered successfully to Telegram via GitHub Actions.

Fixed bug: daily_store.py previously skipped re-saving a day if any entry already
existed for that date, even if the new data was more complete (e.g. full EOD vs.
partial mid-session). Now overwrites when new data has more candles.

## Next up
- Wire Groww's direct paid API (groww_api.py) once Saim provides the key, for
  1-minute granularity and fully-automated (no-Claude-session-needed) live data
- FII/DII bias layer (Saim sending data as it becomes available)
- Options OI order-flow, Greeks, SMC layers

## OI Order-Flow Layer (added 11 Aug 2026)
`oi_orderflow.py` parses NSE-style option-chain CSV exports (uploaded by Saim)
and computes PCR, max-OI support/resistance strikes, and a BULLISH/BEARISH/
NEUTRAL lean from OI-change direction. engine.py now awards +2 points when
this lean AGREES with the price/momentum signal direction, notes disagreement
explicitly ("treat with caution") without boosting score, and stays silent
(0/2) if neutral or no data. Max achievable score is now 8/10 (was 6/10).

Currently OI snapshots are added manually (Saim uploads a CSV, Claude parses
and stores it via daily_store.append_options_snapshot) — not yet a live feed.
run_agent_check.py automatically picks up the latest stored snapshot per
symbol when scoring, so once a CSV is loaded it factors into every run.

## Price Momentum / VSA Order-Flow-Proxy Layer (added 12 Aug 2026)
`price_momentum.py` implements Volume Spread Analysis (VSA) — reads EFFORT
(volume) vs RESULT (candle spread + close position) to detect no-demand,
no-supply, buying/selling climax, and absorption patterns, which answer
"what happens inside price when orders/triggers hit" without needing true
Level-2 order-book data. Wired into engine.py for +1 point when it agrees
with the price/momentum signal direction. Max score now 9/10 (was 8/10).

**Current limitation**: NIFTY/BANKNIFTY index candles from GrowwMCP don't
include volume yet (indices aren't directly traded) — this layer correctly
reports NEUTRAL/no-signal until volume data is wired in (e.g. from
groww_api.py's fetch_candles(), which does return volume, or NIFTY futures
data). See memory/lessons.json -> price_momentum_vsa for full concept
documentation.
