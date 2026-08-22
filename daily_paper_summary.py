"""
daily_paper_summary.py — full report of a day's self-generated paper trades
------------------------------------------------------------------------------
Answers exactly Saim's 19 Aug question: "kal ke date mein kitne paper
trade liye? kya liye? kitna % tha?" — a clean, readable daily report
(not just aggregate stats) of every paper trade opened that day, its
entry/exit, outcome, and the day's overall win rate.

Run manually: python3 daily_paper_summary.py [YYYY-MM-DD]
(defaults to today if no date given)
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paper_trader import _read_all as read_paper_trades
from telegram_notify import send_telegram_message


def build_daily_summary(date_str):
    trades = [t for t in read_paper_trades() if t["date"] == date_str]

    # Volume Profile / POC summary (added 21 Aug 2026) — shown regardless
    # of whether any trades happened, since this is standalone useful data
    poc_lines = []
    try:
        from volume_profile_tracker import get_latest_daily_poc, get_current_rolling_poc
        for symbol in ["NIFTY", "BANKNIFTY"]:
            daily = get_latest_daily_poc(symbol)
            rolling = get_current_rolling_poc(symbol)
            if daily and daily["date"] == date_str:
                poc_lines.append(f"{symbol} Daily POC: {daily['poc_price']} (VA {daily['value_area_low']}-{daily['value_area_high']})")
            if rolling:
                poc_lines.append(f"{symbol} Contract POC: {rolling['poc_price']} (VA {rolling['value_area_low']}-{rolling['value_area_high']}, since {rolling['period_start']})")
    except Exception:
        pass

    if not trades:
        msg = f"<b>Paper Trade Summary — {date_str}</b>\n\nNo paper trades opened this day."
        if poc_lines:
            msg += "\n\n<b>Volume Profile:</b>\n" + "\n".join(poc_lines)
        return msg

    lines = [f"<b>Paper Trade Summary — {date_str}</b>", ""]

    closed = [t for t in trades if t["status"] == "CLOSED"]
    open_trades = [t for t in trades if t["status"] == "OPEN"]
    wins = [t for t in closed if t["outcome"] == "WIN"]
    losses = [t for t in closed if t["outcome"] == "LOSS"]

    for t in trades:
        entry_t = t["entry_time"][11:16]
        exit_t = t["exit_time"][11:16] if t.get("exit_time") else "—"
        outcome = t.get("outcome") or "OPEN"
        pts = t.get("outcome_points")
        pts_str = f"{pts:+.1f}pts" if pts is not None else "—"
        prem = t.get("estimated_premium_pnl")
        prem_str = f" (premium: {prem:+.1f})" if prem is not None else ""
        strat = t.get("strategy_type") or "?"
        opt = t.get("option_snapshot")
        opt_str = f" [{opt['strike']:.0f}{opt['option_type']}]" if opt else ""

        lines.append(f"• {t['symbol']} {t['signal']}{opt_str} | {strat} | entry {entry_t}@{t['entry_price']:.1f} "
                      f"→ exit {exit_t}@{t.get('exit_price', '—')} | <b>{outcome}</b> {pts_str}{prem_str}")

    lines.append("")
    lines.append(f"<b>Total: {len(trades)}</b> ({len(closed)} closed, {len(open_trades)} still open)")
    if closed:
        win_rate = round(len(wins) / len(closed) * 100, 1)
        net_pts = sum((t.get("outcome_points") or 0) for t in closed)
        net_prem = sum((t.get("estimated_premium_pnl") or 0) for t in closed if t.get("estimated_premium_pnl") is not None)
        lines.append(f"Win rate: {len(wins)}/{len(closed)} = <b>{win_rate}%</b>")
        lines.append(f"Net index points: {net_pts:+.1f}")
        if net_prem:
            lines.append(f"Net estimated premium: {net_prem:+.1f}")

    if poc_lines:
        lines.append("")
        lines.append("<b>Volume Profile:</b>")
        lines.extend(poc_lines)

    # Learning-loop review (added 22 Aug 2026, per Saim's identified gap
    # — this data was being collected but NEVER actually reviewed by
    # anything. Now included in every daily summary, closing that gap.)
    try:
        from paper_trader import review_shortfall_patterns
        from prediction_accuracy_tracker import review_prediction_accuracy_by_strategy
        shortfall = review_shortfall_patterns()
        pred_accuracy = review_prediction_accuracy_by_strategy()
        if shortfall.get("shortfall_trades", 0) > 0:
            lines.append("")
            lines.append(f"<b>Shortfall Review:</b> {shortfall['shortfall_trades']}/{shortfall['total_closed']} "
                          f"trades fell short ({shortfall['shortfall_rate_pct']}%), avg shortfall "
                          f"{shortfall['avg_shortfall_points']}pts")
        if isinstance(pred_accuracy, dict) and "message" not in pred_accuracy:
            lines.append("")
            lines.append("<b>Prediction Accuracy by Strategy:</b>")
            for strat, stats in pred_accuracy.items():
                lines.append(f"  {strat}: {stats['avg_accuracy_pct']}% accurate ({stats['trade_count']} trades, "
                              f"{stats['systematic_bias']})")
    except Exception:
        pass

    return "\n".join(lines)


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    report = build_daily_summary(date_str)
    print(report.replace("<b>", "").replace("</b>", ""))
    send_telegram_message("📋 " + report)
