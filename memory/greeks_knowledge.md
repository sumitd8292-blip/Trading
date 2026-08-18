# Greeks Knowledge Base — Individual + Combined Interpretation

Built 18 Aug 2026 per Saim's explicit instruction: the agent needs to
understand WHY things happen, not just detect WHAT is happening. This
is background knowledge the agent's reasoning should draw on when
interpreting live Greeks/OI data — not a mechanical rule, a mental model.

---

## PART 1: Individual Greeks — what each one measures alone

**Delta** — how much an option's premium moves per ₹1 move in the
underlying. Roughly: 0.50 delta = premium moves ₹0.50 for every ₹1 the
index moves. Delta also serves as a rough market-implied "probability
of finishing ITM" — a 0.30 delta option is priced as if there's ~30%
chance of expiring in-the-money. Calls: 0 to +1. Puts: 0 to -1.
ATM ≈ 0.50, deep ITM → 1.0, deep OTM → 0.

**Gamma** — the RATE OF CHANGE of Delta itself. High gamma means Delta
will shift fast as price moves — the option's sensitivity is
accelerating, not constant. Gamma peaks at-the-money and near expiry
(time compresses the probability distribution around the strike).
Gamma alone tells you nothing about direction — only about how fast
sensitivity is changing.

**Theta** — time decay: how much premium erodes per day, all else
equal. Always negative for option BUYERS (works against you), positive
for option SELLERS (works for you). Theta accelerates as expiry
approaches, especially for ATM strikes — this is why a naked long option
held for only minutes can still lose value even if the underlying moved
favorably (theta ate the gain).

**Vega** — sensitivity to a 1% change in Implied Volatility (IV).
High vega = premium reacts strongly to changing volatility expectations,
independent of price direction. Vega matters most for longer-dated
options; it shrinks as expiry nears (less time for volatility to matter).

**IV (Implied Volatility)** — the market's own expectation of future
volatility, priced INTO the option. Rising IV inflates premiums even if
price doesn't move (fear/uncertainty pricing); falling IV deflates them
("IV crush" — commonly seen right after an event like results/expiry
passes and uncertainty resolves).

---

## PART 2: Two Greeks together — what the combination reveals

- **Delta + Gamma**: high gamma near a strike means Delta will swing
  fast as price approaches it — a small move can suddenly make an OTM
  option behave like an ATM one (rapid premium acceleration). This is
  the mechanical basis of a "gamma blast" — NOT random, it's the direct
  consequence of gamma being highest right at/near the current spot,
  especially close to expiry.
- **Theta + Gamma** (the core expiry-day tension): near expiry, Theta
  decay is severe AND Gamma is highest. This is a two-edged sword — if
  price sits still, Theta destroys the option fast; if price moves
  sharply, Gamma-driven delta acceleration can outrun that decay. This
  is WHY expiry-day options trading is simultaneously the highest-decay
  and highest-acceleration environment — both effects are maximal at
  the same time, and which one wins depends entirely on whether price
  actually moves.
- **Delta + IV**: an option's current premium reflects both directional
  exposure (delta) and volatility pricing (IV/vega). A strike with
  moderate delta but very high IV is "expensive" for its directional
  exposure — the premium has a lot of volatility-risk priced in beyond
  pure directional value.
- **Vega + IV**: rising IV inflates ALL premiums together, which can
  make a position look profitable even without a favorable price move —
  and falling IV (IV crush) can erase gains even with a favorable price
  move. This is why premium P&L and index-point P&L can diverge.

## PART 3: Three or more together — the fuller picture

Near an index expiry (WEEKLY for NIFTY/SENSEX, MONTHLY for BANKNIFTY —
see Part 4), the combination of (a) elevated Gamma concentrated near
spot, (b) accelerating Theta, and (c) often-compressing IV (uncertainty
resolving as expiry nears) together determine whether a given price move
translates into an outsized premium move or gets eaten by decay. Layer
in OI (OPEN INTEREST — not a Greek, but the "who's actually positioned
where" context) and this becomes readable as: which strikes have heavy
OI concentration (likely pin/resistance points — big option sellers
defend these), and whether Net GEX is positive (dealer hedging tends to
DAMPEN moves — "pinning") or negative (dealer hedging tends to AMPLIFY
moves — "acceleration"). All of this together is what `compute_gamma_exposure()`
in groww_option_chain.py already computes mechanically — this document
is the WHY behind that number, not a replacement for it.

## PART 4: Weekly (NIFTY/SENSEX) vs Monthly (BANKNIFTY) expiry dynamics

This matters because the SAME day-of-month can mean very different
Greeks behavior depending on which cycle a symbol is in:
- NIFTY/SENSEX are WEEKLY — every single week has its own build-up and
  decay of Gamma/Theta pressure. A NIFTY option is "near expiry" (high
  gamma/theta zone) far more often (every ~5 trading days) than BANKNIFTY.
- BANKNIFTY is MONTHLY (last Tuesday of the month, per Saim's 18 Aug
  correction) — for most of the month, BANKNIFTY options sit in a
  "calmer" Greeks regime (lower gamma, slower theta decay, more room
  for Vega/IV effects to matter) UNTIL the final few days before its own
  monthly expiry, when the same gamma/theta intensity NIFTY sees weekly
  compresses into BANKNIFTY's last days of the month.
- PRACTICAL IMPLICATION FOR LEARNING: when comparing "what happened" on
  a given day, the agent should always check WHERE in each symbol's OWN
  expiry cycle that day fell (days-to-expiry for NIFTY vs days-to-monthly-
  expiry for BANKNIFTY) — the same calendar date can mean "expiry day
  gamma intensity" for one symbol and "mid-cycle calm" for the other.
  This context (days-to-expiry per symbol) should be logged alongside
  any pattern/divergence observation so historical comparisons are
  apples-to-apples, not accidentally comparing a NIFTY expiry-day
  reading against a BANKNIFTY mid-cycle reading.

---

## What this means for the divergence-tracking hypothesis specifically

When `divergence_tracker.py` logs an OI-vs-price divergence event, the
Greeks/expiry context at that moment (Net GEX regime, days-to-expiry,
IV level) should be captured alongside it — because the SAME divergence
pattern likely behaves differently depending on whether it happens in a
high-gamma/near-expiry window (where price is more likely to snap
sharply once it moves) versus a calmer mid-cycle window (where moves may
be slower/smaller). Without this context, pooling all divergence events
together would blur two genuinely different regimes into one statistic.
