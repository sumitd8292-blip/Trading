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

## FII/DII Layer — Manual Input (12 Aug 2026)
Automated NSE scraping was tried and abandoned: nseindia.com isn't
reachable from Claude's sandbox, and the `nsefin` library has an
unfixable-via-monkeypatch URL bug (frozen dataclass). Repeated automated
attempts also kept failing from GitHub Actions and spamming Telegram with
failure messages — removed.

Now uses manual entry (fii_dii.py): Saim provides the day's FII/DII net
figures from any source he trusts, Claude records them via
`record_fii_dii()` into memory/fii_dii_manual.jsonl. The runner
automatically picks up the latest recorded entry for scoring — same
reliable pattern as the options-OI CSV layer.

## Greeks / IV-Skew Layer (added 12 Aug 2026)
`greeks_bias.py` reads option Greeks (Delta, IV, Theta) fetched via
GrowwMCP's `get_greeks_for_fno_contract` and derives a directional lean
from **IV skew** between OTM calls and OTM puts at matching |delta|
(~0.3): higher OTM-put IV than OTM-call IV = downside-fear/hedging
demand = BEARISH; higher OTM-call IV = upside demand = BULLISH.

**GrowwMCP quirk discovered**: `get_greeks_for_fno_symbol` (whole-chain
query) returns an empty result — must query individual strikes via
`get_greeks_for_fno_contract` with explicit search_queries instead
(works reliably, can batch several strikes per call).

Wired into engine.py for +1 point when it agrees with the price signal.
Max score now 11 (was 10) — SMC structure layer is the last one still
pending, will raise this further once added.

Currently populated manually (same pattern as OI/FII-DII layers) via
`daily_store.append_greeks_snapshot()` — automating this requires a live
Claude session pulling fresh Greeks each day since GrowwMCP only works
inside chat sessions.

## SMC Layer (added 12 Aug 2026) — completes the 5-layer rubric
`smc.py` implements Smart Money Concepts using pure price action (no
volume needed — complements the volume-dependent VSA layer):
- **Swing points** (fractal highs/lows)
- **BOS** (Break of Structure — continuation) vs **CHoCH** (Change of
  Character — potential reversal, weighted 2x higher than BOS since it's
  the stronger signal)
- **FVG** (Fair Value Gaps) — 3-candle imbalances price often returns to

Wired into engine.py for +1 (BOS) or +2 (CHoCH) points. **Max score now
13** — all 5 planned layers (price+momentum, OI, VSA, FII/DII, Greeks,
SMC) are wired in.

## Alert labeling (12 Aug 2026)
Telegram alerts now show **CALL** for LONG signals and **PUT** for SHORT
signals (Saim's trading convention — buy Call to go long, buy Put to go
short), alongside the internal LONG/SHORT label for clarity.

## 1-Minute Data Collection (added 12 Aug 2026)
`daily_store.append_intraday_candles()` now supports `interval_label="1min"`
(previously only 5min was actually used, though the parameter existed).
Confirmed working: 1-minute NIFTY candles fetched via GrowwMCP (750-1125
candles for 1-3 trading days), stored under
`data/daily_store/{SYMBOL}_1min_log.jsonl`, and scored through the full
5-layer engine successfully. Saim's 11 Aug request for finer granularity
(market character shifting — more AI-driven trading, changing FII
patterns) is now technically supported.

Currently populated manually per Claude session (same GrowwMCP-only
limitation as live data generally) — automating this to run every minute
without a session open requires the VPS deployment (continuous_runner.py
already defaults to 1-minute loops, see deploy/deploy.md).

## Learning Loop (added 13 Aug 2026)
`learning_loop.py` closes the feedback cycle:
- `record_outcome(symbol, date, outcome, points, exit_reason)` — logs how
  an alerted signal actually played out (WIN/LOSS/BREAKEVEN/NO_TRADE)
- `review_performance()` — reads all outcomed trades and breaks down win
  rate by which layers agreed/disagreed/were neutral, surfacing
  plain-language suggestions (e.g. "SMC agreement correlates with 70% WR
  vs 45% overall — consider weighting it higher")

**Design choice**: this does NOT auto-adjust engine.py's scoring weights.
It surfaces evidence; Saim reviews and decides whether to change
weights — same "mutual consent" discipline carried over from FlowDesk.

engine.py's `score_setup()` now returns a structured `layer_status` dict
(agree/disagree/neutral/unavailable per layer) alongside the human-
readable `reasons` list, and `log_signal()` stores it — this is what
makes the per-layer performance breakdown possible without fragile text
parsing.

**Still needs**: Saim providing outcomes after signals play out (nothing
to review yet — sample size is 0 outcomed trades as of 13 Aug 2026).
