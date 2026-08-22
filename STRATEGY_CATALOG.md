# Strategy Catalog — Order-Flow Related Concepts, One Box Each

Built 20 Aug 2026 per Saim's explicit instruction: every order-flow
concept should live in its own defined "box" — what timeframe it needs,
what data it needs, whether it CAN be backtested with what we have right
now, and if not, exactly what's missing. This is the reference document
the agent (and Claude, in future sessions) should check before assuming
capability that doesn't actually exist yet.

---

## BOX 1: RSI-Reversal (entry strategy)
- **Timeframe**: 1-min live signal, uses recent ~14-20 candles of history
- **Data needed**: price candles only (have this — live, 1-min, from Groww)
- **Backtestable now?**: YES — original 90-day backtest done, this is the
  current live baseline (42.9% WR, 1.67:1 R:R)
- **Status**: LIVE, actively trading

## BOX 2: Trend-Continuation (entry strategy)
- **Timeframe**: 1-min live signal, 4-5 candle alignment check
- **Data needed**: price candles only (have this)
- **Backtestable now?**: YES — tested against RSI-baseline (17 Aug),
  performed worse as a standalone trigger in that specific test
- **Status**: LIVE, actively trading (fires alongside RSI-reversal)

## BOX 3: VSA / Volume-Momentum (confirmation layer)
- **Timeframe**: 1-min
- **Data needed**: volume — index candles have NONE, so this uses
  FUTURES candles instead (have this — live, fixed 19 Aug to use
  correct MONTHLY futures expiry)
- **Backtestable now?**: PARTIALLY — futures volume is live now, but we
  don't have a long HISTORY of futures volume to backtest against
  (only from whenever this fix was deployed, 18-19 Aug onward)
- **Status**: LIVE as a confirmation layer, NOT yet backtested standalone

## BOX 4: SMC (BOS/CHoCH) (confirmation layer)
- **Timeframe**: works on whatever candle series it's given (currently 1-min)
- **Data needed**: price candles only
- **Backtestable now?**: YES for price-structure detection; tested
  standalone as a TRIGGER (not just confirmation) on 17 Aug — performed
  badly (-287.8pts) as a standalone signal, confirmed better suited as
  a confirmation layer (which is its current live role)
- **Status**: LIVE as confirmation only

## BOX 5: OI/PCR Lean (confirmation layer)
- **Timeframe**: refreshed every ~3 min live
- **Data needed**: live option chain (have this, live)
- **Backtestable now?**: NO — we don't have HISTORICAL option-chain OI
  data at fine time resolution, only live snapshots going forward from
  whenever each feature was built. **This is exactly the gap Saim's
  manual NSE downloads would fill.**
- **Status**: LIVE as confirmation, NOT backtestable yet (no history)

## BOX 6: Greeks/IV-Skew (confirmation layer)
- **Timeframe**: refreshed every ~3 min live
- **Data needed**: live option chain Greeks (have this, live, fixed 19 Aug
  — was built but never actually wired into scoring until that fix)
- **Backtestable now?**: NO — same reason as Box 5, no historical Greeks data
- **Status**: LIVE as confirmation, NOT backtestable yet

## BOX 7: FII/DII Flow (confirmation layer)
- **Timeframe**: daily (one number per day)
- **Data needed**: manual daily CSV upload from NSE (Saim provides this
  occasionally) — NO live feed exists
- **Backtestable now?**: NO — only 2 days of data ever recorded (12-13
  Aug), nowhere near enough
- **Status**: MOSTLY DORMANT — needs regular manual data to be useful at all

## BOX 8: Confidence Tiers (mechanical vs behavioral classification)
- **Timeframe**: applies to all the above, doesn't have its own timeframe
- **Data needed**: outcome data from paper trades (accumulates automatically)
- **Backtestable now?**: N/A — this is an ANALYSIS layer over other boxes'
  results, not a standalone strategy. Needs enough closed trades across
  boxes 1-7 to produce a meaningful tier-by-tier win-rate comparison.
- **Status**: LIVE (learning_loop.review_performance() reports this),
  but sample size is still small (few days of trades)

## BOX 9: Order-Flow-Depth (5/20-level bid-ask)
- **Timeframe**: would refresh every ~3 min if working
- **Data needed**: live market-depth API access
- **Backtestable now?**: NO — Groww's version is broken (GA001 errors,
  escalated to support, ticket #27379948). Dhan's version (20-level) is
  built and connection-tested successfully but not yet confirmed
  receiving live tick data (tested after-hours on 20 Aug, needs a
  market-hours retest).
