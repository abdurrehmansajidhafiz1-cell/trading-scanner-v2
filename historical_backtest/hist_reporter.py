"""
hist_reporter.py — Historical Backtest Report Generator & Email Sender.

Year-by-year email reports:
2021, 2022, 2023, 2024, 2025, aur current year (2026).

Har email mein:
- Annual summary
- Monthly sections
- Day-by-day breakdown
- Best / Worst trades
- Market condition
- P&L / Win Rate / Profit Factor
- Data errors

Existing reporting.py se bilkul independent hai.
"""

import logging
import smtplib

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


logger = logging.getLogger("hist_backtest")


# ============================================================
# DAY-BY-DAY TABLE
# ============================================================

def render_day_table(day_breakdown: dict) -> str:
    """Day-by-day breakdown table render karta hai."""

    if not day_breakdown:
        return "  Is month mein koi zone qualify nahi hua.\n"

    lines = []

    lines.append(
        f"  {'Date':<14} | {'Zones':>5} | {'Wins':>4} | "
        f"{'Loss':>4} | {'Day P&L':>9}"
    )

    lines.append(
        f"  {'-' * 14}-+-{'-' * 5}-+-{'-' * 4}-+-"
        f"{'-' * 4}-+-{'-' * 9}"
    )

    for day_str in sorted(day_breakdown.keys()):
        d = day_breakdown[day_str]

        resolved = d["wins"] + d["losses"]

        if resolved > 0:
            pnl_str = f"{d['pnl_r']:+.2f} R"
        else:
            pnl_str = "  ——  "

        lines.append(
            f"  {day_str:<14} | "
            f"{d['zones']:>5} | "
            f"{d['wins']:>4} | "
            f"{d['losses']:>4} | "
            f"{pnl_str:>9}"
        )

    return "\n".join(lines) + "\n"


# ============================================================
# MONTHLY SECTION
# ============================================================

def render_month_section(
    month_key: str,
    market_type: str,
    metrics: dict,
    day_breakdown: dict,
    zones: list,
    coin_errors: list,
) -> str:
    """Ek month ka complete report section render karta hai."""

    m = metrics

    if m["profit_factor"] == float("inf"):
        pf_str = "∞"
    else:
        pf_str = f"{m['profit_factor']:.2f}"

    resolved = m["wins"] + m["losses"]

    if resolved > 0:
        win_rate_str = f"{m['win_rate_pct']:.1f}%"
    else:
        win_rate_str = "N/A"

    lines = []

    lines.append("")
    lines.append("=" * 60)
    lines.append(f"  MONTHLY BACKTEST — {month_key}")
    lines.append(f"  Market Condition:      {market_type}")
    lines.append("=" * 60)

    lines.append(f"  Total Trades:          {m['total_trades']}")
    lines.append(f"  Wins:                  {m['wins']}")
    lines.append(f"  Losses:                {m['losses']}")
    lines.append(f"  Expired (no touch):    {m['expired']}")
    lines.append(f"  Timed Out:             {m['timed_out']}")
    lines.append(f"  Pending:               {m['pending']}")
    lines.append(f"  Win Rate:              {win_rate_str}")
    lines.append(f"  Net P&L (R):           {m['net_pnl_r']:+.2f} R")
    lines.append(f"  Profit Factor:         {pf_str}")
    lines.append(f"  Max Drawdown:          {m['max_drawdown_r']:.2f} R")
    lines.append(f"  Max Consec. Wins:      {m['max_consec_wins']}")
    lines.append(f"  Max Consec. Losses:    {m['max_consec_losses']}")

    # --------------------------------------------------------
    # Best / Worst trade
    # --------------------------------------------------------

    if m["total_trades"] > 0:

        win_zones = [
            z for z in zones
            if z.get("status") == "WIN"
        ]

        loss_zones = [
            z for z in zones
            if z.get("status") == "LOSS"
        ]

        if win_zones:
            best = max(
                win_zones,
                key=lambda z: z.get("actual_rr", 0) or 0
            )

            lines.append(
                f"\n  Best Trade:  "
                f"{best.get('coin', 'UNKNOWN')} "
                f"[{best.get('timeframe', '?')}] "
                f"+{best.get('actual_rr', 0):.2f}R "
                f"({str(best.get('created_at', ''))[:10]})"
            )

        if loss_zones:
            worst = min(
                loss_zones,
                key=lambda z: z.get("actual_rr", 99) or 99
            )

            lines.append(
                f"  Worst Trade: "
                f"{worst.get('coin', 'UNKNOWN')} "
                f"[{worst.get('timeframe', '?')}] "
                f"-1.00R "
                f"({str(worst.get('created_at', ''))[:10]})"
            )

    else:
        lines.append(
            "\n  Is month mein koi qualified zone nahi mila."
        )

    # --------------------------------------------------------
    # Day breakdown
    # --------------------------------------------------------

    lines.append("\n  --- Day-by-Day Breakdown ---")
    lines.append(render_day_table(day_breakdown))

    # --------------------------------------------------------
    # Errors
    # --------------------------------------------------------

    if coin_errors:
        preview = ", ".join(coin_errors[:5])

        if len(coin_errors) > 5:
            preview += "..."

        lines.append(
            f"  [!] Data gaps / fetch errors "
            f"({len(coin_errors)} coin(s)): {preview}"
        )

    return "\n".join(lines)


