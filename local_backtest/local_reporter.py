"""
local_reporter.py — Comprehensive Report generation for the local 1-year backtest.
Includes in-depth Day-by-Day performance analysis, Top Winning Days,
Quiet/Zero-Setup Days tracking, and full CSV exports.
"""

import csv
import logging
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("local_backtest")


def render_day_table(day_breakdown: dict) -> str:
    if not day_breakdown:
        return "  Is period mein koi zone qualify nahi hua.\n"
    lines = [
        f"  {'Date':<12} | {'Zones':>5} | {'Wins':>4} | {'Loss':>4} | {'BE':>3} | {'WinRate':>7} | {'Day P&L':>9} | {'Performance Note'}",
        f"  {'-'*12}-+-{'-'*5}-+-{'-'*4}-+-{'-'*4}-+-{'-'*3}-+-{'-'*7}-+-{'-'*9}-+-{'-'*20}",
    ]
    for day_str, d in day_breakdown.items():
        resolved = d["wins"] + d["losses"] + d.get("breakevens", 0)
        pnl_str = f"{d['pnl_r']:+.2f} R" if resolved > 0 else "  --  "
        wr_str = f"{(d['wins'] / resolved * 100):.0f}%" if resolved > 0 else " -- "
        
        note = ""
        if d["pnl_r"] >= 3.0:
            note = "★ Excellent Day"
        elif d["pnl_r"] > 0:
            note = "✓ Profitable"
        elif d["pnl_r"] <= -3.0:
            note = "✗ Heavy Drawdown Day"
        elif d["pnl_r"] < 0:
            note = "Minor Loss"
        elif d["zones"] > 0 and resolved == 0:
            note = "Pending / Incomplete"
        else:
            note = "Quiet Day"

        lines.append(
            f"  {day_str:<12} | {d['zones']:>5} | {d['wins']:>4} | {d['losses']:>4} | "
            f"{d.get('breakevens', 0):>3} | {wr_str:>7} | {pnl_str:>9} | {note}"
        )
    return "\n".join(lines) + "\n"


