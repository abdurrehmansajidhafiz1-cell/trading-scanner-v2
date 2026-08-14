"""
Signal engine — Intraday Fibonacci & Confluence Strategy Core.
1. OTE Zone Focus (61.8% - 78.6% Fib Retracement)
2. Volatility-based ATR Stop Loss (1.5x ATR buffer below Swing Low)
3. Dual Take-Profit targets (TP1 @ 90% Swing High, TP2 @ 1.618 Fib Extension)
4. 4H/Daily Market Structure & BOS Alignment
5. Minimum Risk-Reward Ratio (1:1.5)
6. BTC Market Regime & Volatility Safeguard
"""

from dataclasses import dataclass, field
import pandas as pd
import numpy as np

import config
from indicators import ema, rsi, atr, volume_spike
from pivot_detection import compute_adaptive_pivot_len, get_locked_swing_structure, _parse_timestamp


@dataclass
class SignalResult:
    coin: str
    timeframe: str
    valid_structure: bool = False
    qualifies: bool = False
    swing_high: float = None
    swing_low: float = None
    swing_high_time: str = None
    swing_low_time: str = None
    pivot_len: int = None
    best_zone_name: str = None
    best_zone_price: float = None
    best_score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    stop_price: float = None
    target_price: float = None
    tp2_price: float = None
    actual_rr: float = None
    rr_ok: bool = False
    trend_ok: bool = False
    reject_reason_code: str = None
    reject_reason_detail: str = None
    structure_created_at: str = None


def is_near(a: float, b: float, tol_pct: float) -> bool:
    if b == 0:
        return False
    return abs(a - b) / b * 100 <= tol_pct


def check_prior_level_flip(df: pd.DataFrame, zone_price: float, pivot_len: int) -> bool:
    lookback_start = max(0, len(df) - 90)
    lookback_end = max(0, len(df) - pivot_len - 1)
    if lookback_end <= lookback_start:
        return False
    window = df.iloc[lookback_start:lookback_end]
    near_high = window["high"].apply(lambda h: is_near(h, zone_price, config.PRIOR_LEVEL_TOLERANCE_PCT)).any()
    near_low = window["low"].apply(lambda l: is_near(l, zone_price, config.PRIOR_LEVEL_TOLERANCE_PCT)).any()
    return bool(near_high or near_low)


def get_trend_up(df_daily: pd.DataFrame) -> bool:
    if len(df_daily) < config.EMA_LENGTH:
        return False
    daily_close = df_daily["close"].iloc[-1]
    daily_ema = ema(df_daily["close"], config.EMA_LENGTH).iloc[-1]
    return daily_close > daily_ema


def check_btc_regime_ok(df_btc: pd.DataFrame | None) -> tuple[bool, str]:
    """
    BTC 1H Market Regime Safeguard — agar BTC sharp drop (1H > 2.0%) kar raha ho
    to altcoin long setups block ho jate hain.
    """
    if df_btc is None or len(df_btc) < 5:
        return True, ""
    last_close = df_btc["close"].iloc[-1]
    prev_close = df_btc["close"].iloc[-4]  # 4 x 15m or 1h window
    drop_pct = (prev_close - last_close) / prev_close * 100
    if drop_pct >= config.BTC_MAX_1H_DROP_PCT:
        return False, f"BTC 1H drop {drop_pct:.2f}% (max {config.BTC_MAX_1H_DROP_PCT}% allowed)"
    return True, ""


def score_zone_intraday(df: pd.DataFrame, zone_price: float, fib_ratio: float,
                         is_htf_trend_up: bool, rsi_val: float, has_vol_spike: bool,
                         pivot_len: int) -> tuple[int, dict]:
    breakdown = {}
    w = config.CONFLUENCE_WEIGHTS

    # 1. OTE Zone Score (61.8% to 78.6% Retracement)
    if config.FIB_OTE_MIN <= fib_ratio <= config.FIB_OTE_MAX:
        breakdown["ote_zone"] = w["ote_zone"]
    elif fib_ratio == 0.500:
        breakdown["ote_zone"] = int(w["ote_zone"] * 0.6)
    else:
        breakdown["ote_zone"] = 0

    # 2. HTF BOS / Market Structure Alignment
    breakdown["htf_bos_alignment"] = w["htf_bos_alignment"] if is_htf_trend_up else 0

    # 3. Volume Expansion
    breakdown["volume_expansion"] = w["volume_expansion"] if has_vol_spike else 0

    # 4. RSI Oversold / Momentum
    breakdown["rsi_divergence_or_os"] = w["rsi_divergence_or_os"] if rsi_val <= config.RSI_OVERSOLD_THRESHOLD else 0

    # 5. Prior Level S/R Flip
    breakdown["prior_level_flip"] = w["prior_level_flip"] if check_prior_level_flip(df, zone_price, pivot_len) else 0

    total = sum(breakdown.values())
    return total, breakdown


