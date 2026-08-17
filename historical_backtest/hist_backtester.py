"""
hist_backtester.py — Month-by-Month + Day-by-Day Historical Backtest Engine.

Purpose:
- Existing live signal_engine.py ko use karke historical replay karna.
- Zero look-ahead bias maintain karna.
- Har candle par sirf us waqt tak available data use karna.
- Qualified zones ko future candles ke against resolve karna.
- Same-candle TP + SL ko conservative LOSS count karna.
- Trade lifetime ko structure-age se independently handle karna.
"""

import sys
import os
import logging
from collections import defaultdict

import pandas as pd
import numpy as np


# ============================================================
# PATH SETUP
# ============================================================

PARENT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

sys.path.insert(0, PARENT_DIR)


# ============================================================
# LIVE STRATEGY ENGINE
# ============================================================

from signal_engine import analyze


logger = logging.getLogger("hist_backtest")


# ============================================================
# HELPERS
# ============================================================

def _truncate_to(
    df: pd.DataFrame | None,
    cutoff_time,
) -> pd.DataFrame | None:
    """
    Look-ahead bias prevention.

    Sirf woh candles return karta hai jo cutoff_time tak
    available hain.
    """

    if df is None:
        return None

    if df.empty:
        return df.copy()

    return df[
        df["timestamp"] <= cutoff_time
    ].reset_index(drop=True)


def _classify_month_market(
    df_daily: pd.DataFrame,
) -> str:
    """
    Month ke overall market condition ko classify karta hai.

    Classification BTC/daily data ke basis par hoti hai.
    """

    if df_daily is None or len(df_daily) < 5:
        return "UNKNOWN"

    start_price = float(
        df_daily["close"].iloc[0]
    )

    end_price = float(
        df_daily["close"].iloc[-1]
    )

    if start_price <= 0:
        return "UNKNOWN"

    change_pct = (
        (end_price - start_price)
        / start_price
        * 100
    )

    if change_pct > 10:
        return "STRONG BULL"

    if change_pct > 3:
        return "BULL"

    if change_pct < -10:
        return "STRONG BEAR"

    if change_pct < -3:
        return "BEAR"

    return "SIDEWAYS / CONSOLIDATION"


# ============================================================
# ZONE RESOLUTION
# ============================================================

