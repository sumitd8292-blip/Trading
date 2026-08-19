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

## Six New Learning Hypotheses Structured (18 Aug 2026)
Per Saim's explicit request — the agent now tracks multiple specific,
well-defined questions instead of one undifferentiated outcome pool:

1. **Real premium P&L** (paper_trader.py): each paper trade now captures
   an option snapshot (strike/Delta/Theta) at entry, and computes
   estimated real premium P&L (Delta move + Theta decay over actual
   hold time) alongside the raw index-point P&L — `review_premium_pnl()`
   shows how much these diverge.
2. **Time-of-day performance** (`review_by_time_and_strategy()`): breaks
   down win rate by entry hour — does signal quality vary across the day?
3. **FII/DII price-impact timing** (fii_price_impact_tracker.py): same
   pattern as divergence_tracker.py — logs FII lean daily, checks over
   subsequent days whether price actually moved 30+ pts in FII's implied
   direction, and how long it took. Only activates on days Saim provides
   FII/DII figures (still manual, no live feed).
4. **Post-close momentum prediction accuracy**
   (post_close_accuracy_tracker.py): logs each day's gap-bias prediction,
   checks the next morning's actual open against it — the real answer to
   "does this actually predict next-day gaps".
5. **Reversal vs trend-continuation, by regime**: paper trades are now
   tagged with `strategy_type` (which entry logic fired), and
   `review_by_time_and_strategy()` cross-tabs strategy_type x entry_hour
   so the agent can eventually see which approach wins in which
   conditions.
6. **VIX effect on signal quality**: continuous_runner.py now fetches
   India VIX every ~5 min (best-effort, `refresh_vix()`) and tags it onto
   each paper trade — once enough data accumulates, can check whether
   win rate degrades in high-VIX conditions.

Tested end-to-end (opened a tagged trade with option snapshot + VIX,
closed it, confirmed premium P&L, time/strategy breakdown, and index-vs-
premium comparison all compute correctly).

## VSA Layer Fixed — Real Volume via Futures (18 Aug 2026)
Confirmed live via GrowwMCP: NIFTY/BANKNIFTY INDEX candles have
`volume: null` on every single candle (indices aren't directly traded,
only their futures/options are) — this is a genuine, permanent
limitation, not a bug. Fixed by fetching FUTURES candles in parallel
(which DO have real volume, confirmed: e.g. 258050, 70200 units per
5-min bar) and feeding those into price_momentum.momentum_bias()
instead of the index candles. Falls back to index candles (still no
volume, VSA stays neutral) if the futures fetch fails for any reason.

## Option Volume Profile (added 18 Aug 2026)
Per Saim's point that options generate MORE day-trading volume than
futures — `compute_volume_profile()` in groww_option_chain.py now
reads live option VOLUME (distinct from OI): total call/put volume near
the money, PCR-Volume (activity-based, complementing PCR-OI which is
positioning-based), and the single most-active-by-volume strike on each
side. High volume + unchanged OI suggests active intraday trading
without new positioning; high volume + rising OI suggests fresh,
committed positioning. Wired into continuous_runner.py's option-chain
refresh cycle, logged alongside OI/GEX every ~5 min.

## Expiry-Close "Gamma Blast" Tracker (added 18 Aug 2026)
Encodes Saim's specific explanation of the pinning-release pattern: all
day, option sellers write heavily near ATM (confirmed live today —
massive dual-side OI buildup at 24200-24250), suppressing natural price
movement. In the FINAL MINUTES before close, as sellers close positions,
that suppressed momentum can release rapidly — a "gamma blast" where a
strike's premium can jump from ₹1-2 to ₹50-150+ in minutes.

`expiry_close_tracker.py`'s `analyze_close_window()` measures whether
this is real: compares average per-minute price movement in the last 15
min before close vs the day's whole-day average (an "acceleration
ratio"), and identifies which specific strike's premium moved the most
during the window. `review_acceleration_stats()` reports the
accumulated evidence across tracked expiry days.

Wired into continuous_runner.py: automatically captures an option-chain
snapshot at the start of the pre-close window (~15:15) and runs the
analysis right after market close, once per expiry day. Tested with
simulated accelerating-price data (correctly detected 9.95x
acceleration ratio).

## Two Critical Fixes to Expiry-Close Tracker (18 Aug 2026, same day)
1. **Timing bug fixed**: MARKET_CLOSE was hardcoded to 15:30 in
   expiry_close_tracker.py, but options/futures actually trade until
   15:40 (cash index closes ~15:15/15:30, options/futures continue) —
   the real gamma-blast window was being cut short, missing data.
   Fixed to 15:40, matching continuous_runner.py's own constant.