def render_month_section(month_key: str, market_type: str, metrics: dict, day_breakdown: dict, zones: list, selected_coins: list | None = None) -> str:
    m = metrics
    pf_str = f"{m['profit_factor']:.2f}" if m["profit_factor"] != float("inf") else "inf"
    resolved_count = m["wins"] + m["losses"] + m.get("breakevens", 0)
    win_rate_str = f"{m['win_rate_pct']:.1f}%" if resolved_count > 0 else "N/A"

    # Top winning days in this month
    winning_days = [
        (day, d) for day, d in day_breakdown.items() if d["pnl_r"] > 0 and (d["wins"] + d["losses"]) > 0
    ]
    winning_days.sort(key=lambda x: -x[1]["pnl_r"])

    loss_days = [
        (day, d) for day, d in day_breakdown.items() if d["pnl_r"] < 0 and (d["wins"] + d["losses"]) > 0
    ]
    loss_days.sort(key=lambda x: x[1]["pnl_r"])

    lines = [
        f"\n{'=' * 60}",
        f"  MONTHLY BACKTEST -- {month_key}",
        f"  Market Condition:      {market_type}",
        f"{'=' * 60}",
    ]

    if selected_coins:
        lines.append(f"  Dynamic Universe ({len(selected_coins)} Coins Selected for {month_key}):")
        lines.append(f"    {', '.join(selected_coins)}\n")

    lines.extend([
        f"  Total Trades:          {m['total_trades']}",
        f"  Wins:                  {m['wins']}",
        f"  Losses:                {m['losses']}",
        f"  Breakevens (0R):       {m.get('breakevens', 0)}",
        f"  Expired (no touch):    {m['expired']}",
        f"  Timed Out:             {m['timed_out']}",
        f"  Still Pending:         {m['pending']}",
        f"  Win Rate:              {win_rate_str}",
        f"  Net P&L (R):           {m['net_pnl_r']:+.2f} R",
        f"  Profit Factor:         {pf_str}",
        f"  Max Drawdown:          {m['max_drawdown_r']:.2f} R",
        f"  Max Consec. Wins:      {m['max_consec_wins']}",
        f"  Max Consec. Losses:    {m['max_consec_losses']}",
    ])

    if m["total_trades"] == 0:
        lines.append("\n  Is month mein koi qualified zone nahi mila (Market was quiet / Bearish).")
    else:
        win_zones = [z for z in zones if z["status"] == "WIN"]
        loss_zones = [z for z in zones if z["status"] == "LOSS"]
        if win_zones:
            best = max(win_zones, key=lambda z: z.get("actual_rr", 0))
            lines.append(f"\n  Best Trade:  {best['coin']} [{best['timeframe']}] "
                         f"+{best.get('actual_rr', 0):.2f}R  ({str(best['created_at'])[:10]})")
        if loss_zones:
            worst = min(loss_zones, key=lambda z: z.get("actual_rr", 99))
            lines.append(f"  Worst Trade: {worst['coin']} [{worst['timeframe']}] "
                         f"-1.00R  ({str(worst['created_at'])[:10]})")

        # Top Winning Days summary
        if winning_days:
            top_wins_str = ", ".join([f"{day} ({d['pnl_r']:+.2f}R, {d['wins']}W)" for day, d in winning_days[:3]])
            lines.append(f"  Top Winning Day(s):    {top_wins_str}")
        if loss_days:
            worst_days_str = ", ".join([f"{day} ({d['pnl_r']:+.2f}R, {d['losses']}L)" for day, d in loss_days[:2]])
            lines.append(f"  Worst Loss Day(s):     {worst_days_str}")

        # Deep Failure & Diagnostic Analysis for this month
        lines.append("\n  --- ALL TRADES COMPLETE DIAGNOSTIC LEDGER ---")
        for idx, z in enumerate(sorted(zones, key=lambda x: str(x.get("created_at", ""))), 1):
            st = z.get("status", "PENDING")
            st_icon = "✅ WIN" if st == "WIN" else ("❌ LOSS" if st == "LOSS" else ("↔ BREAKEVEN" if st == "BREAKEVEN" else ("⏰ EXPIRED" if st == "EXPIRED" else "⏳ PENDING")))
            touch_str = str(z.get("touched_at", "N/A"))[:16] if z.get("touched_at") else "Not Touched"
            res_str = str(z.get("resolved_at", "N/A"))[:16] if z.get("resolved_at") else "Unresolved"
            diag_str = z.get("diagnosis") or z.get("post_sl_details") or "No diagnostic details."

            lines.append(f"\n  [#{idx:02d}] {z['coin']} [{z['timeframe']}] -- {st_icon}")
            lines.append(f"    • Zone Level     : {z.get('level_name', '78.6% OTE')}")
            lines.append(f"    • Created At     : {str(z.get('created_at', ''))[:16]} UTC")
            lines.append(f"    • Entry Price    : {z['entry_price']:.4f}")
            lines.append(f"    • Stop Loss (ATR): {z['stop_price']:.4f}")
            lines.append(f"    • Take Profit    : {z['target_price']:.4f}")
            lines.append(f"    • Risk:Reward    : 1:{z.get('actual_rr', 0):.2f}")
            lines.append(f"    • Confluence     : {z.get('score', 0)}/100")
            lines.append(f"    • Swing Structure: {z.get('swing_low', 0):.4f} -> {z.get('swing_high', 0):.4f}")
            lines.append(f"    • Touched At     : {touch_str}")
            lines.append(f"    • Resolved At    : {res_str}")
            lines.append(f"    • Diagnosis      : {diag_str}")

    lines.append("\n  --- Day-by-Day Detailed Breakdown ---")
    lines.append(render_day_table(day_breakdown))
    return "\n".join(lines)