def _resolve_zone(
    zone: dict,
    df_after_entry: pd.DataFrame,
    tf_cfg: dict,
    max_lifetime_bars: int,
    same_candle_tp_sl_is_loss: bool = True,
) -> dict:
    """
    Qualified zone ko future price action ke against resolve karta hai.

    Possible statuses:

        WIN
        LOSS
        EXPIRED
        TIMEOUT
        PENDING

    IMPORTANT:
    Agar same candle mein TP aur SL dono hit ho jayein,
    intrabar order OHLC data se pata nahi hota.

    Conservative assumption:
        TP + SL same candle = LOSS
    """

    if df_after_entry is None or df_after_entry.empty:
        zone["status"] = "PENDING"
        zone["resolved_at"] = None
        zone["touched_at"] = None
        return zone

    entry_price = zone["entry_price"]
    stop_price = zone["stop_price"]
    target_price = zone["target_price"]

    touched = False
    touched_at = None

    # --------------------------------------------------------
    # Zone tolerance
    # --------------------------------------------------------

    tolerance_pct = float(
        tf_cfg.get(
            "zone_tolerance_pct",
            0.0,
        )
    )

    touch_threshold = (
        entry_price
        * (
            1
            + tolerance_pct / 100
        )
    )

    # --------------------------------------------------------
    # Future candle replay
    # --------------------------------------------------------

    for idx, (_, candle) in enumerate(
        df_after_entry.iterrows()
    ):

        candle_low = float(
            candle["low"]
        )

        candle_high = float(
            candle["high"]
        )

        candle_time = str(
            candle["timestamp"]
        )

        # ----------------------------------------------------
        # 1. Check zone touch
        # ----------------------------------------------------

        if not touched:

            if candle_low <= touch_threshold:

                touched = True
                touched_at = candle_time

                zone["touched_at"] = touched_at

        # ----------------------------------------------------
        # 2. Once zone is touched, evaluate TP/SL
        # ----------------------------------------------------

        if touched:

            hit_target = (
                candle_high >= target_price
            )

            hit_stop = (
                candle_low <= stop_price
            )

            # ------------------------------------------------
            # Same candle TP + SL
            # ------------------------------------------------

            if hit_target and hit_stop:

                if same_candle_tp_sl_is_loss:

                    zone["status"] = "LOSS"

                    zone["resolution_reason"] = (
                        "SAME_CANDLE_TP_SL"
                    )

                    zone["resolved_at"] = candle_time

                    return zone

                # Non-conservative fallback
                zone["status"] = "WIN"

                zone["resolution_reason"] = (
                    "SAME_CANDLE_TP_SL_TARGET_FIRST"
                )

                zone["resolved_at"] = candle_time

                return zone

            # ------------------------------------------------
            # TP only
            # ------------------------------------------------

            if hit_target:

                zone["status"] = "WIN"

                zone["resolution_reason"] = (
                    "TARGET_HIT"
                )

                zone["resolved_at"] = candle_time

                return zone

            # ------------------------------------------------
            # SL only
            # ------------------------------------------------

            if hit_stop:

                zone["status"] = "LOSS"

                zone["resolution_reason"] = (
                    "STOP_HIT"
                )

                zone["resolved_at"] = candle_time

                return zone

        # ----------------------------------------------------
        # 3. Trade lifetime
        # ----------------------------------------------------

        if idx + 1 >= max_lifetime_bars:

            if not touched:

                zone["status"] = "EXPIRED"

                zone["resolution_reason"] = (
                    "ZONE_NOT_TOUCHED"
                )

            else:

                zone["status"] = "TIMEOUT"

                zone["resolution_reason"] = (
                    "TRADE_LIFETIME_EXCEEDED"
                )

            zone["resolved_at"] = candle_time

            return zone

    # --------------------------------------------------------
    # Future data khatam ho gaya
    # --------------------------------------------------------

    zone["status"] = "PENDING"
    zone["resolved_at"] = None

    if touched:
        zone["resolution_reason"] = (
            "FUTURE_DATA_ENDED_AFTER_TOUCH"
        )
    else:
        zone["resolution_reason"] = (
            "FUTURE_DATA_ENDED_BEFORE_TOUCH"
        )

    return zone


# ============================================================
# SINGLE COIN / MONTH BACKTEST
# ============================================================

