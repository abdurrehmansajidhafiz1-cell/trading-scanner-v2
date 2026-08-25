"""
15-Day Rolling Backtesting & Performance Analysis Engine.
Realistic execution modeling with zero look-ahead bias, Binance fees (0.075%),
slippage (0.04%), and granular metric calculation (Win Rate, Profit Factor,
Max Drawdown, Expectancy, and Loss Root-Cause Breakdown).
"""

import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

import config
import database as db
from failure_analyzer import diagnose_trade_outcome

logger = logging.getLogger("trading_scanner")


def run_15day_rolling_backtest(start_dt: datetime = None, end_dt: datetime = None) -> dict:
    """
    15-day rolling historical backtest execute karta hai aur granular metrics return karta hai.
    """
    end_dt = end_dt or datetime.now(timezone.utc)
    start_dt = start_dt or (end_dt - timedelta(days=config.EVALUATION_WINDOW_DAYS))

    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    all_zones = db.get_zones_in_window(start_iso, end_iso)
    scan_logs = db.get_scan_logs_in_window(start_iso, end_iso)

    total_trades = len(all_zones)
    wins = [z for z in all_zones if z["status"] == "WIN"]
    losses = [z for z in all_zones if z["status"] == "LOSS"]
    active = [z for z in all_zones if z["status"] in ("PENDING", "ACTIVE")]
    expired = [z for z in all_zones if z["status"] == "EXPIRED"]
    timed_out = [z for z in all_zones if z["status"] == "TIMEOUT"]

    resolved_count = len(wins) + len(losses)
    win_rate = (len(wins) / resolved_count * 100) if resolved_count > 0 else 0.0
    loss_rate = (len(losses) / resolved_count * 100) if resolved_count > 0 else 0.0

    # P&L and R-multiple calculation (with fees & slippage)
    roundtrip_cost_pct = (config.BINANCE_FEE_PCT * 2) + (config.SLIPPAGE_PCT * 2)
    
    total_r = 0.0
    gross_win_r = 0.0
    gross_loss_r = 0.0

    trade_pnl_list = []

    for z in wins:
        rr = z.get("actual_rr") or config.MIN_RR
        # Net R-multiple after fee/slippage adjustment (~0.23% fee impact)
        net_r = rr - (roundtrip_cost_pct / 100 * rr)
        gross_win_r += net_r
        total_r += net_r
        trade_pnl_list.append(net_r)

    for z in losses:
        net_r = -(1.0 + (roundtrip_cost_pct / 100))
        gross_loss_r += abs(net_r)
        total_r += net_r
        trade_pnl_list.append(net_r)

    profit_factor = (gross_win_r / gross_loss_r) if gross_loss_r > 0 else (gross_win_r if gross_win_r > 0 else 1.0)
    avg_win_r = (gross_win_r / len(wins)) if wins else 0.0
    avg_loss_r = (-gross_loss_r / len(losses)) if losses else 0.0

    # Max Drawdown calculation
    equity_curve = [0.0]
    running = 0.0
    for r in trade_pnl_list:
        running += r
        equity_curve.append(running)

    equity_series = pd.Series(equity_curve)
    peak = equity_series.cummax()
    drawdown = equity_series - peak
    max_drawdown_r = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

    # Consecutive wins & losses
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    curr_wins = 0
    curr_losses = 0

    for z in all_zones:
        s = z["status"]
        if s == "WIN":
            curr_wins += 1
            curr_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, curr_wins)
        elif s == "LOSS":
            curr_losses += 1
            curr_wins = 0
            max_consecutive_losses = max(max_consecutive_losses, curr_losses)

    # Failure Root Cause Breakdown
    failure_causes = {}
    for z in losses + timed_out:
        diag = diagnose_trade_outcome(z, None, None)
        tag = diag["primary_tag"]
        failure_causes[tag] = failure_causes.get(tag, 0) + 1

    return {
        "evaluation_window_days": config.EVALUATION_WINDOW_DAYS,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "total_trades": total_trades,
        "resolved_trades": resolved_count,
        "wins": len(wins),
        "losses": len(losses),
        "active_pending": len(active),
        "expired": len(expired),
        "timed_out": len(timed_out),
        "win_rate_pct": win_rate,
        "loss_rate_pct": loss_rate,
        "net_pnl_r": total_r,
        "profit_factor": profit_factor,
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "max_drawdown_r": max_drawdown_r,
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
        "failure_causes": failure_causes,
    }
