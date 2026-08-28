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
    all_zones = db.get_all_zones()
    wins = [z for z in all_zones if z["status"] == "WIN"]
    losses = [z for z in all_zones if z["status"] == "LOSS"]
    breakevens = [z for z in all_zones if z["status"] == "BREAKEVEN"]
    pending = [z for z in all_zones if z["status"] in ("PENDING", "ACTIVE")]
    expired = [z for z in all_zones if z["status"] == "EXPIRED"]
    timed_out = [z for z in all_zones if z["status"] == "TIMEOUT"]

    resolved_count = len(wins) + len(losses)
    win_rate = (len(wins) / resolved_count * 100) if resolved_count > 0 else 0.0

    fee_cost = (0.075 + 0.04) / 100 * 2
    net_pnl = sum((z.get("actual_rr") or 0) - fee_cost for z in wins) - sum(1.0 + fee_cost for z in losses)
    net_pnl += sum((z.get("actual_rr") or 0) - fee_cost for z in breakevens if (z.get("actual_rr") or 0) > 0)

    gross_profit = sum(z.get("actual_rr") or 0 for z in wins) + sum(z.get("actual_rr") or 0 for z in breakevens if (z.get("actual_rr") or 0) > 0)
    gross_loss = len(losses) * 1.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 1.0)
    pf_str = f"{profit_factor:.2f}" if profit_factor != float("inf") else "inf"

    # Drawdown and streaks calculation
    cum_r = 0.0
    peak_r = 0.0
    max_dd = 0.0
    cur_consec_wins = 0
    cur_consec_losses = 0
    max_consec_wins = 0
    max_consec_losses = 0

    for z in sorted(all_zones, key=lambda x: str(x.get("created_at", ""))):
        st = z["status"]
        if st == "WIN":
            r_val = (z.get("actual_rr") or 1.5) - fee_cost
            cum_r += r_val
            cur_consec_wins += 1
            cur_consec_losses = 0
        elif st == "LOSS":
            cum_r -= (1.0 + fee_cost)
            cur_consec_losses += 1
            cur_consec_wins = 0
        elif st == "BREAKEVEN":
            r_val = (z.get("actual_rr") or 0.0) - fee_cost if (z.get("actual_rr") or 0.0) > 0 else -fee_cost
            cum_r += r_val
            cur_consec_wins = 0
            cur_consec_losses = 0
        else:
            continue

        peak_r = max(peak_r, cum_r)
        max_dd = max(max_dd, peak_r - cum_r)
        max_consec_wins = max(max_consec_wins, cur_consec_wins)
        max_consec_losses = max(max_consec_losses, cur_consec_losses)

    lines = []
    lines.append("--- CUMULATIVE ROLLING PROGRESS (Day 1 se Aaj Tak) ---")
    lines.append(f"Backtest Start Date (Day 1): {tz.format_both(_get_system_start_dt())}")
    lines.append(f"Current Date:               {tz.format_both(end_dt)}")
    lines.append(f"Total Trades Qualified:     {len(all_zones)}")
    lines.append(f"  Wins:                     {len(wins)}")
    lines.append(f"  Losses:                   {len(losses)}")
    lines.append(f"  Breakevens (0R / Partial):{len(breakevens)}")
    lines.append(f"  Active/Pending:           {len(pending)}")
    lines.append(f"  Expired (never touched):  {len(expired)}")
    lines.append(f"  Timed Out (range end):    {len(timed_out)}")
    lines.append(f"Cumulative Win Rate:        {win_rate:.1f}%")
    lines.append(f"Cumulative Net P&L (R):     {net_pnl:+.2f} R")
    lines.append(f"Profit Factor:              {pf_str}")
    lines.append(f"Max Drawdown:               {max_dd:.2f} R")
    lines.append(f"Max Consecutive Wins:       {max_consec_wins}")
    lines.append(f"Max Consecutive Losses:     {max_consec_losses}")

    lines.append("")
    return "\n".join(lines)