2. **Weekly-only vs combined-expiry tagging** (critical per Saim's
   warning): 25 Aug 2026 is the first date where NIFTY's weekly expiry
   AND BANKNIFTY's monthly expiry land on the SAME day — a combined
   expiry day's gamma-blast intensity is structurally different
   (expected bigger) than a normal weekly-only day. Pooling them
   together would corrupt the learned baseline and make future
   weekly-only days look "wrong" against an inflated combined-day
   average. analyze_close_window() now takes an expiry_type param
   ("weekly_only" vs "weekly_and_monthly_combined"), auto-detected in
   continuous_runner.py by checking whether more than one tracked
   symbol expires on the same date. review_acceleration_stats() reports
   these as separate breakdowns, never pooled.

## Two Bugs Fixed Per Saim's 19 Aug Live Alert Review
1. **Greeks/FII "NOT YET INTEGRATED" despite having live data**: found
   that continuous_runner.py's score_setup() call never actually passed
   greeks_bias or fii_bias parameters — engine.py was correctly
   reporting them as unavailable because, from its perspective, they
   truly were None, even though live Gamma/OI option-chain data and
   (when provided) manual FII data existed elsewhere in the codebase.
   Fixed: converts the already-fetched live option-chain rows into the
   flat format greeks_bias.compute_greeks_bias() expects and wires it
   in; also wires in fii_dii.get_latest_manual_fii_bias().
2. **Premium-move estimate improved (Delta+Gamma, not Delta-only)**:
   estimate_premium_move() now uses a proper 2nd-order Taylor
   approximation (ΔPremium ≈ Delta×ΔS + 0.5×Gamma×ΔS²) when Gamma data
   is available, meaningfully more accurate for larger moves than pure
   linear Delta. Theta intentionally still excluded here (it's a
   time-decay effect, not price-move — already handled separately in
   paper_trader.py's real premium P&L calc). Alert wording updated to
   reflect this.

## Critical VSA Bug Fixed: Futures Only Have Monthly Contracts (19 Aug 2026)
Found while reviewing why VSA might still show "no volume data" for
some weeks: continuous_runner.py's futures-fetch for VSA was using
_EXPIRY_CALCULATORS[symbol] (NIFTY's WEEKLY Tuesday expiry — correct
for OPTIONS) as the futures contract expiry. But NIFTY/BANKNIFTY index
FUTURES only exist as MONTHLY contracts (near/mid/far month) — there
is no such thing as a weekly futures contract (only options have weekly
expiry). Using a weekly date would silently fail to find a matching
futures contract on any week where that Tuesday wasn't also the
monthly expiry. Fixed: VSA's futures fetch now always uses
get_monthly_expiry() regardless of symbol, since that's the only valid
expiry type for futures contracts.

## Cooldown Added to Prevent Whipsaw Over-Trading (19 Aug 2026)
Saim caught 51 paper trades in a single day (expected ~1.5-3/day) —
root cause: no cooldown after a trade closed, so if the entry
condition was still barely true on the very next 1-min tick, a new
trade opened immediately, creating rapid open->SL->reopen churn in
choppy conditions. This explained a suspicious pattern: many tiny wins
(0.4-2pts, consistent with trailing SL barely triggering before
reversing) mixed with repeated exact -15pt losses (fixed initial SL),
and real premium P&L coming out poor/negative despite index-point P&L
looking mildly positive — high-frequency low-edge churn gets eaten by
real-world costs. Fixed: open_paper_trade() now enforces a 10-minute
cooldown after the last CLOSED trade for that symbol+date before a new
one can open. Tested: immediate re-entry attempt correctly blocked.

## Replaced Blunt Cooldown With Edge-Triggered Signals + Shortfall Diagnosis (19 Aug 2026)
Saim pushed back hard on the 10-min cooldown fix: "that's not learning,
that's just a rule you imposed — if it hits SL once, does that mean it
stops trying all day?" — a fair, sharp critique. Fixed properly:

1. **Edge-triggered entry** (replaces cooldown): the real bug was that
   engine.py's signal check is LEVEL-triggered (fires every tick a
   condition remains true) instead of EDGE-triggered (should fire once,
   when the condition freshly becomes true). continuous_runner.py now
   tracks each symbol's previous-tick signal and only opens a new paper
   trade when the signal actually TRANSITIONS into LONG/SHORT — a
   continuously-true signal doesn't keep re-triggering entries. This is
   a correction to what "a new signal" actually means, not an arbitrary
   time-based rule.

2. **Shortfall diagnosis** (the deeper learning Saim actually wanted):
   every closed trade now compares its actual move against the
   trending-move threshold (trail_trigger_points, 15 by default) — if
   it fell short, logs exactly WHICH layers (OI/VSA/SMC/Greeks/FII) were
   NOT supportive (disagree/neutral) at entry. `review_shortfall_patterns()`
   aggregates this across all trades: for each layer, what % of its
   non-supportive occurrences coincided with a shortfall — a real,
   data-backed answer to "does this layer's absence predict weak moves"
   instead of just WIN/LOSS. Tested end-to-end: correctly diagnosed a
   1pt-actual-vs-15pt-expected trade as having VSA+OI non-supportive at
   entry, and the pattern-review correctly aggregated it.

