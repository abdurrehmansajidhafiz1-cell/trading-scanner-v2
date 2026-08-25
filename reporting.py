"""
Reporting engine — Dual-Reporting System (06:00 AM PKT & 06:00 PM PKT).
Renders both:
  1. CURRENT PERIOD REPORT (Previous boundary -> Current boundary)
  2. CUMULATIVE ROLLING PROGRESS (Day 1 -> Current date)
  3. DYNAMIC SCAN UNIVERSE (Explicit Scanned Coins List for every period)
  4. 15-DAY STRATEGY EVALUATION & FAILURE DIAGNOSIS REPORT
All timestamps rendered in Pakistan Time (PKT) for user readability, internal calculation in UTC.
"""

import json
from datetime import datetime, timezone, timedelta, time as dtime

import database as db
import timezone_utils as tz
import config
from backtester import run_15day_rolling_backtest

# Dual Reports: Fixed PKT Wall-Clock Schedules (06:00 AM PKT & 06:00 PM PKT)
DAILY_REPORT_TIME_PKT = dtime(6, 0)     # subah 06:00 AM PKT
HALFDAY_REPORT_TIME_PKT = dtime(18, 0)  # shaam 06:00 PM PKT


def _fmt_num(x, decimals=4):
    return f"{x:.{decimals}f}" if x is not None else "N/A"


def _get_system_start_dt() -> datetime:
    start_iso = db.get_config("system_start_datetime")
    if start_iso:
        return datetime.fromisoformat(start_iso)
    return datetime.now(timezone.utc)


def _cumulative_progress_section(end_dt: datetime) -> str:
    bt = run_15day_rolling_backtest(start_dt=_get_system_start_dt(), end_dt=end_dt)
    
    lines = []
    lines.append("--- CUMULATIVE ROLLING PROGRESS (Day 1 se Aaj Tak) ---")
    lines.append(f"Backtest Start Date (Day 1): {tz.format_both(_get_system_start_dt())}")
    lines.append(f"Current Date:               {tz.format_both(end_dt)}")
    lines.append(f"Total Trades Qualified:     {bt['total_trades']}")
    lines.append(f"  Wins:                     {bt['wins']}")
    lines.append(f"  Losses:                   {bt['losses']}")
    lines.append(f"  Active/Pending:           {bt['active_pending']}")
    lines.append(f"  Expired (never touched):  {bt['expired']}")
    lines.append(f"  Timed Out (range end):    {bt['timed_out']}")
    lines.append(f"Cumulative Win Rate:        {bt['win_rate_pct']:.1f}%")
    lines.append(f"Cumulative Net P&L (R):     {bt['net_pnl_r']:+.2f} R")
    lines.append(f"Profit Factor:              {bt['profit_factor']:.2f}")
    lines.append(f"Max Drawdown:               {bt['max_drawdown_r']:.2f} R")
    lines.append(f"Max Consecutive Wins:       {bt['max_consecutive_wins']}")
    lines.append(f"Max Consecutive Losses:     {bt['max_consecutive_losses']}")
    
    if bt["failure_causes"]:
        lines.append("\nTop Loss Root Causes (Cumulative):")
        for cause, count in sorted(bt["failure_causes"].items(), key=lambda x: -x[1]):
            lines.append(f"  - {cause}: {count} trade(s)")

    lines.append("")
    return "\n".join(lines)


