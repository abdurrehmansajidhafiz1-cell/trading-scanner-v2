"""
hist_backtester.py — Month-by-Month + Day-by-Day Historical Backtest Engine.

Purpose:
- Existing live signal_engine.py ko use karke historical replay karna.
- Zero look-ahead bias maintain karna.
- Har candle par sirf us waqt tak available data use karna.
- Qualified zones ko future candles ke against resolve karna.
- Same-candle TP + SL ko conservative LOSS count karna.
- Trade lifetime ko structure-age se independently handle karna.
- Monthly aur day-by-day performance metrics generate karna.
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

    Conservative assumption:

        Same candle TP + SL = LOSS
    """

    if (
        df_after_entry is None
        or df_after_entry.empty
    ):
        zone["status"] = "PENDING"
        zone["resolved_at"] = None
        zone["touched_at"] = None
        zone["resolution_reason"] = (
            "NO_FUTURE_DATA"
        )

        return zone

    entry_price = float(
        zone["entry_price"]
    )

    stop_price = float(
        zone["stop_price"]
    )

    target_price = float(
        zone["target_price"]
    )

    touched = False

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
        # Zone touch
        # ----------------------------------------------------

        if not touched:

            if candle_low <= touch_threshold:

                touched = True

                zone["touched_at"] = (
                    candle_time
                )

        # ----------------------------------------------------
        # TP / SL after zone touch
        # ----------------------------------------------------

        if touched:

            hit_target = (
                candle_high
                >= target_price
            )

            hit_stop = (
                candle_low
                <= stop_price
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

                    zone["resolved_at"] = (
                        candle_time
                    )

                    return zone

                else:

                    zone["status"] = "WIN"

                    zone["resolution_reason"] = (
                        "SAME_CANDLE_TP_SL_TARGET_FIRST"
                    )

                    zone["resolved_at"] = (
                        candle_time
                    )

                    return zone

            # ------------------------------------------------
            # TP only
            # ------------------------------------------------

            if hit_target:

                zone["status"] = "WIN"

                zone["resolution_reason"] = (
                    "TARGET_HIT"
                )

                zone["resolved_at"] = (
                    candle_time
                )

                return zone

            # ------------------------------------------------
            # SL only
            # ------------------------------------------------

            if hit_stop:

                zone["status"] = "LOSS"

                zone["resolution_reason"] = (
                    "STOP_HIT"
                )

                zone["resolved_at"] = (
                    candle_time
                )

                return zone

        # ----------------------------------------------------
        # Maximum trade lifetime
        # ----------------------------------------------------

        if (
            idx + 1
            >= max_lifetime_bars
        ):

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

            zone["resolved_at"] = (
                candle_time
            )

            return zone

    # --------------------------------------------------------
    # Future data ended
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

    analyze() ko sirf current candle tak ka data diya jata hai.
    """

    if df_main is None:
        return []

    if len(df_main) < 100:
        return []

    # --------------------------------------------------------
    # Default trade lifetime
    # --------------------------------------------------------

    if max_lifetime_bars is None:

        max_lifetime_bars = (
            int(
                tf_cfg.get(
                    "max_structure_age_bars",
                    18,
                )
            )
            * 3
        )

    max_lifetime_bars = max(
        1,
        int(max_lifetime_bars),
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

    # --------------------------------------------------------
    # Duplicate zone protection
    # --------------------------------------------------------

    last_recorded_zone_price = None

    # --------------------------------------------------------
    # Candle-by-candle replay
    # --------------------------------------------------------

    for _, candle in month_candles.iterrows():

        candle_time = candle["timestamp"]

        matching_indices = df_main.index[
            df_main["timestamp"] == candle_time
        ].tolist()

        if not matching_indices:
            continue

        abs_idx = matching_indices[0]

        # ----------------------------------------------------
        # Historical main timeframe slice
        # ----------------------------------------------------

        df_slice = (
            df_main.iloc[
                : abs_idx + 1
            ]
            .reset_index(drop=True)
        )

        # ----------------------------------------------------
        # Historical auxiliary slices
        # ----------------------------------------------------

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

        if (
            last_recorded_zone_price
            is not None
        ):

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
        # Only qualified signals
        # ----------------------------------------------------

        if not result.qualifies:
            continue

        zone_price = (
            result.best_zone_price
        )

        if zone_price is None:
            continue

        zone_price = float(
            zone_price
        )

        # ----------------------------------------------------
        # Duplicate zone protection
        # ----------------------------------------------------

        if (
            last_recorded_zone_price
            is not None
            and zone_price
            == last_recorded_zone_price
        ):
            continue

        # ----------------------------------------------------
        # Required execution values
        # ----------------------------------------------------

        if (
            result.stop_price is None
            or result.target_price is None
            or result.actual_rr is None
        ):

            logger.warning(
                "Qualified signal missing "
                "execution values: "
                f"{coin}[{timeframe}] "
                f"{candle_time}"
            )

            continue

        # Update duplicate tracker only after
        # complete valid execution data.
        last_recorded_zone_price = (
            zone_price
        )

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
            "coin":
                coin,

            "timeframe":
                timeframe,

            "created_at":
                str(candle_time),

            "entry_price":
                float(
                    result.best_zone_price
                ),

            "stop_price":
                float(
                    result.stop_price
                ),

            "target_price":
                float(
                    result.target_price
                ),

            "tp2_price":
                (
                    float(result.tp2_price)
                    if result.tp2_price
                    is not None
                    else None
                ),

            "swing_low":
                (
                    float(result.swing_low)
                    if result.swing_low
                    is not None
                    else None
                ),

            "swing_high":
                (
                    float(result.swing_high)
                    if result.swing_high
                    is not None
                    else None
                ),

            "swing_low_time":
                result.swing_low_time,

            "swing_high_time":
                result.swing_high_time,

            "structure_created_at":
                result.structure_created_at,

            "score":
                int(result.best_score),

            "actual_rr":
                float(result.actual_rr),

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
        # Resolve zone against future candles
        # ----------------------------------------------------

        zone = _resolve_zone(
            zone=zone,

            df_after_entry=df_after,

            tf_cfg=tf_cfg,

            max_lifetime_bars=(
                max_lifetime_bars
            ),

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
    Month ke zones se complete performance metrics calculate karta hai.

    Round-trip cost:

        2 × fee
        +
        2 × slippage
    """

    wins = [
        z for z in zones
        if z.get("status") == "WIN"
    ]

    losses = [
        z for z in zones
        if z.get("status") == "LOSS"
    ]

    resolved = (
        wins
        + losses
    )

    # --------------------------------------------------------
    # Cost model
    # --------------------------------------------------------

    roundtrip_cost_pct = (
        (float(fee_pct) * 2)
        +
        (float(slip_pct) * 2)
    )

    cost_multiplier = (
        roundtrip_cost_pct / 100.0
    )

    # --------------------------------------------------------
    # WIN R values
    # --------------------------------------------------------

    win_r_values = []

    for z in wins:

        rr = z.get(
            "actual_rr"
        )

        if rr is None:
            continue

        rr = float(rr)

        net_r = (
            rr
            - (
                cost_multiplier
                * rr
            )
        )

        win_r_values.append(
            net_r
        )

    # --------------------------------------------------------
    # LOSS R values
    # --------------------------------------------------------

    loss_r_values = [
        -(
            1.0
            + cost_multiplier
        )
        for _ in losses
    ]

    # --------------------------------------------------------
    # Total
    # --------------------------------------------------------

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
        * 100.0
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
    # Drawdown + streaks
    # --------------------------------------------------------

    running_r = 0.0
    peak_r = 0.0
    max_dd = 0.0

    max_consec_wins = 0
    max_consec_losses = 0

    streak_w = 0
    streak_l = 0

    for z in zones:

        status = z.get(
            "status"
        )

        # ----------------------------------------------------
        # WIN
        # ----------------------------------------------------