def _cumulative_all_time_ledger_section() -> str:
    """
    Day 1 se aaj tak jitne bhi zones qualify hue hain, unka complete running ledger
    user ke pasandeeda detailed block structure mein return karta hai.
    """
    all_zones = db.get_all_zones()
    lines = []
    lines.append(f"--- CUMULATIVE ALL-TIME TRADES & ZONES LEDGER (Day 1 se Aaj Tak: Total {len(all_zones)} Zones) ---")
    
    if not all_zones:
        lines.append("Abhi tak koi trade qualify nahi hui.")
        lines.append("")
        return "\n".join(lines)

    total_wins = sum(1 for z in all_zones if z["status"] == "WIN")
    total_losses = sum(1 for z in all_zones if z["status"] == "LOSS")
    total_be = sum(1 for z in all_zones if z["status"] == "BREAKEVEN")
    total_pending = sum(1 for z in all_zones if z["status"] in ("PENDING", "ACTIVE"))
    total_expired = sum(1 for z in all_zones if z["status"] == "EXPIRED")
    total_timeout = sum(1 for z in all_zones if z["status"] == "TIMEOUT")

    resolved_count = total_wins + total_losses
    cum_wr = (total_wins / resolved_count * 100) if resolved_count > 0 else 0.0

    lines.append(f"Cumulative Summary: {len(all_zones)} Total | {total_wins} Wins | {total_losses} Losses | {total_be} Breakevens | {total_pending} Pending | {total_expired} Expired | {total_timeout} Timeouts")
    lines.append(f"Cumulative Win Rate: {cum_wr:.1f}% ({total_wins}/{resolved_count} resolved)\n")

    for idx, z in enumerate(all_zones, 1):
        status = z.get("status", "PENDING")
        created_str = tz.format_both(datetime.fromisoformat(z["created_at"])) if z.get("created_at") else "N/A"
        breakdown = json.loads(z["score_breakdown"]) if z.get("score_breakdown") else {}

        lines.append(f"\n  [#{idx:>02}] {z['coin']} [{z['timeframe']}] — {status}")
        lines.append(f"    Zone level: {z.get('level_name', '78.6% OTE')}")
        lines.append(f"    Structure created: {created_str}")
        lines.append(f"    Entry Price: {_fmt_num(z.get('entry_price'))}")
        lines.append(f"    Stop Loss (Safe 1.75x ATR): {_fmt_num(z.get('stop_price'))}")
        target_p = z.get('target_price')
        entry_p = z.get('entry_price')
        if target_p and entry_p and target_p > entry_p:
            lock_p = entry_p + (target_p - entry_p) * 0.25
            lines.append(f"    60% Profit Lock Floor: {_fmt_num(lock_p)} (+0.40R Cash Profit)")
        lines.append(f"    Take Profit (95% Target): {_fmt_num(target_p)}")
        lines.append(f"    Risk:Reward Ratio: 1:{_fmt_num(z.get('actual_rr'), 2)}")
        lines.append(f"    Confluence Score: {z.get('score', 0)}/100 ({breakdown})")
        lines.append(f"    Swing Structure: {_fmt_num(z.get('swing_low'))} -> {_fmt_num(z.get('swing_high'))}")

        if z.get("touched_at"):
            try:
                touched_str = tz.format_both(datetime.fromisoformat(z["touched_at"]))
            except Exception:
                touched_str = str(z["touched_at"])
            lines.append(f"    Touched at: {touched_str}")

        if z.get("resolved_at"):
            try:
                resolved_str = tz.format_both(datetime.fromisoformat(z["resolved_at"]))
            except Exception:
                resolved_str = str(z["resolved_at"])
            lines.append(f"    Resolved at: {resolved_str}")

        # Outcome summary
        if status == "WIN":
            lines.append(f"    Trade Outcome: +{_fmt_num(z.get('actual_rr'), 2)} R (WIN)")
        elif status == "LOSS":
            lines.append(f"    Trade Outcome: -1.00 R (LOSS)")
        elif status == "BREAKEVEN":
            lines.append(f"    Trade Outcome:  0.00 R (BREAKEVEN)")
        elif status in ("PENDING", "ACTIVE"):
            lines.append(f"    Trade Outcome: ACTIVE / MONITORING")
        elif status == "EXPIRED":
            lines.append(f"    Trade Outcome: EXPIRED (Invalidated before green confirmation)")
        elif status == "TIMEOUT":
            lines.append(f"    Trade Outcome: TIMED OUT (Sideways chop)")

        if z.get("post_sl_details"):
            lines.append(f"    Post-SL Diagnosis: {z['post_sl_details']}")

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
        # Change 1: Complete Day 1 to Today all-time trades ledger in every email!
        lines.append(_cumulative_all_time_ledger_section())
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
            lines.append(f"    Entry Price: {_fmt_num(z.get('entry_price'))}")
            lines.append(f"    Stop Loss (Safe 1.75x ATR): {_fmt_num(z.get('stop_price'))}")
            target_p = z.get('target_price')
            entry_p = z.get('entry_price')
            if target_p and entry_p and target_p > entry_p:
                lock_p = entry_p + (target_p - entry_p) * 0.25
                lines.append(f"    60% Profit Lock Floor: {_fmt_num(lock_p)} (+0.40R Cash Profit)")
            lines.append(f"    Take Profit (95% Target): {_fmt_num(target_p)}")
            lines.append(f"    Risk:Reward Ratio: 1:{_fmt_num(z.get('actual_rr'), 2)}")
            lines.append(f"    Confluence Score: {z.get('score', 0)}/100 ({breakdown})")
            lines.append(f"    Swing Structure: {_fmt_num(z.get('swing_low'))} -> {_fmt_num(z.get('swing_high'))}")
            if z["touched_at"]:
                lines.append(f"    Touched at: {tz.format_both(datetime.fromisoformat(z['touched_at']))}")
            if z["resolved_at"]:
                lines.append(f"    Resolved at: {tz.format_both(datetime.fromisoformat(z['resolved_at']))}")
            if z.get("post_sl_details"):
                lines.append(f"    Post-SL Diagnosis: {z['post_sl_details']}")
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