def backtest_single_coin_month(
    df_main: pd.DataFrame,
    df_daily: pd.DataFrame,
    df_intermediate: pd.DataFrame | None,
    df_btc_1h: pd.DataFrame | None,
    coin: str,
    timeframe: str,
    month_start,
    month_end,
    tf_cfg: dict,
    max_lifetime_bars: int | None = None,
    same_candle_tp_sl_is_loss: bool = True,
) -> list[dict]:
    """
    Ek coin + ek timeframe + ek month ka candle-by-candle
    historical replay.

    Har candle par:

        historical slice
              ↓
        signal_engine.analyze()
              ↓
        qualified?
              ↓
        future candles se resolution

    Important:
    analyze() ko sirf current candle tak ka data diya jata hai.
    """

    if df_main is None:
        return []

    if len(df_main) < 100:
        return []

    if max_lifetime_bars is None:

        # Historical config se import yahan deliberately nahi
        # kiya ja raha. Caller explicit lifetime pass karega.

        max_lifetime_bars = (
            tf_cfg.get(
                "max_structure_age_bars",
                18,
            )
            * 3
        )

    month_start_ts = pd.Timestamp(
        month_start
    )

    month_end_ts = pd.Timestamp(
        month_end
    )

    # --------------------------------------------------------
    # Current month candles
    # --------------------------------------------------------

    month_candles = df_main[
        (df_main["timestamp"] >= month_start_ts)
        &
        (df_main["timestamp"] < month_end_ts)
    ]

    if month_candles.empty:
        return []

    zones_found = []

    # Prevent duplicate zone creation at same price.
    last_recorded_zone_price = None

    # --------------------------------------------------------
    # Candle-by-candle replay
    # --------------------------------------------------------

    for _, candle in month_candles.iterrows():

        candle_time = candle["timestamp"]

        # Find absolute dataframe position.
        matching_indices = df_main.index[
            df_main["timestamp"] == candle_time
        ].tolist()

        if not matching_indices:
            continue

        abs_idx = matching_indices[0]

        # ----------------------------------------------------
        # Historical slices
        # ----------------------------------------------------

        df_slice = (
            df_main.iloc[
                : abs_idx + 1
            ]
            .reset_index(drop=True)
        )

        df_daily_slice = _truncate_to(
            df_daily,
            candle_time,
        )

        df_inter_slice = _truncate_to(
            df_intermediate,
            candle_time,
        )

        df_btc_slice = _truncate_to(
            df_btc_1h,
            candle_time,
        )

        # ----------------------------------------------------
        # Previous swing state
        # ----------------------------------------------------

        if last_recorded_zone_price is not None:

            prev_state = {
                "last_recorded_zone_price":
                    last_recorded_zone_price,

                "swing_high": None,
                "swing_low": None,
                "swing_high_time": None,
                "swing_low_time": None,
            }

        else:

            prev_state = None

        # ----------------------------------------------------
        # LIVE SIGNAL ENGINE
        # ----------------------------------------------------

        try:

            result = analyze(
                coin,
                timeframe,
                df_slice,
                (
                    df_daily_slice
                    if df_daily_slice is not None
                    else df_main.head(0)
                ),
                df_inter_slice,
                prev_state,
                df_btc_slice,
            )

        except Exception as e:

            logger.warning(
                "analyze() failed: "
                f"{coin}[{timeframe}] "
                f"{candle_time}: {e}"
            )

            continue

        # ----------------------------------------------------
        # Qualified setup
        # ----------------------------------------------------

        if not result.qualifies:
            continue

        zone_price = result.best_zone_price

        if zone_price is None:
            continue

        # ----------------------------------------------------
        # Duplicate zone protection
        # ----------------------------------------------------

        if (
            last_recorded_zone_price is not None
            and zone_price == last_recorded_zone_price
        ):
            continue

        last_recorded_zone_price = zone_price

        # ----------------------------------------------------
        # Validate required execution values
        # ----------------------------------------------------

        if (
            result.stop_price is None
            or result.target_price is None
            or result.actual_rr is None
        ):
            logger.warning(
                "Qualified signal missing execution values: "
                f"{coin}[{timeframe}] {candle_time}"
            )

            continue

        # ----------------------------------------------------
        # Future candles
        # ----------------------------------------------------

        df_after = (
            df_main.iloc[
                abs_idx + 1:
            ]
            .reset_index(drop=True)
        )

        # ----------------------------------------------------
        # Zone object
        # ----------------------------------------------------

        zone = {
            "coin": coin,
            "timeframe": timeframe,

            "created_at":
                str(candle_time),

            "entry_price":
                result.best_zone_price,

            "stop_price":
                result.stop_price,

            "target_price":
                result.target_price,

            "tp2_price":
                result.tp2_price,

            "swing_low":
                result.swing_low,

            "swing_high":
                result.swing_high,

            "swing_low_time":
                result.swing_low_time,

            "swing_high_time":
                result.swing_high_time,

            "structure_created_at":
                result.structure_created_at,

            "score":
                result.best_score,

            "actual_rr":
                result.actual_rr,

            "level_name":
                result.best_zone_name,

            "score_breakdown":
                result.score_breakdown,

            "status":
                "PENDING",

            "touched_at":
                None,

            "resolved_at":
                None,

            "resolution_reason":
                None,
        }

        # ----------------------------------------------------
        # Resolve
        # ----------------------------------------------------

        zone = _resolve_zone(
            zone=zone,
            df_after_entry=df_after,
            tf_cfg=tf_cfg,
            max_lifetime_bars=max_lifetime_bars,
            same_candle_tp_sl_is_loss=(
                same_candle_tp_sl_is_loss
            ),
        )

        zones_found.append(zone)

    return zones_found


# ============================================================
# MONTH METRICS
# ============================================================

