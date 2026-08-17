"""
hist_backtester.py — Month-by-Month + Day-by-Day Historical Backtest Engine.
Bilkul same Fibonacci strategy rules use karta hai jo live 15-day system mein hain.
Zero look-ahead bias: har candle sirf apne time tak ka data dekhti hai.
Existing backtester.py se bilkul independent hai.
"""

import sys
import os
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import pandas as pd
import numpy as np

# Parent directory ko sys.path mein add karo taake signal_engine import ho sake
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signal_engine import analyze

logger = logging.getLogger("hist_backtest")


def _truncate_to(df: pd.DataFrame, cutoff_time) -> pd.DataFrame:
    """Look-ahead bias prevention: sirf cutoff_time tak ki candles rakhta hai."""
    return df[df["timestamp"] <= cutoff_time].reset_index(drop=True)


def _classify_month_market(df_daily: pd.DataFrame) -> str:
    """Month ke overall market condition classify karta hai (Bull/Bear/Sideways)."""
    if len(df_daily) < 5:
        return "UNKNOWN"
    start_price = df_daily["close"].iloc[0]
    end_price   = df_daily["close"].iloc[-1]
    change_pct  = (end_price - start_price) / start_price * 100
    if change_pct > 10:
        return "STRONG BULL"
    elif change_pct > 3:
        return "BULL"
    elif change_pct < -10:
        return "STRONG BEAR"
    elif change_pct < -3:
        return "BEAR"
    else:
        return "SIDEWAYS / CONSOLIDATION"


def _resolve_zone(zone: dict, df_after_entry: pd.DataFrame, tf_cfg: dict) -> dict:
    """
    Zone ko price action ke against test karta hai.
    Returns: updated zone with status (WIN/LOSS/EXPIRED/TIMEOUT)
    """
    touched    = False
    touched_at = None
    age_limit  = tf_cfg["max_structure_age_bars"] * 3

    for idx, (_, candle) in enumerate(df_after_entry.iterrows()):
        if not touched:
            touch_threshold = zone["entry_price"] * (1 + tf_cfg["zone_tolerance_pct"] / 100)
            if candle["low"] <= touch_threshold:
                touched    = True
                touched_at = str(candle["timestamp"])
                zone["touched_at"] = touched_at

        if touched:
            if candle["high"] >= zone["target_price"]:
                zone["status"]      = "WIN"
                zone["resolved_at"] = str(candle["timestamp"])
                return zone
            elif candle["low"] <= zone["stop_price"]:
                zone["status"]      = "LOSS"
                zone["resolved_at"] = str(candle["timestamp"])
                return zone

        if idx > age_limit:
            if not touched:
                zone["status"]      = "EXPIRED"
                zone["resolved_at"] = str(candle["timestamp"])
            else:
                zone["status"]      = "TIMEOUT"
                zone["resolved_at"] = str(candle["timestamp"])
            return zone

    zone["status"]      = "PENDING"
    zone["resolved_at"] = None
    return zone


def backtest_single_coin_month(
    df_main: pd.DataFrame,
    df_daily: pd.DataFrame,
    df_intermediate: pd.DataFrame | None,
    df_btc_1h: pd.DataFrame | None,
    coin: str,
    timeframe: str,
    month_start: datetime,
    month_end: datetime,
    tf_cfg: dict,
) -> list[dict]:
    """
    Ek coin ka ek month ka candle-by-candle backtest chalata hai.
    Returns: list of zone dicts (har zone mein status, scores, timestamps)
    """
    if len(df_main) < 100:
        return []

    # Sirf is month ke indices
    month_start_ts = pd.Timestamp(month_start)
    month_end_ts   = pd.Timestamp(month_end)

    month_candles = df_main[
        (df_main["timestamp"] >= month_start_ts) &
        (df_main["timestamp"] <  month_end_ts)
    ]

    if len(month_candles) == 0:
        return []

    zones_found = []
    last_recorded_zone_price = None

    for i, (_, _candle) in enumerate(month_candles.iterrows()):
        candle_time = _candle["timestamp"]
        candle_idx  = df_main.index[df_main["timestamp"] == candle_time].tolist()
        if not candle_idx:
            continue
        abs_idx = candle_idx[0]

        df_slice           = df_main.iloc[: abs_idx + 1].reset_index(drop=True)
        df_daily_slice     = _truncate_to(df_daily, candle_time)
        df_inter_slice     = _truncate_to(df_intermediate, candle_time) if df_intermediate is not None else None
        df_btc_slice       = _truncate_to(df_btc_1h, candle_time) if df_btc_1h is not None else None

        prev_state = {
            "last_recorded_zone_price": last_recorded_zone_price,
            "swing_high": None, "swing_low": None,
            "swing_high_time": None, "swing_low_time": None,
        } if last_recorded_zone_price else None

        result = analyze(coin, timeframe, df_slice, df_daily_slice, df_inter_slice, prev_state, df_btc_slice)

        if result.qualifies and result.best_zone_price != last_recorded_zone_price:
            last_recorded_zone_price = result.best_zone_price

            # Resolve zone against future candles
            df_after = df_main.iloc[abs_idx + 1:].reset_index(drop=True)
            zone = {
                "coin":         coin,
                "timeframe":    timeframe,
                "created_at":   str(candle_time),
                "entry_price":  result.best_zone_price,
                "stop_price":   result.stop_price,
                "target_price": result.target_price,
                "swing_low":    result.swing_low,
                "swing_high":   result.swing_high,
                "score":        result.best_score,
                "actual_rr":    result.actual_rr,
                "level_name":   result.best_zone_name,
                "score_breakdown": result.score_breakdown,
                "status":       "PENDING",
                "touched_at":   None,
                "resolved_at":  None,
            }
            zone = _resolve_zone(zone, df_after, tf_cfg)
            zones_found.append(zone)

    return zones_found


