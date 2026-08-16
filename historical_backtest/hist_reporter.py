"""
hist_reporter.py — Historical Backtest Report Generator & Email Sender.
Year-by-year email format (5 emails: 2021, 2022, 2023, 2024, 2025/2026).
Har email mein monthly sections + day-by-day tables hain.
Existing reporting.py se bilkul independent hai.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict

logger = logging.getLogger("hist_backtest")


# ============================================================
# REPORT TEXT GENERATION
# ============================================================

def render_day_table(day_breakdown: dict) -> str:
    """Day-by-day breakdown table render karta hai."""
    if not day_breakdown:
        return "  Is month mein koi zone qualify nahi hua.\n"
    lines = []
    lines.append(f"  {'Date':<14} | {'Zones':>5} | {'Wins':>4} | {'Loss':>4} | {'Day P&L':>9}")
    lines.append(f"  {'-'*14}-+-{'-'*5}-+-{'-'*4}-+-{'-'*4}-+-{'-'*9}")
    for day_str in sorted(day_breakdown.keys()):
        d = day_breakdown[day_str]
        pnl_str = f"{d['pnl_r']:+.2f} R" if (d["wins"] + d["losses"]) > 0 else "  ——  "
        lines.append(
            f"  {day_str:<14} | {d['zones']:>5} | {d['wins']:>4} | {d['losses']:>4} | {pnl_str:>9}"
        )
    return "\n".join(lines) + "\n"


def render_month_section(month_key: str, market_type: str, metrics: dict,
                          day_breakdown: dict, zones: list, coin_errors: list) -> str:
    """Ek month ka complete section text render karta hai."""
    m = metrics
    pf_str = f"{m['profit_factor']:.2f}" if m["profit_factor"] != float("inf") else "∞"
    win_rate_str = f"{m['win_rate_pct']:.1f}%" if (m["wins"] + m["losses"]) > 0 else "N/A"

    lines = []
    lines.append(f"\n{'=' * 60}")
    lines.append(f"  MONTHLY BACKTEST — {month_key}")
    lines.append(f"  Market Condition:      {market_type}")
    lines.append(f"{'=' * 60}")
    lines.append(f"  Total Trades:          {m['total_trades']}")
    lines.append(f"  Wins:                  {m['wins']}")
    lines.append(f"  Losses:                {m['losses']}")
    lines.append(f"  Expired (no touch):    {m['expired']}")
    lines.append(f"  Timed Out:             {m['timed_out']}")
    lines.append(f"  Win Rate:              {win_rate_str}")
    lines.append(f"  Net P&L (R):           {m['net_pnl_r']:+.2f} R")
    lines.append(f"  Profit Factor:         {pf_str}")
    lines.append(f"  Max Drawdown:          {m['max_drawdown_r']:.2f} R")
    lines.append(f"  Max Consec. Wins:      {m['max_consec_wins']}")
    lines.append(f"  Max Consec. Losses:    {m['max_consec_losses']}")

    if m["total_trades"] == 0:
        lines.append("\n  Is month mein koi qualified zone nahi mila.")
    else:
        # Best / Worst trade
        win_zones  = [z for z in zones if z["status"] == "WIN"]
        loss_zones = [z for z in zones if z["status"] == "LOSS"]
        if win_zones:
            best = max(win_zones, key=lambda z: z.get("actual_rr", 0))
            lines.append(f"\n  Best Trade:  {best['coin']} [{best['timeframe']}] "
                         f"+{best.get('actual_rr', 0):.2f}R  ({str(best['created_at'])[:10]})")
        if loss_zones:
            worst = min(loss_zones, key=lambda z: z.get("actual_rr", 99))
            lines.append(f"  Worst Trade: {worst['coin']} [{worst['timeframe']}] "
                         f"-1.00R  ({str(worst['created_at'])[:10]})")

    lines.append("\n  --- Day-by-Day Breakdown ---")
    lines.append(render_day_table(day_breakdown))

    if coin_errors:
        lines.append(f"  [!] Data gaps / fetch errors ({len(coin_errors)} coin(s)): " +
                     ", ".join(coin_errors[:5]) + ("..." if len(coin_errors) > 5 else ""))

    return "\n".join(lines)


def render_year_summary(year: int, monthly_metrics: dict) -> str:
    """Ek saal ka summary section render karta hai."""
    months_data = {k: v for k, v in monthly_metrics.items() if k.startswith(str(year))}
    if not months_data:
        return ""

    total_trades = sum(m["total_trades"] for m in months_data.values())
    total_wins   = sum(m["wins"]         for m in months_data.values())
    total_losses = sum(m["losses"]       for m in months_data.values())
    total_pnl_r  = sum(m["net_pnl_r"]   for m in months_data.values())
    resolved     = total_wins + total_losses
    win_rate     = (total_wins / resolved * 100) if resolved > 0 else 0.0

    best_month  = max(months_data.items(), key=lambda x: x[1]["net_pnl_r"])
    worst_month = min(months_data.items(), key=lambda x: x[1]["net_pnl_r"])

    lines = []
    lines.append(f"\n{'#' * 60}")
    lines.append(f"  ANNUAL SUMMARY — {year}")
    lines.append(f"{'#' * 60}")
    lines.append(f"  Total Trades:    {total_trades}")
    lines.append(f"  Total Wins:      {total_wins}")
    lines.append(f"  Total Losses:    {total_losses}")
    lines.append(f"  Annual Win Rate: {win_rate:.1f}%")
    lines.append(f"  Annual P&L (R):  {total_pnl_r:+.2f} R")
    lines.append(f"  Best Month:      {best_month[0]}  ({best_month[1]['net_pnl_r']:+.2f} R)")
    lines.append(f"  Worst Month:     {worst_month[0]}  ({worst_month[1]['net_pnl_r']:+.2f} R)")
    lines.append(f"{'#' * 60}")
    return "\n".join(lines)


def render_overall_summary(monthly_metrics: dict) -> str:
    """5-year overall summary render karta hai."""
    if not monthly_metrics:
        return "No data available."

    all_total   = sum(m["total_trades"] for m in monthly_metrics.values())
    all_wins    = sum(m["wins"]         for m in monthly_metrics.values())
    all_losses  = sum(m["losses"]       for m in monthly_metrics.values())
    all_pnl_r   = sum(m["net_pnl_r"]   for m in monthly_metrics.values())
    resolved    = all_wins + all_losses
    win_rate    = (all_wins / resolved * 100) if resolved > 0 else 0.0

    best_month  = max(monthly_metrics.items(), key=lambda x: x[1]["net_pnl_r"])
    worst_month = min(monthly_metrics.items(), key=lambda x: x[1]["net_pnl_r"])
    best_win_rate_month  = max(monthly_metrics.items(),
                                key=lambda x: x[1]["win_rate_pct"] if x[1]["total_trades"] >= 3 else 0)
    worst_win_rate_month = min(monthly_metrics.items(),
                                key=lambda x: x[1]["win_rate_pct"] if x[1]["total_trades"] >= 3 else 100)

    # Zero-trade months count
    zero_trade_months = [k for k, v in monthly_metrics.items() if v["total_trades"] == 0]

    lines = []
    lines.append(f"\n{'*' * 60}")
    lines.append(f"  5-YEAR OVERALL PERFORMANCE SUMMARY (2021 → 2026)")
    lines.append(f"{'*' * 60}")
    lines.append(f"  Total Months Analyzed:      {len(monthly_metrics)}")
    lines.append(f"  Total Trades (All Time):    {all_total}")
    lines.append(f"  Total Wins:                 {all_wins}")
    lines.append(f"  Total Losses:               {all_losses}")
    lines.append(f"  5-Year Win Rate:            {win_rate:.1f}%")
    lines.append(f"  5-Year Net P&L (R):         {all_pnl_r:+.2f} R")
    lines.append(f"  Best Month (P&L):           {best_month[0]}  ({best_month[1]['net_pnl_r']:+.2f} R)")
    lines.append(f"  Worst Month (P&L):          {worst_month[0]}  ({worst_month[1]['net_pnl_r']:+.2f} R)")
    lines.append(f"  Best Win Rate Month:        {best_win_rate_month[0]}  ({best_win_rate_month[1]['win_rate_pct']:.1f}%)")
    lines.append(f"  Worst Win Rate Month:       {worst_win_rate_month[0]}  ({worst_win_rate_month[1]['win_rate_pct']:.1f}%)")
    lines.append(f"  Zero-Trade Months:          {len(zero_trade_months)}")
    if zero_trade_months:
        lines.append(f"    Months: {', '.join(zero_trade_months[:8])}" +
                     ("..." if len(zero_trade_months) > 8 else ""))
    lines.append(f"{'*' * 60}")
    return "\n".join(lines)


# ============================================================
# EMAIL SENDING
# ============================================================

def _send_email_raw(subject: str, body: str, cfg) -> bool:
    """Email bhejta hai (hist_config.py ke credentials use karta hai)."""
    if not cfg.SMTP_USER or not cfg.SMTP_PASSWORD or not cfg.REPORT_EMAIL_TO:
        logger.warning("SMTP credentials missing — email skip.")
        print(f"\n[EMAIL SKIPPED — no credentials]\nSubject: {subject}\n{body[:500]}...")
        return False

    msg = MIMEMultipart()
    msg["From"]    = cfg.SMTP_USER
    msg["To"]      = cfg.REPORT_EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT) as server:
            server.starttls()
            server.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Email sent: {subject}")
        print(f"  ✓ Email sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email send error: {e}")
        print(f"  ✗ Email error: {e}")
        return False


def send_year_report(year: int, monthly_results: list[dict], monthly_metrics: dict, cfg) -> bool:
    """Ek saal ka complete email bhejta hai (monthly + day-by-day breakdown)."""
    lines = []
    lines.append(f"HISTORICAL BACKTEST REPORT — {year}")
    lines.append(f"Fibonacci Intraday Strategy | 2021-2026 Analysis")
    lines.append(f"Coins Tested: {len(cfg.HIST_COIN_UNIVERSE)}")
    lines.append(f"Timeframes: {', '.join(cfg.TIMEFRAMES)}")
    lines.append("")
    lines.append(render_year_summary(year, monthly_metrics))

    for result in monthly_results:
        if not result["month_key"].startswith(str(year)):
            continue
        lines.append(render_month_section(
            month_key     = result["month_key"],
            market_type   = result["market_type"],
            metrics       = result["metrics"],
            day_breakdown = result["day_breakdown"],
            zones         = result["zones"],
            coin_errors   = result.get("coin_errors", []),
        ))

    subject = f"Historical Backtest — {year} Annual Report (Fibonacci Strategy)"
    body    = "\n".join(lines)
    return _send_email_raw(subject, body, cfg)


def send_overall_summary_report(monthly_results: list[dict], monthly_metrics: dict, cfg) -> bool:
    """5-year overall summary email bhejta hai."""
    lines = []
    lines.append("HISTORICAL BACKTEST — 5-YEAR COMPLETE ANALYSIS")
    lines.append("Fibonacci Intraday Strategy | 2021 → 2026")
    lines.append("=" * 60)
    lines.append(render_overall_summary(monthly_metrics))
    lines.append("\n--- Year-by-Year P&L Summary ---")
    years = sorted(set(int(k[:4]) for k in monthly_metrics.keys()))
    for yr in years:
        yr_months = {k: v for k, v in monthly_metrics.items() if k.startswith(str(yr))}
        yr_pnl    = sum(m["net_pnl_r"] for m in yr_months.values())
        yr_wins   = sum(m["wins"]       for m in yr_months.values())
        yr_losses = sum(m["losses"]     for m in yr_months.values())
        resolved  = yr_wins + yr_losses
        yr_wr     = (yr_wins / resolved * 100) if resolved > 0 else 0.0
        lines.append(f"  {yr}: P&L = {yr_pnl:+.2f} R  |  Win Rate = {yr_wr:.1f}%  |  "
                     f"Trades = {sum(m['total_trades'] for m in yr_months.values())}")

    subject = "Historical Backtest — 5-Year Overall Summary (Fibonacci Strategy)"
    body    = "\n".join(lines)
    return _send_email_raw(subject, body, cfg)
