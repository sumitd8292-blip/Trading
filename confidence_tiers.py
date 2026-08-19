"""
confidence_tiers.py — mechanical vs behavioral signal classification
------------------------------------------------------------------------
Core insight from Saim's 19 Aug discussion: the agent currently treats
every layer's agreement/disagreement with equal weight — but some
signals are MECHANICAL (formula-driven, physics-like, should hold
consistently — e.g. Gamma increasing near expiry) while others are
BEHAVIORAL (reflect an assumption about what other market participants
intend to do — e.g. "OI/depth mismatch means someone is defending a
level on purpose") which can be right or wrong unpredictably since it
depends on human/institutional decisions, not a formula.

This is NOT about which layer is "better" — it's about calibrating how
much weight a correct/incorrect read from each layer should carry when
the agent reasons about confidence. A mechanical signal being wrong is
more surprising (formula should hold); a behavioral signal being wrong
is normal/expected some of the time (it's a probabilistic guess about
intent, not a law).

TIER = "mechanical": derived from a fixed formula/relationship that
       holds regardless of who's trading — Gamma increasing near
       expiry, Theta decay rate, IV-skew math, price-structure
       (BOS/CHoCH from pure swing geometry)
TIER = "behavioral": reflects an inference about OTHER PARTICIPANTS'
       intent or positioning, which could be wrong because it assumes
       a specific human/institutional decision — OI lean (assumes
       positioning predicts direction), order-book absorption
       (assumes a wall is deliberate defense, not just resting orders),
       FII/DII flows (assumes institutional flow predicts price)
"""

LAYER_CONFIDENCE_TIERS = {
    "greeks": "mechanical",   # IV-skew/Delta/Gamma math — formula-based
    "smc": "mechanical",      # BOS/CHoCH — pure price-swing geometry, no intent assumption
    "vsa": "mechanical",      # effort-vs-result (volume vs spread) — observational, not intent-guessing
    "oi": "behavioral",       # assumes OI positioning predicts direction
    "fii_dii": "behavioral",  # assumes institutional flow predicts price
}

# The two NEW order-flow modules built 19 Aug also get tiers:
EVENT_CONFIDENCE_TIERS = {
    "expiry_close_acceleration": "mechanical",  # Gamma rising near expiry — formula-driven
    "gamma_exposure_regime": "mechanical",      # GEX sign/magnitude — formula-driven
    "oi_price_divergence": "behavioral",        # assumes OI positioning will "win" eventually
    "order_book_absorption": "behavioral",      # assumes a resting wall is deliberate defense
}


def get_tier(layer_name):
    """Returns 'mechanical', 'behavioral', or 'unknown' for a given layer/event name."""
    return LAYER_CONFIDENCE_TIERS.get(layer_name) or EVENT_CONFIDENCE_TIERS.get(layer_name) or "unknown"