- **Status**: NOT YET LIVE on either broker — this is the most
  actively-being-debugged box right now

## BOX 10: Footprint Proxy (sampled buyer/seller aggression)
- **Timeframe**: samples every ~3 min (piggybacks on Box 9's fetch cycle)
- **Data needed**: same live-quote data as Box 9 — so this is BLOCKED
  until Box 9 works on at least one broker
- **Backtestable now?**: NO — no historical tick data exists to replay,
  and live sampling hasn't been running long/reliably enough yet
- **Status**: BUILT but effectively DORMANT until Box 9 is resolved

## BOX 11: FVG-Touch Reaction (SMC-derived pattern)
- **Timeframe**: 1-min, checks across a rolling ~100-candle lookback
- **Data needed**: price candles only (have this)
- **Backtestable now?**: YES, but only against the SAME short window of
  intraday data we have (~15-20 days) — not enough for a statistically
  confident answer yet, needs more days of accumulation (automatic, no
  extra data-sourcing needed — just time)
- **Status**: LIVE, actively collecting data, too early to review results

## BOX 12: Session-Behavior (regular vs extended-session range split)
- **Timeframe**: once/day, end-of-day analysis
- **Data needed**: price candles only (have this)
- **Backtestable now?**: YES against the ~15-20 days we have live, but
  again — needs more days for a confident pattern
- **Status**: LIVE, actively collecting data

## BOX 13: Multi-Timeframe Context (30-min trend)
- **Timeframe**: 30-min candles, refreshed once/day
- **Data needed**: price candles only (have this, ~5 days lookback fetched daily)
- **Backtestable now?**: YES for the trend-read itself; NOT yet tested
  for whether "aligned with higher timeframe" trades actually perform
  better (needs enough trades tagged with this context to compare)
- **Status**: LIVE (fixed 20 Aug, working), too early to review

## BOX 14: Order-Size Anomaly (z-score spike detection)
- **Timeframe**: samples every ~3 min (piggybacks on Box 9/10's cycle)
- **Data needed**: same as Box 9 — BLOCKED until depth data works
- **Backtestable now?**: NO — no historical order-book size data exists
- **Status**: BUILT but DORMANT until Box 9 resolved

---

## THE HONEST SUMMARY (what Saim's question was really asking)

**Boxes genuinely live AND actively learning from real trades**: 1, 2
(the two entry strategies actually generating the trades Saim sees)

**Boxes live as confirmation but too new to have a real answer yet**: 3,
4, 5, 6, 8, 11, 12, 13 — these are all TURNED ON and collecting data, but
none has had enough TIME/VOLUME of trades yet to say "this genuinely
helps" or "this doesn't" with statistical confidence. This is not the
same as "not working" — it's "not old enough to judge yet."

**Boxes that need data Saim hasn't provided yet**: 5, 6, 7 need
HISTORICAL option-chain/OI/Greeks data to backtest (only have live
going-forward data) — this is exactly what Saim's offered manual NSE
downloads would unlock.

**Boxes completely blocked on the depth-data bug**: 9, 10, 14 — these
can't do ANYTHING (live or backtest) until Box 9 (order-flow-depth) is
fixed on either Groww or Dhan.

**Direct answer to "kitne signal aaye but sirf 2-3 trade khuli"**: this
was a genuine BUG (alert-dedup vs paper-trade-dedup used different
rules) — fixed 20 Aug, see git log. Not the agent being inconsistent —
two different pieces of code disagreeing about what counts as "a new
signal."

## BOX 16: POC-Reaction Strategy (entry strategy, added 21 Aug 2026)
- **Timeframe**: 1-min live signal, tests price against rolling contract-period POC
- **Data needed**: futures candles+volume (have this, live) → volume_profile_tracker.py's POC
- **Backtestable now?**: YES — tested against 12-17 Aug real data. Edge-triggered:
  18 signals over 6 days (vs 39 before edge-triggering fix). Correctly generated
  3 LONG-bounce signals on 17 Aug's morning/midday (genuine short-term bounces),
  which the built-in fail-safe SL (placed just beyond POC, not a fixed point
  distance) would have caught when the level finally broke down decisively
  that afternoon (-140 to -166pt continuation).
- **Design principle (direct answer to "what happens if the strategy is wrong")**:
  SL sits just beyond the POC level itself. A loss on this strategy specifically
  means "the level failed" — which per the 17 Aug data is exactly when a large
  continuation move tends to follow, so the SL naturally limits exposure right
  at the point the core assumption breaks, rather than fighting a breakdown.
- **Status**: LIVE, tagged as strategy_type="poc_reaction" — independent of
  RSI-Reversal/Trend-Continuation (Boxes 1-2), tracked separately in
  learning_loop so its own win-rate can be judged on its own merits.

## BOX 17: LTF Volume Microburst Detector (observational, added 21 Aug 2026)
- **Timeframe**: 1-min, checks each new futures candle against a 20-period volume EMA baseline
- **Data needed**: futures candles+volume (have this, live — already fetched for VSA/Box 3, no extra API calls)
- **Backtestable now?**: PARTIALLY — logic verified via synthetic test (correctly
  flagged an injected 6.5x-volume directional spike), but real historical
  verification is limited since our saved 15-day dataset only has close+volume
  (no OHLC), so directional-efficiency couldn't be tested against real data yet.
  Live data (fetch_candles) has full OHLC, so this works correctly going forward.
- **Origin**: synthesized from two TradingView indicators discussed 21 Aug
  (Leviathan's Market Sessions/Volume Profile — already Box implemented;
  Zeiierman's LTF Volume Microburst Bubbles) combined with the SEBI/Copthall
  CAS-manipulation case mechanics (three 2-13-second concentrated spikes, one
  entity dominating 99%+ of order value in each).
- **Honest scope limitation**: detects volume-CONCENTRATION anomalies only.
  Does NOT detect the order-CANCELLATION-rate pattern SEBI found (place huge
  orders, cancel ~a third after price moves) — that needs order-book-level
  data (order-flow-depth, still blocked). This is the "volume spike" half of
  the mechanism, not the "spoof and cancel" half.
- **Status**: LIVE, observational only (prints detection, doesn't yet feed
  a trading signal or paper trade) — a detection layer to build on, not a
  strategy yet.

## BOX 18: Time-Adaptive SL/Target (risk-management layer, added 21 Aug 2026)
- **Origin**: Saim's observation, TESTED against real 4-day 1-min NIFTY data
  (only continuous days available: 10, 11, 12, 21 Aug) — CONFIRMED: morning
  (9:15-11:00) avg 4.09pts/min movement, midday (11:00-14:00) avg 2.54pts/min
  (~38% less), afternoon (14:00-15:15) avg 3.16pts/min. Consistent across
  ALL 4 available days.
- **What it does**: scales SL/target by time-of-day multiplier (1.25x morning,
  0.78x midday, 0.97x afternoon), preserving the ~1.67:1 reward:risk ratio
  while sizing absolute point-distances to match actual typical movement
  in that window — directly addresses Saim's flagged symptom ("trades just
  show losses") where a fixed 15/25 SL/target mismatched midday's lower
  volatility (price drifts without cleanly reaching either level).
- **Honest limitation**: calibrated from only 4 days — should be
  RECALIBRATED as more data accumulates (now easy via auto_sync_data.py's
  daily GitHub push).
- **Status**: LIVE as of 21 Aug, applied to every new paper trade.

## BOX 16 UPDATE (21 Aug 2026): Initiative vs Responsive Mode Added
Per Saim's explicit instruction to research Market Profile theory in
depth (multiple sources verified) and implement carefully (16 test
scenarios run before wiring live — synthetic + real historical data,
covering IB computation at multiple candle-resolutions, balance/
imbalance classification, and initiative-mode continuation signals
cross-checked against the known 17 Aug breakdown pattern):

**New modules**: initial_balance.py (first-hour IB range + volume-
supported breakout detection — the EARLIEST, most actionable day-type
signal per Dalton's Market Profile theory), volume_profile.classify_balance_imbalance()
(POC position within the day's range — center=balanced/mean-reversion-
favorable, edge=imbalanced/trend-favorable, matching p-type/b-type
patterns from Market Profile theory), poc_reaction_strategy.determine_trade_mode()
(combines IB-breakout + balance/imbalance classification into a single
RESPONSIVE/INITIATIVE/NEUTRAL decision), check_poc_reaction_signal_v2()
(mode-aware: RESPONSIVE fades bounces off POC as before; INITIATIVE
trades WITH confirmed continuation away from POC instead of fading it).

**Key research finding applied**: a volume-supported Initial Balance
breakout is the STRONGEST, EARLIEST signal (available within the first
hour) — prioritized over the slower end-of-day balance/imbalance read.
Also found: a day can appear "balanced" in full-day aggregate stats
while still containing a genuine late-session imbalance/breakout (17
Aug's own daily classification came back BALANCED despite its known
afternoon breakdown) — this is WHY the real-time IB-breakout check
matters alongside, not instead of, the end-of-day classification.

**strategy_type now tags the mode explicitly**: "poc_reaction_responsive"
or "poc_reaction_initiative" — so their win-rates can be tracked and
compared SEPARATELY once enough trades accumulate (a genuinely testable
question: does Initiative-mode or Responsive-mode perform better, and
under what conditions).

## BOX 19: Naked POC Tracker (added 21 Aug 2026)
- **Origin**: per Saim's instruction to research Naked POC theory in depth
  first, then implement carefully. Verified from multiple sources: a Naked
  POC (virgin POC/NPOC) is a prior session's Point of Control price has
  NOT traded back through since — ~80% get revisited within 10 sessions
  (the "magnet effect" — unresolved institutional interest at that price).
- **What it does**: get_naked_pocs() scans all historical daily POCs
  (from volume_profile_tracker's log), checks each against ALL subsequent
  days' high/low ranges (via a lightweight day_range_log.jsonl, avoiding
  re-fetching historical candles) to determine which remain unretested.
  Sorted by sessions_unvisited (longer unvisited = stronger pull per theory).
  check_naked_poc_proximity() flags when current price is near one.
- **Three use-cases from research (documented, not all wired as trading
  signals yet)**: (1) TARGET — nearby naked POC in trade direction as
  take-profit, (2) ENTRY ZONE — first test often gets a sharp reaction
  (SL beyond level), (3) BREAKDOWN — if it fails to hold, trade the
  continuation (reuses our Initiative/Responsive framework from Box 16).
- **Tested (3 scenarios)**: synthetic naked/tested classification,
  proximity detection, end-to-end with log_day_range/load_day_ranges
  helpers — all passed. Verified against real 12-day NIFTY data:
  correctly identified early-August POCs (24720, 24660, from before the
  known price decline) as still naked, consistent with the well-established
  downtrend pattern.
- **Status**: LIVE (computed daily in continuous_runner.py's EOD flow,
  printed for visibility) — NOT yet wired as an active trading signal
  (currently observational, printing top-3 naked POCs by age each day).

## BOX 19 UPDATE (21 Aug 2026): Full Trading-Signal Integration Live
Per Saim's "kar do ise" (do it) — naked POC is now a full 4th entry
strategy (alongside RSI-Reversal, Trend-Continuation, POC-Reaction):
check_naked_poc_signal() combines all 3 research use-cases —
ENTRY-ZONE reaction (mode-aware, reuses check_poc_reaction_signal_v2),
BREAKDOWN continuation (via the same Initiative/Responsive trade_mode),
and TARGET suggestion (further naked POCs in the trade direction,
returned as suggested_targets — a statistically-grounded take-profit
option, ~80% historical revisit rate, vs an arbitrary fixed distance).
5 test scenarios (RESPONSIVE bounce, INITIATIVE breakdown, no-nearby-POC
edge case, target-suggestion correctness) all passed before wiring live.
strategy_type="naked_poc" for independent win-rate tracking. Wired with
its own edge-triggered signal state, Telegram alert, and paper-trade
opening — parallel to (not replacing) the rolling-POC reaction strategy.

## NEW: Systematic Backtest Harness (backtest_harness.py, 21 Aug 2026)
Per Saim's #1-of-5 sequential priority — the biggest structural gap
identified 20 Aug. run_harness() replays a FIXED dataset candle-by-candle
through the REAL, CURRENT engine.score_setup() (no reimplementation —
genuinely reflects live strategy code), no-lookahead (only past-visible
data at each point), edge-triggered entry (matches live logic), EOD
force-close (bug found+fixed during testing — without this, trades
carried across overnight gaps unrealistically, inflating trade-count
from documented ~1.5/day to 3/day). log_harness_run() saves before/after
comparable summaries.

8 tests run before considering this done: syntax, basic execution, a
real bug found via manual trade-trace (EOD carry-over) and fixed,
re-verification, determinism (2 identical runs), dataset-sensitivity
(5-min vs 15-min timeframe genuinely different results, as expected),
tiny-dataset edge case (fails gracefully), and the logging mechanism.

**HONEST FINDING**: the original "42.9% WR / 90-day backtest" baseline
CANNOT be reproduced — its source dataset (nifty_5min_90d.json) was
never committed to git (.gitignore excluded it, size reasons) and no
longer exists anywhere accessible. Current harness result on the
available 15-day Aug 2026 dataset: 29 trades, 31.0% WR, -76pts — this
is a REAL, reproducible number for THIS specific dataset, but not
directly comparable to the old unverifiable claim. Going forward, THIS
harness run (logged as a proper baseline) is what future strategy
changes get compared against — not the old, now-unreproducible number.

## NEW: Risk Agent + Portfolio Agent (risk_agent.py, portfolio_agent.py, 21 Aug 2026)
Per Saim's #2-of-5 sequential priority. Researched standard position-
sizing methods (Fixed Fractional chosen — industry-standard 1-2%
risk-per-trade, doesn't need reliable win-rate history unlike Kelly).

**risk_agent.py**: compute_position_size() — num_lots = floor(risk_amount
/ premium_risk_per_lot), where premium_risk_per_lot = index_SL_points *
abs(Delta) * lot_size. 6 tests: manual math verification, BANKNIFTY lot
size, tiny-capital edge case, zero-input edge cases, negative-Delta (PE
options) handling, custom risk_pct.

**portfolio_agent.py**: check_correlation_risk() (flags NIFTY+BANKNIFTY
open in the SAME direction as concentrated risk, not diversification —
both are correlated broad-India-index bets), check_can_open_new_position()
(gatekeeper: max concurrent positions=2, max total capital-at-risk=2.5%
across all open positions, correlation warning non-blocking). 6 tests:
correlation detection both ways, single-position edge case, 3
gatekeeper scenarios (block-on-max-positions, block-on-total-risk,
allow-within-limits).

Wired into ALL 3 continuous_runner.py trade-opening call sites (main
RSI/Trend-Continuation, POC-Reaction responsive+initiative, Naked-POC)
via a new paper_trader.get_all_open_positions() helper — every new
trade now checks Portfolio Agent limits BEFORE opening, consistently
across all 4 strategies (avoiding duplicated logic). Currently uses a
default simulated ₹100,000 account capital (paper-trading — real
capital tracking is a future step once live trading begins).
15 total tests run before considering this item done.

## BOX 17 REDESIGN COMPLETE (21 Aug 2026): Microburst Now a Confirmation Layer
Per Saim's #3-of-5 priority — implements the redesign proposed (but
unvalidated) earlier same day: LTF Microburst is no longer a standalone
strategy — it's a CONFIRMATION signal for POC-Reaction trades.
get_microburst_confirmation() in poc_reaction_strategy.py: when price
approaches POC, checks if the latest candle's microburst fires OPPOSITE
to the approach direction (fresh counter-pressure → CONFIRMS_BOUNCE) or
SAME direction (continuing conviction → CONFIRMS_BREAKDOWN). 6 tests
(all 4 direction/burst combinations, no-microburst case, None-safety)
plus 1 real-data run (17 Aug, ran cleanly though inconclusive due to
known test-dataset OHLC limitation). Wired into continuous_runner.py's
POC-reaction check — informational for now (logged + shown in Telegram
alert), not yet gating the trade (observing before hard-gating, day 1
of this integration).

## BOX 15 COMPLETE (21 Aug 2026): Range-Breakout-from-Consolidation Detector
Per Saim's #4-of-5 priority. Origin: 20 Aug's manual chart review found
a genuine ~47pt NIFTY missed move (24,217→24,264, 12:40-12:50PM) that
neither RSI-Reversal (needed prior oversold-recovery) nor Trend-
Continuation (needed already-aligned momentum) could catch — a
genuinely different pattern: sudden breakout FROM a tight consolidation.

range_breakout.py: detect_consolidation() (is the recent N-candle range
genuinely tight — "coiled spring" precondition) + detect_range_breakout()
(has price now moved decisively beyond that range, filtering small
noise-pokes via a confirmation-point buffer). 7 synthetic tests +
**1 CRITICAL verification test: recreated Saim's EXACT documented 20
Aug numbers (consolidation ~24,210-24,217, breakout to 24,264) —
CONFIRMED this detector would have caught the exact move that started
this whole investigation.** 5th independent entry strategy
(strategy_type="range_breakout"), wired with edge-triggering, Portfolio
Agent gate, Telegram alert — same rigor as Boxes 16/19.

## BOX 20: Gamma-Opening Strategy (6th entry strategy, added 22 Aug 2026)
- **Origin**: extensively cross-validated research this session — 8 instruments
  (NIFTY, BANKNIFTY, SENSEX + top-5 NIFTY stocks), 43 days each, ALL showing
  the identical structural pattern: morning-dominant, 09:15's first minute
  captures ~2/3 of the entire 5-minute opening window's total movement.
- **What it does**: combines the VERIFIED first-minute-dominance timing with
  EXISTING live GEX regime detection (ACCELERATION=amplifying vs
  PINNING=dampening). Only fires on ACCELERATION days with a clear directional
  first candle (>3pt move, filters flat/indecisive opens). Target = the
  VERIFIED historical average first-minute move for that specific instrument
  (NIFTY=26.7pts, BANKNIFTY=105.1pts) — NOT a guessed fixed number, per
  Saim's explicit rejection of arbitrary targets. SL = half the target.
- **Tested**: 6 scenarios (PINNING-skip, ACCELERATION+up, ACCELERATION+down,
  flat-open-skip, boundary case) — all passed.
- **Status**: LIVE, runs once daily (09:16-09:19 window, after the 09:15
  candle completes), tagged strategy_type="gamma_opening" for independent
  win-rate tracking. This is the strategy that will build the "genuine
  opinion" (Saim's words) on whether the gamma-explosion premise holds up
  in continuous live paper-trading, not just historical backtest.

## GAP FIXED (22 Aug 2026): Prediction-vs-Reality Tracking + Shortfall-Review Now Actually Runs
Per Saim's identified gap — code-audit confirmed review_shortfall_patterns()
existed but was NEVER called by anything (pure dead infrastructure), and
estimated_premium_pnl was post-facto only, no explicit "predicted X vs
got Y, how accurate" comparison ever computed.

**prediction_accuracy_tracker.py**: logs Delta/Gamma inputs at trade-open,
computes expected premium move at trade-close, compares against actual.
**Critical design distinction (Saim's explicit correction)**: uses
Delta+Gamma 2nd-order Taylor (groww_option_chain.estimate_premium_move's
formula) specifically for gamma_opening strategy trades (whose entire
premise IS gamma-driven amplification beyond plain Delta — using
plain-Delta as the "expected" baseline would make this specific strategy
look wrong even when working exactly as designed), plain Delta for all
5 other strategies. 7 tests passed, including a test explicitly
recreating Saim's "15pt move → 47pt-scale premium via Gamma" scenario.

Both review_shortfall_patterns() and review_prediction_accuracy_by_strategy()
now actually get called — wired into daily_paper_summary.py's Telegram
report, so this data gets SEEN every day going forward, not just collected.

## NEW: Strategy-Failure Diagnostics + Adversarial-Review Principle (22 Aug 2026)
Per Saim's direct analogy: exactly like inspect_dhan_csv.py diagnosed the
REAL reason a code-lookup was failing (rather than re-guessing), this
diagnoses the REAL reason a trade's prediction misses — researched from
academic/industry AI-trading-agent literature: (1) "self-reflection
inherits the generator's prior" — a model reviewing its own reasoning
reuses the same blind spots that caused the error; external/independent
checks work better; (2) concrete common failure-mode checklist from the
Reflexion pattern: "feature/label leakage, stale data, ignored costs,
regime mismatch."

strategy_failure_diagnostics.py: diagnose_prediction_miss() checks a
CLOSED trade against 4 independently-verifiable factors (regime_mismatch,
low_volume_at_entry, hold_time_exceeded_design_window, non_supportive_
layers_at_entry) — every factor checked and recorded even if not
triggered, for a complete/comparable diagnostic record. review_common_
failure_factors() aggregates across all diagnosed trades to find which
factor is MOST OFTEN responsible. 6 tests + 1 real bug found-and-fixed
during integration testing (a `strategy_type` variable-scope bug,
caught via the exact same "test, find error, fix" discipline being
implemented here).

Auto-triggers whenever a closed trade's prediction accuracy is below
50% (ACCURACY_MISS_THRESHOLD_PCT). Wired into paper_trader.py's trade-
close logic and daily_paper_summary.py's Telegram report.

HONEST GAPS noted for future improvement: gex_regime_at_exit and
volume_at_entry aren't currently threaded through to the diagnostic
call site (only gex_regime_at_entry and hold-time are genuinely live) —
flagged in code comments, not silently assumed complete.
