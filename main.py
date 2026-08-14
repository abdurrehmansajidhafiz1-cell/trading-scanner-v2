"""
Main entry point for GitHub Actions & External Cron Triggers.
1. Scans market using Dynamic Binance Liquidity Engine & Intraday Fib Strategy
2. Resolves trades chronologically
3. Sends Dual Reports (06:00 AM & 06:00 PM PKT) with Period Activity & Cumulative Rolling Progress
4. Handles exit codes for CI/CD failure detection
"""

import sys
import traceback
from datetime import datetime, timezone

import logging_setup  # noqa: F401
import logging

import database as db
from scanner import scan_once
from reporting import (
    generate_report, should_send_report, due_intraday_reports,
    mark_boundary_sent, mark_period_sent,
    generate_welcome_email, is_first_ever_run, mark_system_initialized,
)
from email_sender import send_email, send_error_alert
import timezone_utils as tz

logger = logging.getLogger("trading_scanner")


def check_and_send_reports():
    if is_first_ever_run():
        logger.info("First run initialization — sending Welcome Email.")
        send_email("Trading System — Intraday Fibonacci Engine Started", generate_welcome_email())
        mark_system_initialized()
        return

    # Dual Reports (06:00 AM PKT & 06:00 PM PKT)
    for period_key, period_label, start_dt, end_dt in due_intraday_reports():
        logger.info(f"{period_label} due ({tz.format_both(start_dt)} -> {tz.format_both(end_dt)}), generating report...")
        report_text = generate_report(period_label, start_dt, end_dt, include_cumulative=True)
        subject = f"Trading System — {period_label} ({tz.format_pkt(end_dt, '%Y-%m-%d %I:%M %p')})"
        sent = send_email(subject, report_text)
        if sent:
            mark_boundary_sent(end_dt)
        else:
            logger.error(f"{period_label} email send failed — boundary not advanced, will retry next run.")
            break

    # Periodic 15-Day & Monthly Reports
    periods = [
        ("3day", "3-Day Summary Report"),
        ("15day", "15-Day Strategy Evaluation & Failure Diagnosis Report"),
        ("monthly", "Monthly Performance Report"),
    ]

    for period_key, period_label in periods:
        due, start_dt, end_dt = should_send_report(period_key)
        if due:
            logger.info(f"{period_label} due, generating...")
            report_text = generate_report(period_label, start_dt, end_dt, include_cumulative=True)
            subject = f"Trading System — {period_label} ({tz.format_pkt(end_dt, '%Y-%m-%d')})"
            sent = send_email(subject, report_text)
            if sent:
                mark_period_sent(period_key, end_dt)
            else:
                logger.error(f"{period_label} email send failed.")


def main():
    logger.info(f"=== Scan run started: {datetime.now(timezone.utc).isoformat()} "
                f"({tz.format_pkt(datetime.now(timezone.utc))}) ===")
    db.init_db()

    scan_failed = False
    error_summary = None
    error_traceback = None
    try:
        results = scan_once()
        logger.info(f"Scan complete. {len(results)} coin(s) currently qualifying.")
    except Exception as e:
        scan_failed = True
        error_summary = str(e)
        error_traceback = traceback.format_exc()
        logger.error(f"SCAN CYCLE FAIL: {e}")
        logger.error(error_traceback)
        send_error_alert(error_summary, error_traceback)

    try:
        check_and_send_reports()
    except Exception as e:
        logger.error(f"Report/email error: {e}")
        logger.error(traceback.format_exc())

    logger.info("=== Scan run complete ===")

    if scan_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