def generate_report(period_label: str, start_dt: datetime, end_dt: datetime, include_cumulative: bool = True) -> str:
    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    zones = db.get_zones_in_window(start_iso, end_iso)
    rejected = db.get_rejected_in_window(start_iso, end_iso)
    scan_logs = db.get_scan_logs_in_window(start_iso, end_iso)

    coins_scanned = scan_logs[-1]["coins_scanned"] if scan_logs else 0
    total_scans = len(scan_logs)

    # Extract distinct scanned coin list across all scan runs in this reporting period
    scanned_coins_set = set()
    for log in scan_logs:
        if log.get("coin_list"):
            try:
                c_list = json.loads(log["coin_list"])
                if isinstance(c_list, list):
                    scanned_coins_set.update(c_list)
            except Exception:
                pass

    scanned_coins_list = sorted(list(scanned_coins_set))

    wins = [z for z in zones if z["status"] == "WIN"]
    losses = [z for z in zones if z["status"] == "LOSS"]
    pending = [z for z in zones if z["status"] in ("PENDING", "ACTIVE")]
    expired = [z for z in zones if z["status"] == "EXPIRED"]
    timed_out = [z for z in zones if z["status"] == "TIMEOUT"]

    resolved_count = len(wins) + len(losses)
    win_rate = (len(wins) / resolved_count * 100) if resolved_count > 0 else None

    lines = []
    lines.append(f"{'=' * 55}")
    lines.append(f"TRADING SYSTEM DUAL REPORT — {period_label}")
    lines.append(f"Period start: {tz.format_both(start_dt)}")
    lines.append(f"Period end:   {tz.format_both(end_dt)}")
    lines.append(f"{'=' * 55}\n")

    if include_cumulative:
        lines.append(_cumulative_progress_section(end_dt))
        lines.append("--- CURRENT REPORTING PERIOD ACTIVITY ---")

    lines.append(f"Coins Scanned Count:               {coins_scanned}")
    lines.append(f"Total Scan Runs This Period:      {total_scans}")
    lines.append(f"Period Trades Qualified:          {len(zones)}")
    lines.append(f"  Wins:                           {len(wins)}")
    lines.append(f"  Losses:                         {len(losses)}")
    lines.append(f"  Active/Pending:                 {len(pending)}")
    lines.append(f"  Expired:                        {len(expired)}")
    lines.append(f"  Timed Out:                      {len(timed_out)}")
    
    if win_rate is not None:
        lines.append(f"Period Win Rate:                  {win_rate:.1f}% ({len(wins)}/{resolved_count} resolved)")
    else:
        lines.append("Period Win Rate:                  N/A (no trades resolved in this period)")
    lines.append("")

    # --- DYNAMIC SCAN UNIVERSE COINS LIST ---
    lines.append(f"--- DYNAMIC SCAN UNIVERSE ({len(scanned_coins_list)} Coins Selected) ---")
    if scanned_coins_list:
        lines.append("Is reporting period mein yeh coins Dynamic Scan List mein selected thay:")
        for idx, coin_sym in enumerate(scanned_coins_list, 1):
            lines.append(f"  {idx:>2}. {coin_sym}")
    else:
        lines.append("Dynamic Scan List coins unavailable for this window.")
    lines.append("")

    if zones:
        lines.append("--- QUALIFIED TRADES & SETUPS (PERIOD DETAILS) ---")
        for z in zones:
            breakdown = json.loads(z["score_breakdown"]) if z["score_breakdown"] else {}
            created_str = tz.format_both(datetime.fromisoformat(z["created_at"])) if z["created_at"] else "N/A"
            lines.append(f"\n  {z['coin']} [{z['timeframe']}] — {z['status']}")
            lines.append(f"    Zone level: {z['level_name']}")
            lines.append(f"    Structure created: {created_str}")
            lines.append(f"    Entry Price: {_fmt_num(z['entry_price'])}")
            lines.append(f"    Stop Loss (ATR): {_fmt_num(z['stop_price'])}")
            lines.append(f"    Take Profit: {_fmt_num(z['target_price'])}")
            lines.append(f"    Risk:Reward Ratio: 1:{_fmt_num(z['actual_rr'], 2)}")
            lines.append(f"    Confluence Score: {z['score']}/100 ({breakdown})")
            lines.append(f"    Swing Structure: {_fmt_num(z['swing_low'])} -> {_fmt_num(z['swing_high'])}")
            if z["touched_at"]:
                lines.append(f"    Touched at: {tz.format_both(datetime.fromisoformat(z['touched_at']))}")
            if z["resolved_at"]:
                lines.append(f"    Resolved at: {tz.format_both(datetime.fromisoformat(z['resolved_at']))}")
    else:
        lines.append("--- QUALIFIED TRADES ---")
        lines.append("Is period mein koi naya setup qualify nahi hua.")

    lines.append("\n--- REJECTED SETUPS SUMMARY ---")
    if rejected:
        reason_summary = {}
        for r in rejected:
            reason_summary[r["reason_code"]] = reason_summary.get(r["reason_code"], 0) + 1
        for reason, count in sorted(reason_summary.items(), key=lambda x: -x[1]):
            lines.append(f"  - {reason}: {count}")
    else:
        lines.append("Is period mein koi setup reject nahi hua.")

    lines.append(f"\n{'=' * 55}")
    return "\n".join(lines)


