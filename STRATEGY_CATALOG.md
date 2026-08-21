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