def compute_month_metrics(
    zones: list[dict],
    fee_pct: float = 0.075,
    slip_pct: float = 0.04,
) -> dict:
    """
    Month ke zones se performance metrics calculate karta hai.

    Fee/slippage:
        fee_pct + slippage_pct
        each side par apply hota hai.

    Round-trip cost:
        2 × fee + 2 × slippage
    """

    wins = [
        z for z in zones
        if z["status"] == "WIN"
    ]

    losses = [
        z for z in zones
        if z["status"] == "LOSS"
    ]

    resolved = wins + losses

    # --------------------------------------------------------
    # Cost
    # --------------------------------------------------------

    roundtrip_cost_pct = (
        (fee_pct * 2)
        +
        (slip_pct * 2)
    )

    cost_multiplier = (
        roundtrip_cost_pct / 100
    )

    # --------------------------------------------------------
    # R calculation
    # --------------------------------------------------------

    win_r_values = []

    for z in wins:

        rr = z.get("actual_rr")

        if rr is None:
            continue

        # Percentage cost ko R mein convert.
        net_r = (
            rr
            - (cost_multiplier * rr)
        )

        win_r_values.append(net_r)

    loss_r_values = [
        -(
            1.0
            + cost_multiplier
        )
        for _ in losses
    ]

    total_r_values = (
        win_r_values
        + loss_r_values
    )

    net_pnl_r = sum(
        total_r_values
    )

    gross_win_r = sum(
        win_r_values
    )

    gross_loss_r = abs(
        sum(loss_r_values)
    )

    # --------------------------------------------------------
    # Win rate
    # --------------------------------------------------------

    win_rate = (
        len(wins)
        / len(resolved)
        * 100
        if resolved
        else 0.0
    )

    # --------------------------------------------------------
    # Profit factor
    # --------------------------------------------------------

    if gross_loss_r > 0:

        profit_factor = (
            gross_win_r
            / gross_loss_r
        )

    else:

        profit_factor = (
            float("inf")
            if gross_win_r > 0
            else 1.0
        )

    # --------------------------------------------------------
    # Equity curve / drawdown
    # --------------------------------------------------------

    running_r = 0.0
    peak_r = 0.0
    max_dd = 0.0

    max_consec_wins = 0
    max_consec_losses = 0

    streak_w = 0
    streak_l = 0

    # --------------------------------------------------------
    # IMPORTANT:
    # Zones already appear in creation order.
    # --------------------------------------------------------

    for z in zones:

        status = z["status"]

        if status == "WIN":

            rr = z.get("actual_rr")

            if rr is None:
                continue

            trade_r = (
                rr
                - (cost_multiplier * rr)
            )

            running_r += trade_r

            streak_w += 1
            streak_l = 0

        elif status == "LOSS":

            trade_r = -(
                1.0
                + cost_multiplier
            )

            running_r += trade_r

            streak_l += 1
            streak_w = 0

        else:

            continue

        peak_r = max(
            peak_r,
            running_r,
        )

        drawdown = (
            peak_r
            - running_r
        )

        max_dd = max(
            max_dd,
            drawdown,
        )
        "max_consec_wins":
            max_consec_wins,

        "max_consec_losses":
            max_consec_losses,
    }


# ============================================================
# DAY-BY-DAY BREAKDOWN
# ============================================================

def compute_day_breakdown(
    zones: list[dict],
) -> dict:
    """
    Month ke qualified zones ko day-by-day aggregate karta hai.

    Har day ke liye:
        - zones
        - wins
        - losses
        - net P&L in R
    """

    day_data = defaultdict(
        lambda: {
            "zones": 0,
            "wins": 0,
            "losses": 0,
            "pnl_r": 0.0,
        }
    )

    # Same cost model as compute_month_metrics()
    fee_pct = 0.075
    slip_pct = 0.04

    roundtrip_cost_pct = (
        (fee_pct * 2)
        +
        (slip_pct * 2)
    )

    cost_multiplier = (
        roundtrip_cost_pct / 100
    )

    for z in zones:

        try:
            day_str = str(
                z["created_at"]
            )[:10]

        except Exception:
            continue

        day_data[day_str]["zones"] += 1

        # ----------------------------------------------------
        # WIN
        # ----------------------------------------------------

        if z["status"] == "WIN":

            day_data[day_str]["wins"] += 1

            rr = z.get("actual_rr")

            if rr is not None:

                net_r = (
                    rr
                    - (cost_multiplier * rr)
                )

                day_data[day_str]["pnl_r"] += net_r

        # ----------------------------------------------------
        # LOSS
        # ----------------------------------------------------

        elif z["status"] == "LOSS":

            day_data[day_str]["losses"] += 1

            day_data[day_str]["pnl_r"] += -(
                1.0
                + cost_multiplier
            )

    return dict(
        sorted(
            day_data.items()
        )
    )

        
           