def generate_welcome_email() -> str:
    lines = [
        "=" * 55,
        "TRADING SYSTEM — INTRADAY FIBONACCI STARTED",
        "=" * 55,
        "",
        f"System start time: {tz.format_both(datetime.now(timezone.utc))}",
        "",
        "Dual Reports automatically sent twice daily:",
        "  - Morning Report:   06:00 AM PKT",
        "  - Evening Report:   06:00 PM PKT",
        "",
        "Each report contains both Current Period Activity, Dynamic Scan Coins List, and Cumulative Rolling Progress.",
        "=" * 55,
    ]
    return "\n".join(lines)


def is_first_ever_run() -> bool:
    return db.get_config("system_initialized") is None


def mark_system_initialized():
    db.set_config("system_initialized", "true")
    now_iso = datetime.now(timezone.utc).isoformat()
    db.set_config("last_report_boundary", now_iso)
    for period in ("3day", "15day", "monthly"):
        db.set_config(f"last_report_{period}", now_iso)


def _next_boundary_after(after_utc: datetime) -> tuple:
    after_pkt = tz.to_pkt(after_utc)
    candidates = []
    for day_offset in (0, 1):
        day = after_pkt.date() + timedelta(days=day_offset)
        for period_key, t in (("daily", DAILY_REPORT_TIME_PKT), ("halfday", HALFDAY_REPORT_TIME_PKT)):
            candidate_pkt = datetime.combine(day, t, tzinfo=tz.PKT)
            if candidate_pkt > after_pkt:
                candidates.append((candidate_pkt, period_key))
    candidates.sort(key=lambda c: c[0])
    boundary_pkt, period_key = candidates[0]
    return boundary_pkt.astimezone(timezone.utc), period_key


def due_intraday_reports(max_catchup: int = 6) -> list:
    labels = {"daily": "Morning Report (06:00 AM PKT)", "halfday": "Evening Report (06:00 PM PKT)"}
    last_boundary_iso = db.get_config("last_report_boundary")
    cursor = datetime.fromisoformat(last_boundary_iso) if last_boundary_iso else datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)

    due = []
    for _ in range(max_catchup):
        boundary_utc, period_key = _next_boundary_after(cursor)
        if boundary_utc > now:
            break
        due.append((period_key, labels[period_key], cursor, boundary_utc))
        cursor = boundary_utc

    return due


def mark_boundary_sent(boundary_dt: datetime):
    db.set_config("last_report_boundary", boundary_dt.isoformat())


def should_send_report(period: str) -> tuple:
    now = datetime.now(timezone.utc)
    last_sent_key = f"last_report_{period}"
    last_sent = db.get_config(last_sent_key)

    windows = {
        "3day": timedelta(days=3),
        "15day": timedelta(days=15),
        "monthly": timedelta(days=30),
    }
    window = windows.get(period)
    if window is None:
        return False, now, now

    due = last_sent is None or (now - datetime.fromisoformat(last_sent)) >= window
    start_dt = now - window

    return due, start_dt, now


def mark_period_sent(period: str, when: datetime):
    db.set_config(f"last_report_{period}", when.isoformat())
