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
# TIMESTAMP HELPERS
# ============================================================

def _normalize_timestamp(ts):
    """Timestamp ko UTC-aware pandas Timestamp mein convert karta hai."""

    if ts is None:
        return None

    try:
        result = pd.Timestamp(ts)

        if result.tzinfo is None:
            result = result.tz_localize("UTC")
        else:
            result = result.tz_convert("UTC")

        return result

    except Exception:
        return None


def _ensure_timestamp_column(df):
    """DataFrame ki timestamp column ko UTC-aware banata hai."""

    if df is None:
        return None

    if df.empty:
        return df.copy()

    result = df.copy()

    if "timestamp" not in result.columns:
        return result

    try:
        result["timestamp"] = pd.to_datetime(
            result["timestamp"],
            utc=True,
        )
    except Exception:
        pass

    return result


# ============================================================
# LOOK-AHEAD PROTECTION
# ============================================================

def _truncate_to(
    df: pd.DataFrame | None,
    cutoff_time,
) -> pd.DataFrame | None:
    """
    Sirf woh candles return karta hai jo cutoff_time tak
    available hain.

    Look-ahead bias prevention ke liye use hota hai.
    """

    if df is None:
        return None

    if df.empty:
        return df.copy()

    cutoff = _normalize_timestamp(cutoff_time)

    if cutoff is None:
        return df.copy()

    temp = _ensure_timestamp_column(df)

    try:
        temp = temp[
            temp["timestamp"] <= cutoff
        ].copy()
    except Exception:
        return df.copy()

    return temp.reset_index(drop=True)


# ============================================================
# MARKET CLASSIFICATION
# ============================================================