# ============================================================
# ANNUAL SUMMARY
# ============================================================

def render_year_summary(
    year: int,
    monthly_metrics: dict,
) -> str:
    """Ek saal ka summary section render karta hai."""

    months_data = {
        k: v
        for k, v in monthly_metrics.items()
        if k.startswith(str(year))
    }

    if not months_data:
        return ""

    total_trades = sum(
        m["total_trades"]
        for m in months_data.values()
    )

    total_wins = sum(
        m["wins"]
        for m in months_data.values()
    )

    total_losses = sum(
        m["losses"]
        for m in months_data.values()
    )

    total_pnl_r = sum(
        m["net_pnl_r"]
        for m in months_data.values()
    )

    resolved = total_wins + total_losses

    win_rate = (
        total_wins / resolved * 100
        if resolved > 0
        else 0.0
    )

    best_month = max(
        months_data.items(),
        key=lambda x: x[1]["net_pnl_r"]
    )

    worst_month = min(
        months_data.items(),
        key=lambda x: x[1]["net_pnl_r"]
    )

    lines = []

    lines.append("")
    lines.append("#" * 60)
    lines.append(f"  ANNUAL SUMMARY — {year}")
    lines.append("#" * 60)

    lines.append(f"  Months Analyzed: {len(months_data)}")
    lines.append(f"  Total Trades:    {total_trades}")
    lines.append(f"  Total Wins:      {total_wins}")
    lines.append(f"  Total Losses:    {total_losses}")
    lines.append(f"  Annual Win Rate: {win_rate:.1f}%")
    lines.append(f"  Annual P&L (R):  {total_pnl_r:+.2f} R")

    lines.append(
        f"  Best Month:      "
        f"{best_month[0]} "
        f"({best_month[1]['net_pnl_r']:+.2f} R)"
    )

    lines.append(
        f"  Worst Month:     "
        f"{worst_month[0]} "
        f"({worst_month[1]['net_pnl_r']:+.2f} R)"
    )

    lines.append("#" * 60)

    return "\n".join(lines)


# ============================================================
# OVERALL SUMMARY
# ============================================================

