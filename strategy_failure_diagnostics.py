"""
strategy_failure_diagnostics.py — WHY did this prediction/trade fail?
------------------------------------------------------------------------------
22 Aug 2026, per Saim's explicit analogy: exactly like inspect_dhan_csv.py
diagnosed the REAL reason a code-lookup was failing (wrong column-name
assumption) instead of just re-guessing, this module diagnoses the REAL
reason a trade's prediction/outcome missed — checking against a concrete,
evidence-based checklist of common AI-trading-agent failure modes
(researched 22 Aug from academic/industry sources: "feature/label
leakage, stale data, ignored costs, regime mismatch" — the Reflexion
pattern's guardrail checklist), not just recording "it was wrong."

Also implements the "adversarial review" principle from the same
research: a single model reviewing its OWN reasoning inherits the same
blind spots that produced the error — so this diagnostic explicitly
checks EXTERNAL, independently-computed factors (not "does this feel
right to the same logic that made the prediction"), similar in spirit
to an external auditor rather than self-reflection.
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DIAGNOSTIC_LOG_PATH = os.path.join(BASE, "memory", "strategy_failure_diagnostics.jsonl")

# Threshold below which a prediction counts as a genuine "miss" worth diagnosing
ACCURACY_MISS_THRESHOLD_PCT = 50


def diagnose_prediction_miss(trade, gex_regime_at_entry=None, gex_regime_at_exit=None,
                              volume_at_entry=None, avg_volume_baseline=None,
                              entry_to_now_minutes=None):
    """
    Given a CLOSED trade with a poor accuracy_pct (from
    prediction_accuracy_tracker), checks it against a concrete checklist
    of independently-verifiable failure factors — the "external audit"
    checks, not the same logic that made the original prediction.

    Returns a list of {factor, triggered, detail} — every factor gets
    checked (even if not triggered), so the diagnostic record is
    complete and consistently comparable across trades, not just a
    single guessed explanation.
    """
    findings = []

    # Factor 1: REGIME MISMATCH — did the GEX regime change between
    # entry and exit (e.g. started ACCELERATION, became PINNING mid-trade)?
    if gex_regime_at_entry and gex_regime_at_exit:
        regime_changed = ("ACCELERATION" in gex_regime_at_entry) != ("ACCELERATION" in gex_regime_at_exit)
        findings.append({
            "factor": "regime_mismatch",
            "triggered": regime_changed,
            "detail": f"entry_regime={gex_regime_at_entry[:20] if gex_regime_at_entry else None}, "
                      f"exit_regime={gex_regime_at_exit[:20] if gex_regime_at_exit else None}",
        })
    else:
        findings.append({"factor": "regime_mismatch", "triggered": None, "detail": "GEX regime data not available"})

    # Factor 2: LOW VOLUME / STALE ACTIVITY — was volume genuinely below
    # baseline at entry (matching our existing conviction-classification
    # concept, applied here specifically as a failure-explanation)
    if volume_at_entry is not None and avg_volume_baseline:
        ratio = volume_at_entry / avg_volume_baseline if avg_volume_baseline else 0
        low_volume = ratio < 0.8
        findings.append({
            "factor": "low_volume_at_entry",
            "triggered": low_volume,
            "detail": f"volume_ratio_vs_baseline={ratio:.2f}",
        })
    else:
        findings.append({"factor": "low_volume_at_entry", "triggered": None, "detail": "volume data not available"})

    # Factor 3: HOLD-TIME MISMATCH — did the trade need much longer than
    # the strategy's own design-window to develop (e.g. a "first-minute"
    # strategy that actually took 20+ minutes to resolve, suggesting the
    # underlying premise/timing assumption didn't hold that specific day)
    if entry_to_now_minutes is not None:
        strategy_type = trade.get("strategy_type", "")
        expected_window = 5 if strategy_type == "gamma_opening" else 30  # rough defaults per strategy design
        exceeded_window = entry_to_now_minutes > expected_window * 2
        findings.append({
            "factor": "hold_time_exceeded_design_window",
            "triggered": exceeded_window,
            "detail": f"actual_hold_minutes={entry_to_now_minutes}, expected_window={expected_window}",
        })
    else:
        findings.append({"factor": "hold_time_exceeded_design_window", "triggered": None, "detail": "timing data not available"})

    # Factor 4: NON-SUPPORTIVE LAYERS AT ENTRY — reuses existing
    # layer_status data already captured (same source shortfall_diagnosis
    # uses), consolidated into this single diagnostic record
    layer_status = trade.get("layer_status") or {}
    non_supportive = [layer for layer, status in layer_status.items() if status in ("disagree", "neutral")]
    findings.append({
        "factor": "non_supportive_layers_at_entry",
        "triggered": len(non_supportive) >= 2,
        "detail": f"non_supportive_layers={non_supportive}",
    })

    return findings


def log_diagnosis(trade_id, symbol, strategy_type, accuracy_pct, findings):
    """Permanently logs a diagnosis record — accumulates over time so
    review_common_failure_factors() can find PATTERNS across many
    trades, not just individual explanations."""
    entry = {
        "trade_id": trade_id, "symbol": symbol, "strategy_type": strategy_type,
        "accuracy_pct": accuracy_pct, "findings": findings,
        "logged_at": datetime.now().isoformat(),
    }
    with open(DIAGNOSTIC_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def review_common_failure_factors():
    """
    Aggregates ALL logged diagnoses — the actual answer to "which
    failure-factor is MOST OFTEN responsible when our predictions miss,
    across all strategies" — this is the pattern-level insight that
    individual trade diagnoses build toward over time.
    """
    if not os.path.exists(DIAGNOSTIC_LOG_PATH):
        return {"message": "No diagnostic data yet."}

    with open(DIAGNOSTIC_LOG_PATH) as f:
        entries = [json.loads(l) for l in f if l.strip()]

    if not entries:
        return {"message": "No diagnostic data yet."}

    from collections import defaultdict
    factor_trigger_counts = defaultdict(int)
    factor_total_counts = defaultdict(int)

    for e in entries:
        for finding in e["findings"]:
            if finding["triggered"] is not None:
                factor_total_counts[finding["factor"]] += 1
                if finding["triggered"]:
                    factor_trigger_counts[finding["factor"]] += 1

    report = {}
    for factor, total in factor_total_counts.items():
        triggered = factor_trigger_counts.get(factor, 0)
        report[factor] = {
            "triggered_count": triggered, "total_checked": total,
            "trigger_rate_pct": round(triggered / total * 100, 1) if total else None,
        }
    return {"total_diagnosed_trades": len(entries), "factors": report}