## Real Order-Flow / Depth Imbalance Tracking (added 19 Aug 2026)
Direct response to Saim's point: OI/PCR is a POSITIONING snapshot, not
real-time ORDER FLOW. His exact scenario — OI shows bullish, price
tries to rally, but heavy sell orders get punched at a level and absorb
the buying, so price stalls despite "bullish" positioning data.

`order_flow_depth.py` reads live 5-level bid/ask market depth
(`groww_api.fetch_quote_depth()`, endpoint `/v1/live-data/quote`) for
the ATM strike and computes a buy/sell quantity imbalance ratio.
`detect_absorption()` specifically flags when OI/PCR sentiment
DISAGREES with what the order book shows right now (e.g. OI bullish
but sell-side depth is heavier) — exactly Saim's described pattern.

Wired into continuous_runner.py's refresh cycle (every ~5 min alongside
option chain/VIX). Tested with real depth data fetched live today.
This is intentionally a SEPARATE signal from divergence_tracker.py
(which compares OI vs REALIZED price movement) — this compares OI vs
the actual order book in real time, a genuinely different microstructure
read.

## Order Flow Depth — All 5 Levels + Wall Detection (19 Aug 2026, refined)
Saim asked specifically: "does it use all 5 levels, or just the top?"
Previously only totalBuyQty/totalSellQty (whole-exchange aggregate) and
level-1 were captured. Fixed: now sums buy/sell quantity across ALL 5
visible price levels (visible_depth_ratio — the actionable, immediate
picture) and separately identifies the single HEAVIEST level on each
side (the "wall" — which exact price, how much size) since a large
order concentrated at one specific level, not spread evenly, is exactly
the manual-order-punching-defense scenario Saim described. Tested with
real depth data fetched today: correctly found a 5,330-qty sell wall at
50.50 causing SELL_HEAVY visible depth despite whole-book aggregate
looking roughly balanced — and correctly flagged absorption against a
BULLISH OI reading.

## Confidence Tiers + Absorption Outcome Tracking (19 Aug 2026)
Per late-session discussion with Saim about mechanical vs behavioral
signals: `confidence_tiers.py` classifies each layer as "mechanical"
(formula-driven — Greeks, SMC structure, VSA effort-vs-result — should
hold consistently, a wrong read is more surprising) or "behavioral"
(reflects a guess about other participants' intent — OI positioning,
FII/DII flows — expected to be wrong sometimes since it's not a
formula). `learning_loop.review_performance()` now reports a
confidence_tier_summary breaking down win rate by tier — the actual
test of whether mechanical signals really are more reliable than
behavioral ones, once enough data accumulates.

`absorption_tracker.py` (same pattern as divergence_tracker.py) tracks
whether order_flow_depth.py's absorption detections actually resolve in
OI's favor or the order-book wall's favor — logs each absorption event,
checks over the next 2 hours whether price moves 15+pts toward OI's
implied direction (OI_WON) or the wall's direction (WALL_WON), or times
out (INCONCLUSIVE). `review_absorption_stats()` reports the real
win-rate of this behavioral-tier signal. Wired into continuous_runner.py.
Tested end-to-end (correctly logged and resolved a simulated event).

## Four New Learning Modules — 19 Aug 2026 Late-Session Discussion
Systematic implementation of everything discussed:

1. **order_size_anomaly.py** — statistical (mechanical-tier) detection of
   order sizes that are outliers vs a rolling baseline, per Saim's "news
   is lagging, big capital moves first" insight. Flags order-book size
   spikes (z-score based) independent of any news explanation.

2. **multi_timeframe_context.py** — computes daily + 1-hour EMA-trend
   context so 1-min signals can be tagged as WITH or AGAINST the
   higher-timeframe trend (e.g. NIFTY's multi-week decline since 24-Jul).
   Refreshed once/day (higher timeframes don't need per-minute updates).

3. **fvg_touch_tracker.py** — tracks what happens when price returns to
   touch a previously-detected FVG (smc.py's find_recent_fvgs): does it
   REJECT or CONTINUE through, and does VSA at the touch moment predict
   which. Directly closes the loop on today's live example (NIFTY
   touched an 18-Aug gap zone at 24228, then rejected hard to 24078).

4. **session_behavior_tracker.py** — daily comparison of regular cash-
   session price range vs the extended 15:15-15:40 options/futures
   window, formalizing today's finding that the day's most dramatic move
   happened specifically in that extended window (confirmed: LTP's
   regular-session high/low of 24172.85/24025.65 vs the full including-
   extended-session range of 24228.05/23956.85).

All four wired into continuous_runner.py's main loop. Tested end-to-end
(all 4 modules pass with realistic simulated data).