def generate_3day_failure_diagnosis_report(start_dt: datetime, end_dt: datetime) -> str:
    """
    Change 2: Har 3 din ke cycle ke baad tamam non-winning setups (Loss, Timeout, Expired, Rejected)
    ka in-depth failure & post-SL price action breakdown generate karta hai.
    """
    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    zones = db.get_zones_in_window(start_iso, end_iso)
    rejected = db.get_rejected_in_window(start_iso, end_iso)

    wins = [z for z in zones if z["status"] == "WIN"]
    losses = [z for z in zones if z["status"] == "LOSS"]
    expired = [z for z in zones if z["status"] == "EXPIRED"]
    timed_out = [z for z in zones if z["status"] == "TIMEOUT"]

    lines = []
    lines.append(f"{'=' * 60}")
    lines.append("3-DAY CYCLE NON-WINNING & FAILURE DIAGNOSTIC REPORT")
    lines.append(f"Evaluation Cycle: {tz.format_both(start_dt)} -> {tz.format_both(end_dt)}")
    lines.append(f"{'=' * 60}\n")

    lines.append("--- 3-DAY PERFORMANCE SUMMARY ---")
    lines.append(f"Total Qualified Setups:     {len(zones)}")
    lines.append(f"  Successful Wins:          {len(wins)}")
    lines.append(f"  Losses:                   {len(losses)}")
    lines.append(f"  Expired (Invalidated):    {len(expired)}")
    lines.append(f"  Timed Out (Sideways):     {len(timed_out)}")
    lines.append(f"Total Filtered Rejections:  {len(rejected)}\n")

    # Section 1: Detailed Loss Diagnoses & Post-Stop Loss Price Action
    lines.append("============================================================")
    lines.append("SECTION 1: LOSS TRADES DEEP DIAGNOSIS & POST-SL ACTION")
    lines.append("============================================================")
    if losses:
        fakeout_count = 0
        breakdown_count = 0
        for idx, z in enumerate(losses, 1):
            created_str = tz.format_both(datetime.fromisoformat(z["created_at"])) if z.get("created_at") else "N/A"
            resolved_str = tz.format_both(datetime.fromisoformat(z["resolved_at"])) if z.get("resolved_at") else "N/A"
            post_details = z.get("post_sl_details") or "Price did not recover after SL hit."
            behavior = z.get("post_sl_behavior") or "STRUCTURE_BREAKDOWN"

            if behavior == "WICK_SWEEP_FAKEOUT":
                fakeout_count += 1
            else:
                breakdown_count += 1

            lines.append(f"\n[Loss #{idx}] {z['coin']} [{z['timeframe']}] — {z['level_name']}")
            lines.append(f"  • Entry: {_fmt_num(z['entry_price'])} | Stop Loss: {_fmt_num(z['stop_price'])} | TP: {_fmt_num(z['target_price'])}")
            lines.append(f"  • Confluence Score: {z['score']}/100 | Risk:Reward: 1:{_fmt_num(z['actual_rr'], 2)}")
            lines.append(f"  • Created: {created_str}")
            lines.append(f"  • Resolved (SL Hit): {resolved_str}")
            lines.append(f"  • Post-SL Behavior: {behavior}")
            lines.append(f"  • Price Action Analysis: {post_details}")

        lines.append("\n📊 Loss Behavior Breakdown:")
        lines.append(f"  - Fakeout / Wick-Sweep Losses: {fakeout_count} (Setup direction was right, SL was tight)")
        lines.append(f"  - Genuine Cascade Breakdowns:  {breakdown_count} (SL protected capital from deeper dump)")
    else:
        lines.append("✅ Is 3-day cycle mein koi trade loss nahi hui! Excellent performance.")

    # Section 2: Expired & Invalidated Setups
    lines.append("\n============================================================")
    lines.append("SECTION 2: EXPIRED & INVALIDATED SETUPS (NO ENTRY)")
    lines.append("============================================================")
    if expired:
        lines.append(f"Total {len(expired)} setup(s) expire/invalidate hue (Green confirmation na milne ki wajah se capital bacha):")
        for idx, z in enumerate(expired, 1):
            lines.append(f"  {idx}. {z['coin']} [{z['timeframe']}] {z['level_name']} @ {_fmt_num(z['entry_price'])} (Score: {z['score']}/100)")
            lines.append(f"     Reason: Price dropped through zone without bullish green close.")
    else:
        lines.append("Is 3-day cycle mein koi setup expire nahi hua.")

    # Section 3: Timed Out Setups
    lines.append("\n============================================================")
    lines.append("SECTION 3: TIMED-OUT SETUPS (SIDEWAYS CONSOLIDATION)")
    lines.append("============================================================")
    if timed_out:
        for idx, z in enumerate(timed_out, 1):
            lines.append(f"  {idx}. {z['coin']} [{z['timeframe']}] {z['level_name']} — Maximum holding bars exceed hue without hitting TP/SL.")
    else:
        lines.append("Is 3-day cycle mein koi setup timeout nahi hua.")

    # Section 4: Filter Rejection Root Causes
    lines.append("\n============================================================")
    lines.append("SECTION 4: TOP FILTER REJECTION ROOT CAUSES")
    lines.append("============================================================")
    if rejected:
        reasons = {}
        for r in rejected:
            reasons[r["reason_code"]] = reasons.get(r["reason_code"], 0) + 1
        for r_code, count in sorted(reasons.items(), key=lambda x: -x[1]):
            lines.append(f"  • {r_code}: {count} instance(s)")
    else:
        lines.append("Koi setup reject nahi hua.")

    # Section 5: Strategic Takeaway & Recommendations
    lines.append("\n============================================================")
    lines.append("SECTION 5: STRATEGIC ACTIONABLE TAKEAWAYS")
    lines.append("============================================================")
    if losses:
        lines.append("• Stop Loss Buffer Review: Check whether Wick-Sweep Fakeouts exceed Cascade Breakdowns.")
        lines.append("• Reversal Confirmation: Green closed candle entry filter continues to prevent falling knife traps.")
    else:
        lines.append("• System executing with high conviction and strict discipline.")

    lines.append(f"\n{'=' * 60}")
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