def compute_month_metrics(zones: list[dict], fee_pct: float = 0.075, slip_pct: float = 0.04) -> dict:
    """Month ke zones se complete performance metrics calculate karta hai."""
    wins   = [z for z in zones if z["status"] == "WIN"]
    losses = [z for z in zones if z["status"] == "LOSS"]
    resolved = wins + losses

    total_cost_pct = (fee_pct + slip_pct) / 100 * 2   # round-trip

    win_r  = sum(z["actual_rr"] - total_cost_pct for z in wins)
    loss_r = sum(-1.0 - total_cost_pct for z in losses)
    net_pnl_r = win_r + loss_r

    win_rate = (len(wins) / len(resolved) * 100) if resolved else 0.0
    profit_factor = (win_r / abs(loss_r)) if abs(loss_r) > 0 else (float("inf") if win_r > 0 else 1.0)

    # Max drawdown calculation
    running_r  = 0.0
    peak_r     = 0.0
    max_dd     = 0.0
    consec_wins = consec_losses = 0
    max_consec_wins = max_consec_losses = 0
    streak_w = streak_l = 0

    for z in zones:
        if z["status"] == "WIN":
            running_r += z["actual_rr"] - total_cost_pct
            streak_w  += 1
            streak_l   = 0
        elif z["status"] == "LOSS":
            running_r += -1.0 - total_cost_pct
            streak_l  += 1
            streak_w   = 0

        peak_r = max(peak_r, running_r)
        max_dd = max(max_dd, peak_r - running_r)
        max_consec_wins   = max(max_consec_wins,   streak_w)
        max_consec_losses = max(max_consec_losses, streak_l)

    return {
        "total_trades":         len(zones),
        "wins":                 len(wins),
        "losses":               len(losses),
        "expired":              sum(1 for z in zones if z["status"] == "EXPIRED"),
        "timed_out":            sum(1 for z in zones if z["status"] == "TIMEOUT"),
        "pending":              sum(1 for z in zones if z["status"] == "PENDING"),
        "win_rate_pct":         win_rate,
        "net_pnl_r":            net_pnl_r,
        "profit_factor":        profit_factor,
        "max_drawdown_r":       max_dd,
        "max_consec_wins":      max_consec_wins,
        "max_consec_losses":    max_consec_losses,
    }


def compute_day_breakdown(zones: list[dict]) -> dict:
    """Month ke zones ko day-by-day breakdown mein aggregate karta hai."""
    day_data = defaultdict(lambda: {"zones": 0, "wins": 0, "losses": 0, "pnl_r": 0.0})

    total_cost_pct = (0.075 + 0.04) / 100 * 2

    for z in zones:
        try:
            day_str = str(z["created_at"])[:10]
        except Exception:
            continue
        day_data[day_str]["zones"] += 1
        if z["status"] == "WIN":
            day_data[day_str]["wins"]  += 1
            day_data[day_str]["pnl_r"] += z["actual_rr"] - total_cost_pct
        elif z["status"] == "LOSS":
            day_data[day_str]["losses"] += 1
            day_data[day_str]["pnl_r"]  += -1.0 - total_cost_pct

    return dict(sorted(day_data.items()))