def _classify_month_market(
    df_daily: pd.DataFrame,
) -> str:
    """
    Daily price movement ke basis par month classify karta hai.

        > +10%  = STRONG BULL
        > +3%   = BULL
        < -10%  = STRONG BEAR
        < -3%   = BEAR
        else    = SIDEWAYS / CONSOLIDATION
    """

    if df_daily is None or df_daily.empty:
        return "UNKNOWN"

    if "close" not in df_daily.columns:
        return "UNKNOWN"

    if len(df_daily) < 2:
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
        * 100.0
    )

    if change_pct > 10.0:
        return "STRONG BULL"

    if change_pct > 3.0:
        return "BULL"

    if change_pct < -10.0:
        return "STRONG BEAR"

    if change_pct < -3.0:
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
    Qualified zone ko future candles ke against resolve karta hai.

    Possible statuses:

        WIN
        LOSS
        EXPIRED
        TIMEOUT
        PENDING

    Conservative rule:

        Same candle mein TP aur SL dono hit hon
        to LOSS count hoga.
    """

    if (
        df_after_entry is None
        or df_after_entry.empty
    ):
        zone["status"] = "PENDING"
        zone["resolved_at"] = None
        zone["resolution_reason"] = (
            "NO_FUTURE_DATA"
        )
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
        zone["resolved_at"] = None
        zone["resolution_reason"] = (
            "INVALID_EXECUTION_VALUES"
        )
        return zone

    try:
        max_lifetime_bars = max(
            1,
            int(max_lifetime_bars),
        )
    except Exception:
        max_lifetime_bars = 1

    future_df = _ensure_timestamp_column(
        df_after_entry
    )

    # --------------------------------------------------------
    # Zone tolerance
    # --------------------------------------------------------

    try:
        tolerance_pct = float(
            tf_cfg.get(
                "zone_tolerance_pct",
                0.0,
            )
        )
    except Exception:
        tolerance_pct = 0.0

    touch_upper = (
        entry_price
        * (
            1.0
            + tolerance_pct / 100.0
        )
    )

    touch_lower = (
        entry_price
        * (
            1.0
            - tolerance_pct / 100.0
        )
    )

    touched = False

    # --------------------------------------------------------
    # Future candle replay
    # --------------------------------------------------------

    for idx, (_, candle) in enumerate(
        future_df.iterrows()
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
        # Zone touch
        # ----------------------------------------------------

        if not touched:

            zone_touched = (
                candle_low <= touch_upper
                and
                candle_high >= touch_lower
            )

            if zone_touched:

                touched = True

                zone["touched_at"] = (
                    candle_time
                )

        # ----------------------------------------------------
        # TP / SL after entry
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
            # Target hit
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
            # Stop hit
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
        # Lifetime
        # ----------------------------------------------------

        if idx + 1 >= max_lifetime_bars:

            if touched:

                zone["status"] = "TIMEOUT"

                zone["resolution_reason"] = (
                    "TRADE_LIFETIME_EXCEEDED"
                )

            else:

                zone["status"] = "EXPIRED"

                zone["resolution_reason"] = (
                    "ZONE_NOT_TOUCHED"
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
    Ek coin + ek timeframe + ek month ka
    candle-by-candle historical replay.

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
    # Normalize main dataframe
    # --------------------------------------------------------

    main_df = _ensure_timestamp_column(
        df_main
    )

    if "timestamp" not in main_df.columns:
        logger.error(
            "%s[%s]: timestamp column missing.",
            coin,
            timeframe,
        )
        return []

    main_df = (
        main_df
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    # --------------------------------------------------------
    # Default trade lifetime
    # --------------------------------------------------------

    if max_lifetime_bars is None:

        try:
            structure_age = int(
                tf_cfg.get(
                    "max_structure_age_bars",
                    18,
                )
            )
        except Exception:
            structure_age = 18

        max_lifetime_bars = max(
            1,
            structure_age * 3,
        )

    # --------------------------------------------------------
    # Month boundaries
    # --------------------------------------------------------

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

    month_mask = (
        (main_df["timestamp"] >= month_start_ts)
        &
        (main_df["timestamp"] < month_end_ts)
    )

    month_candles = main_df[
        month_mask
    ]

    if month_candles.empty:
        return []

    zones_found = []

    # --------------------------------------------------------
    # Duplicate protection
    # --------------------------------------------------------

    recorded_zone_keys = set()

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

        # Signal engine accepts previous swing state,
        # but historical replay does not inject future values.
        #
        # We intentionally keep this None unless a valid
        # state is available from current historical context.

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
                "%s[%s] %s: %s: %s",
                coin,
                timeframe,
                candle_time,
                type(e).__name__,
                e,
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
                "%s[%s] %s",
                coin,
                timeframe,
                candle_time,
            )

            continue

        # ----------------------------------------------------
        # Numeric validation
        # ----------------------------------------------------

        try:

            zone_price = float(
                result.best_zone_price
            )

            stop_price = float(
                result.stop_price
            )

            target_price = float(
                result.target_price
            )

            actual_rr = float(
                result.actual_rr
            )

        except Exception:

            logger.warning(
                "Invalid execution values: "
                "%s[%s] %s",
                coin,
                timeframe,
                candle_time,
            )

            continue

        # ----------------------------------------------------
        # Duplicate setup key
        # ----------------------------------------------------

        structure_key = (
            str(result.swing_high_time),
            str(result.swing_low_time),
            result.best_zone_name,
            round(zone_price, 10),
        )

        if structure_key in recorded_zone_keys:
            continue

        recorded_zone_keys.add(
            structure_key
        )

        # ----------------------------------------------------
        # Future candles
        #
        # Current candle intentionally excluded.
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
            "coin": coin,

            "timeframe": timeframe,

            "created_at": str(
                candle_time
            ),

            "entry_price": zone_price,

            "stop_price": stop_price,

            "target_price": target_price,

            "tp2_price": (
                float(result.tp2_price)
                if result.tp2_price is not None
                else None
            ),

            "swing_low": (
                float(result.swing_low)
                if result.swing_low is not None
                else None
            ),

            "swing_high": (
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

            "score": int(
                result.best_score
            ),

            "actual_rr": actual_rr,

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
            same_candle_tp_sl_is_loss=same_candle_tp_sl_is_loss,
        )

        zones_found.append(zone)

    return zones_found


# ============================================================
# TRADE COST HELPER (fees + slippage, in R terms)
# ============================================================

def _trade_cost_r(
    zone: dict,
    fee_pct: float,
    slippage_pct: float,
) -> float:
    """
    Ek trade ka round-trip fee + slippage cost
    R-multiple mein convert karta hai.

    Risk distance (entry vs stop) ke against
    cost % ko normalize kiya jata hai.
    """

    try:
        entry = float(zone["entry_price"])
        stop = float(zone["stop_price"])
    except Exception:
        return 0.0

    if entry <= 0:
        return 0.0

    risk_pct = abs(entry - stop) / entry * 100.0

    if risk_pct <= 0:
        return 0.0

    # Round-trip = entry fee + exit fee
    total_cost_pct = (
        (2 * fee_pct)
        + slippage_pct
    )

    return total_cost_pct / risk_pct


# ============================================================
# ZONE SUMMARY (shared by month + day breakdown)
# ============================================================

def _summarize_zones(
    zones: list[dict],
    fee_pct: float = 0.0,
    slippage_pct: float = 0.0,
) -> dict:
    """
    Zones ki list se aggregate metrics banata hai.

    NOTE:
    Ye reconstruction hai — original compute_month_metrics /
    compute_day_breakdown ka source code available nahi tha.
    Fee/slippage handling ya R-multiple formula agar aapki
    asal strategy se mismatch kare to yahan adjust karna hoga.
    """

    total_trades = 0
    wins = 0
    losses = 0
    timeouts = 0
    expired = 0
    pending = 0

    gross_pnl_r = 0.0
    total_cost_r = 0.0

    win_r_values = []

    for zone in zones:

        status = zone.get("status")

        if status == "WIN":

            total_trades += 1
            wins += 1

            rr = zone.get("actual_rr")

            try:
                rr = float(rr)
            except Exception:
                rr = 0.0

            gross_pnl_r += rr
            win_r_values.append(rr)

            total_cost_r += _trade_cost_r(
                zone,
                fee_pct,
                slippage_pct,
            )

        elif status == "LOSS":

            total_trades += 1
            losses += 1

            gross_pnl_r += -1.0

            total_cost_r += _trade_cost_r(
                zone,
                fee_pct,
                slippage_pct,
            )

        elif status == "TIMEOUT":
            timeouts += 1

        elif status == "EXPIRED":
            expired += 1

        elif status == "PENDING":
            pending += 1

    net_pnl_r = gross_pnl_r - total_cost_r

    win_rate_pct = (
        (wins / total_trades * 100.0)
        if total_trades > 0
        else 0.0
    )

    avg_win_r = (
        (sum(win_r_values) / len(win_r_values))
        if win_r_values
        else 0.0
    )

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "expired": expired,
        "pending": pending,
        "gross_pnl_r": round(gross_pnl_r, 4),
        "total_cost_r": round(total_cost_r, 4),
        "net_pnl_r": round(net_pnl_r, 4),
        "win_rate_pct": round(win_rate_pct, 2),
        "avg_win_r": round(avg_win_r, 4),
    }


# ============================================================
# MONTH METRICS
# ============================================================

def compute_month_metrics(
    zones: list[dict],
    fee_pct: float = 0.0,
    slippage_pct: float = 0.0,
) -> dict:
    """
    Ek month ke sab zones se aggregate metrics banata hai.
    """

    return _summarize_zones(
        zones,
        fee_pct=fee_pct,
        slippage_pct=slippage_pct,
    )


# ============================================================
# DAY-BY-DAY BREAKDOWN
# ============================================================

def compute_day_breakdown(
    zones: list[dict],
) -> dict:
    """
    Zones ko "created_at" date ke hisaab se group karke
    har din ke metrics return karta hai.

    NOTE: Fees/slippage yahan include nahi kiye gaye
    (caller sirf zones pass karta hai, fee args nahi deta).
    """

    daily_zones = defaultdict(list)

    for zone in zones:

        created_at = zone.get("created_at")

        if not created_at:
            continue

        day_key = str(created_at)[:10]

        daily_zones[day_key].append(zone)

    breakdown = {}

    for day_key in sorted(daily_zones.keys()):

        breakdown[day_key] = _summarize_zones(
            daily_zones[day_key]
        )

    return breakdown