def analyze(coin: str, timeframe: str, df: pd.DataFrame, df_daily: pd.DataFrame,
            df_intermediate: pd.DataFrame | None, prev_swing_state: dict | None,
            df_btc: pd.DataFrame | None = None) -> SignalResult:
    """
    Intraday Fibonacci & Confluence Strategy Pipeline.
    """
    result = SignalResult(coin=coin, timeframe=timeframe)
    tf_cfg = config.TF_SETTINGS[timeframe]

    if len(df) < 100:
        result.reject_reason_code = "INSUFFICIENT_DATA"
        result.reject_reason_detail = f"Sirf {len(df)} candles mili, kam se kam 100 chahiye"
        return result

    # --- BTC Safeguard ---
    if config.ENABLE_BTC_REGIME_FILTER and coin != "BTC/USDT":
        btc_ok, btc_detail = check_btc_regime_ok(df_btc)
        if not btc_ok:
            result.reject_reason_code = "BTC_DUMP_IMPACT"
            result.reject_reason_detail = btc_detail
            return result

    # --- Adaptive pivot length + locked swing structure ---
    pivot_len = compute_adaptive_pivot_len(df)
    result.pivot_len = pivot_len
    swing = get_locked_swing_structure(df, pivot_len, prev_swing_state)

    if swing["swing_high"] is None or swing["swing_low"] is None:
        result.reject_reason_code = "NO_STRUCTURE"
        result.reject_reason_detail = "Confirmed pivot high/low nahi mila"
        return result

    result.swing_high = swing["swing_high"]
    result.swing_low = swing["swing_low"]
    result.swing_high_time = swing["swing_high_time"]
    result.swing_low_time = swing["swing_low_time"]

    # --- Up-leg check ---
    swing_low_ts = _parse_timestamp(swing["swing_low_time"])
    swing_high_ts = _parse_timestamp(swing["swing_high_time"])

    is_up_leg = swing_low_ts < swing_high_ts
    if not is_up_leg:
        result.reject_reason_code = "NOT_UP_LEG"
        result.reject_reason_detail = "Swing high pehle bana, low baad mein — down-leg hai"
        return result

    # --- Structure age check ---
    latest_structure_ts = max(swing_high_ts, swing_low_ts)
    structure_bar_idx = df.index[df["timestamp"] == latest_structure_ts]
    if len(structure_bar_idx) > 0:
        age_bars = len(df) - 1 - structure_bar_idx[0]
    else:
        age_bars = len(df) + 999
    if age_bars > tf_cfg["max_structure_age_bars"]:
        result.reject_reason_code = "STRUCTURE_TOO_OLD"
        result.reject_reason_detail = f"Structure {age_bars} bars purana hai, max {tf_cfg['max_structure_age_bars']} allowed"
        return result

    # --- Range check ---
    range_pct = (result.swing_high - result.swing_low) / result.swing_low * 100
    if range_pct < config.MIN_RANGE_PCT:
        result.reject_reason_code = "RANGE_TOO_SMALL"
        result.reject_reason_detail = f"Swing range {range_pct:.2f}%, minimum {config.MIN_RANGE_PCT}% chahiye"
        return result

    result.valid_structure = True
    result.structure_created_at = latest_structure_ts.isoformat()

    # --- Trend filters (4H / Daily BOS Alignment) ---
    daily_trend_up = get_trend_up(df_daily)
    intermediate_trend_up = True
    if tf_cfg["intermediate_tf"] and df_intermediate is not None:
        intermediate_trend_up = get_trend_up(df_intermediate)

    overall_trend_up = daily_trend_up and intermediate_trend_up
    result.trend_ok = overall_trend_up

    if not overall_trend_up:
        result.reject_reason_code = "TREND_FILTER_FAILED"
        result.reject_reason_detail = f"Trend alignment fail (Daily {'up' if daily_trend_up else 'down'})"
        return result

    # --- Fibonacci zones (50%, 61.8% OTE, 78.6% OTE) ---
    diff = result.swing_high - result.swing_low
    fib_levels = {
        "78.6% OTE": (result.swing_high - 0.786 * diff, 0.786),
        "61.8% OTE": (result.swing_high - 0.618 * diff, 0.618),
        "50.0%": (result.swing_high - 0.500 * diff, 0.500),
    }

    # --- Indicators ---
    rsi_val = rsi(df["close"], config.RSI_LENGTH).iloc[-1]
    vol_spikes = volume_spike(df["volume"], config.VOLUME_LOOKBACK, config.VOLUME_SPIKE_MULTIPLIER)
    recent_vol_spike = bool(vol_spikes.iloc[-3:].any())
    atr_val = atr(df, 14).iloc[-1]

    scored = {}
    for name, (price, ratio) in fib_levels.items():
        score, breakdown = score_zone_intraday(df, price, ratio, overall_trend_up, rsi_val, recent_vol_spike, pivot_len)
        scored[name] = (score, price, breakdown)

    best_name = max(scored, key=lambda k: scored[k][0])
    best_score, best_price, best_breakdown = scored[best_name]

    result.best_zone_name = best_name
    result.best_zone_price = best_price
    result.best_score = best_score
    result.score_breakdown = best_breakdown

    if best_score < tf_cfg["min_score"]:
        result.reject_reason_code = "SCORE_TOO_LOW"
        result.reject_reason_detail = f"Confluence score {best_score}/100, minimum {tf_cfg['min_score']} chahiye"
        return result

    # --- Risk-Reward & Volatility ATR Stop Loss ---
    stop_price = result.swing_low - (config.STOP_LOSS_ATR_MULT * atr_val)
    target_price = result.swing_high * config.TP1_SWING_HIGH_FACTOR
    tp2_price = result.swing_low + config.TP2_EXTENSION * diff

    risk = best_price - stop_price
    reward = target_price - best_price

    result.stop_price = stop_price
    result.target_price = target_price
    result.tp2_price = tp2_price

    if risk <= 0:
        result.reject_reason_code = "INVALID_RISK"
        result.reject_reason_detail = "Risk zero ya negative nikla"
        return result

    actual_rr = reward / risk
    result.actual_rr = actual_rr
    result.rr_ok = actual_rr >= config.MIN_RR

    if not result.rr_ok:
        result.reject_reason_code = "RR_TOO_LOW"
        result.reject_reason_detail = f"R:R 1:{actual_rr:.2f}, minimum 1:{config.MIN_RR} chahiye"
        return result

    # --- Sab check pass ---
    result.qualifies = True
    return result
