"""
hist_backtester.py — Month-by-Month + Day-by-Day Historical Backtest Engine.

Purpose:
- Existing live signal_engine.py ko historical replay mein use karna.
- Zero look-ahead bias maintain karna.
- Har candle par sirf us waqt tak available data use karna.
- Qualified zones ko future candles ke against resolve karna.
- Same-candle TP + SL ko conservative LOSS count karna.
- Trade lifetime ko structure-age se independently handle karna.
- Monthly metrics + day-by-day breakdown provide karna.
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

SELF_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

sys.path.insert(0, PARENT_DIR)
sys.path.insert(0, SELF_DIR)


# ============================================================
# LIVE STRATEGY ENGINE
# ============================================================

from signal_engine import analyze


logger = logging.getLogger("hist_backtest")


# ============================================================
# HELPER — TIMESTAMP NORMALIZATION
# ============================================================

def _normalize_timestamp(ts):
    """
    Timestamp ko pandas Timestamp mein normalize karta hai.
    """

    if ts is None:
        return None

    try:
        result = pd.Timestamp(ts)

        # Naive timestamp ko UTC assume karo.
        if result.tzinfo is None:
            result = result.tz_localize("UTC")

        return result

    except Exception:
        return None


# ============================================================
# HELPER — LOOK-AHEAD PROTECTION
# ============================================================

def _truncate_to(
    df: pd.DataFrame | None,
    cutoff_time,
) -> pd.DataFrame | None:
    """
    Sirf woh candles return karta hai jo cutoff_time tak
    available hain.

    IMPORTANT:
    Is function ka purpose look-ahead bias prevent karna hai.
    """

    if df is None:
        return None

    if df.empty:
        return df.copy()

    cutoff = _normalize_timestamp(cutoff_time)

    if cutoff is None:
        return df.copy()

    temp = df.copy()

    try:
        timestamps = pd.to_datetime(
            temp["timestamp"],
            utc=True,
        )

        temp = temp.loc[
            timestamps <= cutoff
        ].copy()

    except Exception:
        temp = temp[
            temp["timestamp"] <= cutoff
        ].copy()

    return temp.reset_index(drop=True)


# ============================================================
# MARKET CLASSIFICATION
# ============================================================

def _classify_month_market(
    df_daily: pd.DataFrame,
) -> str:
    """
    Month ke overall market condition ko classify karta hai.

    BTC / daily data ke basis par:

        > +10%  = STRONG BULL
        > +3%   = BULL
        < -10%  = STRONG BEAR
        < -3%   = BEAR
        else    = SIDEWAYS / CONSOLIDATION
    """

    if df_daily is None or len(df_daily) < 5:
        return "UNKNOWN"

    try:
        start_price = float(
            df_daily["close"].iloc[0]
        )

        end_price = float(
            df_daily["close"].iloc[-1]
        )

    except Exception:
        return "UNKNOWN"

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

    Conservative rule:

        Same candle TP + SL
        => LOSS
    """

    if (
        df_after_entry is None
        or df_after_entry.empty
    ):
        zone["status"] = "PENDING"
        zone["resolved_at"] = None
        zone["touched_at"] = None

        return zone

    try:
        entry_price = float(
            zone["entry_price"]
        )

        stop_price = float(
            zone["stop_price"]
        )

        target_price = float(
            zone["target_price"]
        )

    except Exception:
        zone["status"] = "PENDING"
        zone["resolution_reason"] = (
            "INVALID_EXECUTION_VALUES"
        )

        return zone

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

    # Long setup:
    # Price ko zone price ke around touch karna hoga.
    #
    # Upper tolerance ko allow kar rahe hain.
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

        try:
            candle_low = float(
                candle["low"]
            )

            candle_high = float(
                candle["high"]
            )

        except Exception:
            continue

        candle_time = str(
            candle["timestamp"]
        )

        # ----------------------------------------------------
        # 1. Zone touch
        # ----------------------------------------------------

        if not touched:

            if candle_low <= touch_threshold:

                touched = True
                touched_at = candle_time

                zone["touched_at"] = (
                    touched_at
                )

        # ----------------------------------------------------
        # 2. TP / SL after zone touch
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
            # TP
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
            # SL
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
        # 3. Trade lifetime
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
        future candles
              ↓
        WIN / LOSS / EXPIRED / TIMEOUT / PENDING
    """

    if df_main is None:
        return []

    if df_main.empty:
        return []

    if len(df_main) < 100:
        return []

    # --------------------------------------------------------
    # Default trade lifetime
    # --------------------------------------------------------

    if max_lifetime_bars is None:

        structure_age = int(
            tf_cfg.get(
                "max_structure_age_bars",
                18,
            )
        )

        max_lifetime_bars = max(
            1,
            structure_age * 3,
        )

    # --------------------------------------------------------
    # Normalize main timestamps
    # --------------------------------------------------------

    main_df = df_main.copy()

    try:
        main_df["timestamp"] = pd.to_datetime(
            main_df["timestamp"],
            utc=True,
        )
    except Exception:
        pass

    main_df = (
        main_df
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    month_start_ts = _normalize_timestamp(
        month_start
    )

    month_end_ts = _normalize_timestamp(
        month_end
    )

    if (
        month_start_ts is None
        or month_end_ts is None
    ):
        return []

    # --------------------------------------------------------
    # Current month candles
    # --------------------------------------------------------

    month_candles = main_df[
        (
            main_df["timestamp"]
            >= month_start_ts
        )
        &
        (
            main_df["timestamp"]
            < month_end_ts
        )
    ].copy()

    if month_candles.empty:
        return []

    zones_found = []

    # --------------------------------------------------------
    # Duplicate protection
    #
    # Same setup ko har candle par repeatedly record
    # karne se prevent karta hai.
    # --------------------------------------------------------

    recorded_zone_keys = set()

    last_swing_key = None

    # --------------------------------------------------------
    # Candle-by-candle replay
    # --------------------------------------------------------

    for abs_idx in month_candles.index:

        candle = main_df.iloc[
            abs_idx
        ]

        candle_time = candle[
            "timestamp"
        ]

        # ----------------------------------------------------
        # Historical main timeframe slice
        # ----------------------------------------------------

        df_slice = (
            main_df.iloc[
                :abs_idx + 1
            ]
            .copy()
            .reset_index(drop=True)
        )

        # ----------------------------------------------------
        # Higher timeframe slices
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

        prev_state = None

        if last_swing_key is not None:

            prev_state = {
                "last_recorded_zone_price":
                    last_swing_key,

                "swing_high": None,

                "swing_low": None,

                "swing_high_time": None,

                "swing_low_time": None,
            }

        # ----------------------------------------------------
        # Signal Engine
        # ----------------------------------------------------

        try:

            result = analyze(
                coin=coin,
                timeframe=timeframe,
                df=df_slice,
                df_daily=(
                    df_daily_slice
                    if df_daily_slice is not None
                    else main_df.head(0)
                ),
                df_intermediate=df_inter_slice,
                prev_swing_state=prev_state,
                df_btc=df_btc_slice,
            )

        except Exception as e:

            logger.warning(
                "analyze() failed: "
                f"{coin}[{timeframe}] "
                f"{candle_time}: "
                f"{type(e).__name__}: {e}"
            )

            continue

        # ----------------------------------------------------
        # Only qualified signals
        # ----------------------------------------------------

        if not result.qualifies:
            continue

        # ----------------------------------------------------
        # Required execution values
        # ----------------------------------------------------

        if (
            result.best_zone_price is None
            or result.stop_price is None
            or result.target_price is None
            or result.actual_rr is None
        ):

            logger.warning(
                "Qualified signal missing execution values: "
                f"{coin}[{timeframe}] "
                f"{candle_time}"
            )

            continue

        zone_price = float(
            result.best_zone_price
        )

        # ----------------------------------------------------
        # Duplicate key
        #
        # Structure + zone + timeframe combination ko
        # duplicate hone se prevent karta hai.
        # ----------------------------------------------------

        structure_key = (
            str(result.swing_high_time),
            str(result.swing_low_time),
            round(zone_price, 10),
        )

        if structure_key in recorded_zone_keys:
            continue

        recorded_zone_keys.add(
            structure_key
        )

        last_swing_key = zone_price

        # ----------------------------------------------------
        # Future candles
        #
        # IMPORTANT:
        # Current candle intentionally exclude hai.
        # Isse current candle ke OHLC ko future resolution
        # mein accidentally use nahi karte.
        # ----------------------------------------------------

        df_after = (
            main_df.iloc[
                abs_idx + 1:
            ]
            .copy()
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
                float(result.best_zone_price),

            "stop_price":
                float(result.stop_price),

            "target_price":
                float(result.target_price),

            "tp2_price":
                (
                    float(result.tp2_price)
                    if result.tp2_price is not None
                    else None
                ),

            "swing_low":
                (
                    float(result.swing_low)
                    if result.swing_low is not None
                    else None
                ),

            "swing_high":
                (
                    float(result.swing_high)
                    if result.swing_high is not None
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
        # Resolve trade
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

    Fee:
        0.075% per side

    Slippage:
        0.04% per side

    Round-trip:
        2 × fee + 2 × slippage
        = 0.23%
    """

    wins = [
        z for z in zones
        if z.get("status") == "WIN"
    ]

    losses = [
        z for z in zones
        if z.get("status") == "LOSS"
    ]

    expired = [
        z for z in zones
        if z.get("status") == "EXPIRED"
    ]

    timed_out = [
        z for z in zones
