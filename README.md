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

## Trend-Continuation Detector (added 17 Aug 2026)
Direct response to Saim's live feedback: the RSI-reversal engine only
catches the SNAP-BACK after a trend exhausts (a mean-reversion detector)
— it structurally cannot fire during an ongoing sustained directional
move (e.g. market opens and sells off steadily, or rallies steadily for
hours). `trend_continuation.py`'s `detect_trend_continuation()` reads
recent candle-to-candle direction directly — if 4+ of the last 5 candles
move the same way with a meaningful net move, it fires IMMEDIATELY,
without waiting for any RSI extreme or reversal.

Wired into engine.py as a FALLBACK signal source: if the RSI-reversal
logic doesn't fire, trend-continuation is checked next (+4 pts). This
means the engine can now catch both reversal setups (range-bound/choppy
markets, smaller targets) and trend-continuation setups (sustained
directional runs, bigger targets) — Saim's exact distinction.

## Live Option Chain + Gamma Exposure (added 17 Aug 2026)
`groww_option_chain.py` replaces the old manual-CSV-upload OI/Greeks
workflow with ONE live API call (`groww_api.fetch_option_chain()` →
`/v1/option-chain/exchange/{exchange}/underlying/{underlying}`) that
returns the full strike chain with Greeks already included.

New capability: **Gamma Exposure (GEX)** — `compute_gamma_exposure()`
sums gamma × OI near the money to identify where dealer/market-maker
hedging concentrates. Positive net GEX suggests pinning (dampened
moves), negative suggests acceleration (amplified moves) — relevant for
expiry-day "gamma blast" analysis Saim asked about (18 Aug is NIFTY
expiry).

Response structure confirmed live via `inspect_option_chain.py`:
payload is `{"<strike>": {"CE": {...}, "PE": {...}}}`, each side having
`greeks` (delta/gamma/theta/vega/rho/iv), `ltp`, `open_interest`, `volume`.

Not yet wired into the continuous_runner's scoring loop — next step is
polling this periodically (e.g. every 5 min) and feeding gamma/OI/IV-skew
into engine.py automatically instead of the old manual snapshot flow.

## Self-Generated Paper Trading (added 17 Aug 2026)
Direct response to Saim's feedback: waiting for manual outcome reporting
is too slow. `paper_trader.py` makes the agent generate its OWN training
data continuously:
- Every time engine.py produces a real signal (regardless of whether a
  Telegram alert was sent or whether Saim actually takes the trade),
  `open_paper_trade()` records a virtual position with entry/SL/target
- Every subsequent loop tick, `check_open_trades()` checks the latest
  candle against open paper trades — if SL or target is hit, closes it
  and AUTOMATICALLY calls `learning_loop.record_outcome()` — no manual
  input needed
- At EOD, any still-open paper trade force-closes at the closing price

This means the learning loop now accumulates real WIN/LOSS/points data
every single trading day automatically, even on days Saim doesn't
personally trade — much faster than the original manual-reporting
design. Paper trades are explicitly separate from Saim's actual executed
positions (tracked in `positions.py`) — they're the agent's own
self-generated backtesting-in-real-time.

Wired into continuous_runner.py's main loop. Tested locally end-to-end
(open → target hit → WIN recorded → learning_loop updated) — works.

## Live Option Chain Wired Into Continuous Loop (18 Aug 2026)
continuous_runner.py now fetches LIVE option chain (OI/PCR + Gamma
Exposure) every ~5 loops (5 min), replacing the stale manual-CSV-upload
snapshot that was otherwise days old. Weekly expiry auto-detected via
get_next_tuesday_expiry() (both NIFTY and BANKNIFTY currently expire
Tuesdays — recheck this if NSE changes the expiry day again). Live OI
bias now feeds engine.py's scoring in place of the old manual snapshot
whenever available.

## Strike Suggestion in Telegram Alerts (added 18 Aug 2026)
Per Saim's request — alerts now include actionable option details, not
just the index-level signal:
- Suggested strike (ATM, matching signal direction — CALL for LONG, PUT
  for SHORT), sourced from the live option chain cache
- Current premium (LTP), Delta, IV of that strike
- Rough estimated premium move for the signal's SL-point distance
  (Delta-only linear estimate — explicitly flagged as ignoring
  Gamma/Theta, not a precise projection)

`groww_option_chain.py` gained `suggest_strike()` and
`estimate_premium_move()`. Tested with fake data matching confirmed
live structure — correctly picks nearest-to-spot strike and computes
delta-scaled premium move.

## Divergence Hypothesis Tracker (added 18 Aug 2026)
Per Saim's explicit instruction: the agent shouldn't just passively log
outcomes — it needs a specific, well-defined question to investigate, or
it'll "watch things happen and let them go" without learning anything
concrete.

`divergence_tracker.py` encodes ONE precise hypothesis: when the live
option-chain OI/PCR lean disagrees with the short-term price trend (e.g.
OI BULLISH while price is trending DOWN), does price eventually move in
OI's implied direction? If yes, how long does it take and how far does
it move? If it doesn't resolve within 3 hours or by EOD, that's also
logged as a valid data point ("OI didn't lead price that day").

This is PURE OBSERVATION — does not feed into engine.py's live scoring
(Saim was clear he doesn't want an active "divergence warning" signal
yet). `review_divergence_stats()` reports the accumulated evidence:
resolution rate, average time-to-resolve, average move size — once
enough events have been tracked, this gives a genuine data-backed
answer instead of a guess.

Wired into continuous_runner.py's main loop (detects + checks resolution
every tick). Tested end-to-end with simulated data (detected an event,
correctly waited through an unresolved check, then correctly resolved
it once price moved 20pts in OI's favor).