def render_overall_summary(
    monthly_metrics: dict,
    start_year: int = 2021,
    end_year: int = 2026,
) -> str:
    """Complete historical analysis ka overall summary."""

    if not monthly_metrics:
        return "No data available."

    all_total = sum(
        m["total_trades"]
        for m in monthly_metrics.values()
    )

    all_wins = sum(
        m["wins"]
        for m in monthly_metrics.values()
    )

    all_losses = sum(
        m["losses"]
        for m in monthly_metrics.values()
    )

    all_pnl_r = sum(
        m["net_pnl_r"]
        for m in monthly_metrics.values()
    )

    resolved = all_wins + all_losses

    win_rate = (
        all_wins / resolved * 100
        if resolved > 0
        else 0.0
    )

    best_month = max(
        monthly_metrics.items(),
        key=lambda x: x[1]["net_pnl_r"]
    )

    worst_month = min(
        monthly_metrics.items(),
        key=lambda x: x[1]["net_pnl_r"]
    )

    valid_wr_months = [
        (k, v)
        for k, v in monthly_metrics.items()
        if v["total_trades"] >= 3
    ]

    if valid_wr_months:
        best_wr = max(
            valid_wr_months,
            key=lambda x: x[1]["win_rate_pct"]
        )

        worst_wr = min(
            valid_wr_months,
            key=lambda x: x[1]["win_rate_pct"]
        )
    else:
        best_wr = None
        worst_wr = None

    zero_trade_months = [
        k
        for k, v in monthly_metrics.items()
        if v["total_trades"] == 0
    ]

    lines = []

    lines.append("")
    lines.append("*" * 60)
    lines.append(
        f"  HISTORICAL OVERALL PERFORMANCE "
        f"({start_year} → {end_year})"
    )
    lines.append("*" * 60)

    lines.append(
        f"  Total Months Analyzed:      "
        f"{len(monthly_metrics)}"
    )

    lines.append(
        f"  Total Trades (All Time):    "
        f"{all_total}"
    )

    lines.append(
        f"  Total Wins:                 "
        f"{all_wins}"
    )

    lines.append(
        f"  Total Losses:               "
        f"{all_losses}"
    )

    lines.append(
        f"  Overall Win Rate:           "
        f"{win_rate:.1f}%"
    )

    lines.append(
        f"  Overall Net P&L (R):        "
        f"{all_pnl_r:+.2f} R"
    )

    lines.append(
        f"  Best Month (P&L):           "
        f"{best_month[0]} "
        f"({best_month[1]['net_pnl_r']:+.2f} R)"
    )

    lines.append(
        f"  Worst Month (P&L):          "
        f"{worst_month[0]} "
        f"({worst_month[1]['net_pnl_r']:+.2f} R)"
    )

    if best_wr:
        lines.append(
            f"  Best Win Rate Month:        "
            f"{best_wr[0]} "
            f"({best_wr[1]['win_rate_pct']:.1f}%)"
        )

    if worst_wr:
        lines.append(
            f"  Worst Win Rate Month:       "
            f"{worst_wr[0]} "
            f"({worst_wr[1]['win_rate_pct']:.1f}%)"
        )

    lines.append(
        f"  Zero-Trade Months:          "
        f"{len(zero_trade_months)}"
    )

    if zero_trade_months:
        preview = ", ".join(zero_trade_months[:12])

        if len(zero_trade_months) > 12:
            preview += "..."

        lines.append(f"    Months: {preview}")

    lines.append("*" * 60)

    return "\n".join(lines)


# ============================================================
# EMAIL SENDING
# ============================================================

def _send_email_raw(
    subject: str,
    body: str,
    cfg,
) -> bool:
    """SMTP ke through email send karta hai."""

    if (
        not cfg.SMTP_USER
        or not cfg.SMTP_PASSWORD
        or not cfg.REPORT_EMAIL_TO
    ):
        logger.warning(
            "SMTP credentials missing — email skip."
        )

        print(
            f"\n[EMAIL SKIPPED — no credentials]\n"
            f"Subject: {subject}\n"
            f"{body[:500]}..."
        )

        return False

    msg = MIMEMultipart()

    msg["From"] = cfg.SMTP_USER
    msg["To"] = cfg.REPORT_EMAIL_TO
    msg["Subject"] = subject

    msg.attach(
        MIMEText(body, "plain", "utf-8")
    )

    try:
        with smtplib.SMTP(
            cfg.SMTP_HOST,
            cfg.SMTP_PORT,
            timeout=60,
        ) as server:

            server.ehlo()
            server.starttls()
            server.ehlo()

            server.login(
                cfg.SMTP_USER,
                cfg.SMTP_PASSWORD,
            )

            server.send_message(msg)

        logger.info(
            f"Email sent successfully: {subject}"
        )

        print(
            f"  ✓ Email sent: {subject}"
        )

        return True

    except Exception as e:

        logger.error(
            f"Email send error: {type(e).__name__}: {e}"
        )

        print(
            f"  ✗ Email error: {e}"
        )

        return False