def render_overall_summary(overall_metrics: dict, monthly_metrics: dict, all_zones: list,
                            coin_universe: list, timeframes: list, start_dt, end_dt) -> str:
    m = overall_metrics
    pf_str = f"{m['profit_factor']:.2f}" if m["profit_factor"] != float("inf") else "inf"

    # Aggregate all daily data across whole year
    from collections import defaultdict
    daily_all = defaultdict(lambda: {"zones": 0, "wins": 0, "losses": 0, "breakevens": 0, "pnl_r": 0.0})
    total_cost_pct = (0.075 + 0.04) / 100 * 2

    for z in all_zones:
        day_str = str(z["created_at"])[:10]
        daily_all[day_str]["zones"] += 1
        if z["status"] == "WIN":
            daily_all[day_str]["wins"] += 1
            daily_all[day_str]["pnl_r"] += z["actual_rr"] - total_cost_pct
        elif z["status"] == "LOSS":
            daily_all[day_str]["losses"] += 1
            daily_all[day_str]["pnl_r"] += -1.0 - total_cost_pct
        elif z["status"] == "BREAKEVEN":
            daily_all[day_str]["breakevens"] += 1
            daily_all[day_str]["pnl_r"] += 0.0 - total_cost_pct

    # Best days of the year
    active_days = [(day, d) for day, d in daily_all.items() if (d["wins"] + d["losses"]) > 0]
    top_days = sorted(active_days, key=lambda x: -x[1]["pnl_r"])
    positive_days_count = sum(1 for _, d in active_days if d["pnl_r"] > 0)
    negative_days_count = sum(1 for _, d in active_days if d["pnl_r"] < 0)

    lines = [
        f"{'*' * 60}",
        "  1-YEAR LOCAL BACKTEST -- OVERALL SUMMARY",
        f"{'*' * 60}",
        f"  Period:                 {start_dt.strftime('%Y-%m-%d')} -> {end_dt.strftime('%Y-%m-%d')}",
        f"  Coins Tested:           {len(coin_universe)}",
        f"  Timeframes:             {', '.join(timeframes)}",
        f"  Total Trades:           {m['total_trades']}",
        f"  Wins:                   {m['wins']}",
        f"  Losses:                 {m['losses']}",
        f"  Breakevens (0R):        {m.get('breakevens', 0)}",
        f"  Expired (no touch):     {m['expired']}",
        f"  Timed Out:              {m['timed_out']}",
        f"  Still Pending:          {m['pending']}",
        f"  Win Rate:               {m['win_rate_pct']:.1f}%",
        f"  Net P&L (R):            {m['net_pnl_r']:+.2f} R",
        f"  Profit Factor:          {pf_str}",
        f"  Max Drawdown:           {m['max_drawdown_r']:.2f} R",
        f"  Max Consec. Wins:       {m['max_consec_wins']}",
        f"  Max Consec. Losses:     {m['max_consec_losses']}",
        f"  Profitable Trading Days:{positive_days_count} days",
        f"  Losing Trading Days:    {negative_days_count} days",
        "",
        "  --- TOP 5 BEST WINNING DAYS OF THE YEAR ---",
    ]

    for rank, (day_str, d) in enumerate(top_days[:5], 1):
        lines.append(f"    #{rank}. {day_str}: P&L = {d['pnl_r']:+.2f} R ({d['wins']} Wins, {d['losses']} Losses)")

    lines.append("\n  --- Month-by-Month Performance Summary ---")
    for month_key, mm in monthly_metrics.items():
        lines.append(f"    {month_key}: P&L = {mm['net_pnl_r']:+.2f} R  |  "
                     f"Win Rate = {mm['win_rate_pct']:.1f}%  |  Trades = {mm['total_trades']}")
    lines.append(f"{'*' * 60}")
    return "\n".join(lines)


def write_full_report(output_dir: str, overall_metrics: dict, monthly_results: list, monthly_metrics: dict,
                       all_zones: list, coin_universe: list, timeframes: list, start_dt, end_dt) -> str:
    """Poora text report file mein likhta hai, path return karta hai."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "backtest_report.txt")

    lines = [
        "LOCAL HISTORICAL BACKTEST REPORT -- 1 YEAR",
        "Fibonacci Intraday Strategy (Enhanced Edition)",
        "",
        render_overall_summary(overall_metrics, monthly_metrics, all_zones, coin_universe, timeframes, start_dt, end_dt),
    ]
    for r in monthly_results:
        lines.append(render_month_section(
            r["month_key"],
            r["market_type"],
            r["metrics"],
            r["day_breakdown"],
            r["zones"],
            selected_coins=r.get("selected_coins"),
        ))

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Report saved: {path}")
    return path


def write_zones_csv(output_dir: str, all_zones: list) -> str:
    """Har zone (trade) ko ek CSV row ke tor par save karta hai (Excel mein khol sakte hain)."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "backtest_zones.csv")

    fieldnames = [
        "coin", "timeframe", "level_name", "created_at", "entry_price", "stop_price",
        "target_price", "swing_low", "swing_high", "score", "actual_rr",
        "status", "touched_at", "resolved_at", "diagnosis", "post_sl_behavior", "post_sl_details",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for z in sorted(all_zones, key=lambda x: str(x.get("created_at", ""))):
            writer.writerow(z)

    logger.info(f"Zones CSV saved: {path}")
    return path


def send_email_report(report_text: str, cfg) -> bool:
    """Optional — sirf tab bhejta hai jab SEND_EMAIL=true ho aur credentials set hon."""
    if not cfg.SEND_EMAIL:
        return False
    if not cfg.SMTP_USER or not cfg.SMTP_PASSWORD or not cfg.REPORT_EMAIL_TO:
        logger.warning("SEND_EMAIL=true hai lekin SMTP credentials missing hain -- email skip.")
        return False

    msg = MIMEMultipart()
    msg["From"] = cfg.SMTP_USER
    msg["To"] = cfg.REPORT_EMAIL_TO
    msg["Subject"] = "Local Backtest -- 1-Year Report (Fibonacci Strategy)"
    msg.attach(MIMEText(report_text, "plain"))

    try:
        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT) as server:
            server.starttls()
            server.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Report email sent successfully.")
        return True
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return False