# ============================================================
# YEAR REPORT
# ============================================================

def send_year_report(
    year: int,
    monthly_results: list[dict],
    monthly_metrics: dict,
    cfg,
) -> bool:
    """Ek saal ka complete email bhejta hai."""

    lines = []

    lines.append(
        f"HISTORICAL BACKTEST REPORT — {year}"
    )

    lines.append(
        "Fibonacci Intraday Strategy"
    )

    lines.append(
        f"Coins Tested: {len(cfg.HIST_COIN_UNIVERSE)}"
    )

    lines.append(
        f"Timeframes: {', '.join(cfg.TIMEFRAMES)}"
    )

    lines.append("")

    lines.append(
        render_year_summary(
            year,
            monthly_metrics,
        )
    )

    year_results = [
        result
        for result in monthly_results
        if result["month_key"].startswith(str(year))
    ]

    for result in year_results:

        lines.append(
            render_month_section(
                month_key=result["month_key"],
                market_type=result["market_type"],
                metrics=result["metrics"],
                day_breakdown=result["day_breakdown"],
                zones=result["zones"],
                coin_errors=result.get("coin_errors", []),
            )
        )

    subject = (
        f"Historical Backtest — "
        f"{year} Annual Report "
        f"(Fibonacci Strategy)"
    )

    body = "\n".join(lines)

    return _send_email_raw(
        subject,
        body,
        cfg,
    )


# ============================================================
# OVERALL REPORT
# ============================================================

def send_overall_summary_report(
    monthly_results: list[dict],
    monthly_metrics: dict,
    cfg,
) -> bool:
    """Complete historical analysis ka overall summary email."""

    if not monthly_metrics:
        logger.warning(
            "No monthly metrics available — "
            "overall email skipped."
        )
        return False

    years = sorted(
        set(
            int(k[:4])
            for k in monthly_metrics.keys()
        )
    )

    start_year = min(years)
    end_year = max(years)

    lines = []

    lines.append(
        "HISTORICAL BACKTEST — "
        "COMPLETE ANALYSIS"
    )

    lines.append(
        "Fibonacci Intraday Strategy"
    )

    lines.append(
        f"Analysis Period: "
        f"{start_year} → {end_year}"
    )

    lines.append(
        f"Coins Tested: "
        f"{len(cfg.HIST_COIN_UNIVERSE)}"
    )

    lines.append(
        f"Timeframes: "
        f"{', '.join(cfg.TIMEFRAMES)}"
    )

    lines.append("=" * 60)

    lines.append(
        render_overall_summary(
            monthly_metrics,
            start_year,
            end_year,
        )
    )

    # --------------------------------------------------------
    # Year-by-Year P&L
    # --------------------------------------------------------

    lines.append(
        "\n--- Year-by-Year P&L Summary ---"
    )

    for year in years:

        year_months = {
            k: v
            for k, v in monthly_metrics.items()
            if k.startswith(str(year))
        }

        year_pnl = sum(
            m["net_pnl_r"]
            for m in year_months.values()
        )

        year_wins = sum(
            m["wins"]
            for m in year_months.values()
        )

        year_losses = sum(
            m["losses"]
            for m in year_months.values()
        )

        resolved = year_wins + year_losses

        year_wr = (
            year_wins / resolved * 100
            if resolved > 0
            else 0.0
        )

        year_trades = sum(
            m["total_trades"]
            for m in year_months.values()
        )

        lines.append(
            f"  {year}: "
            f"P&L = {year_pnl:+.2f} R  |  "
            f"Win Rate = {year_wr:.1f}%  |  "
            f"Trades = {year_trades}"
        )

    subject = (
        "Historical Backtest — "
        "Complete Overall Summary "
        "(Fibonacci Strategy)"
    )

    body = "\n".join(lines)

    return _send_email_raw(
        subject,
        body,
        cfg,
    )
