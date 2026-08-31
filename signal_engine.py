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
    entry_1: float = None  # 61.8% Tier 1 Entry
    entry_2: float = None  # 78.6% Tier 2 Entry
    stop_price: float = None
    tp1_price: float = None # 50% Partial TP
    target_price: float = None # Final TP2 (95% Swing)
    tp2_price: float = None # Extended Fib TP3
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


def check_altcoin_macro_trend(df_daily: pd.DataFrame | None) -> tuple[bool, str]:
    """
    Improvement 1: Altcoin Individual Trend Filter.
    Altcoin ka khud ka Daily EMA 200 check karta hai.
    Agar coin apne EMA 200 se niche hai to long trade skip karo — yeh coin khud BEAR mein hai.
    """
    if not getattr(config, "ENABLE_ALTCOIN_TREND_FILTER", False):
        return True, ""

    ema_len = getattr(config, "ALTCOIN_TREND_EMA_LENGTH", 200)

    if df_daily is None or len(df_daily) < ema_len:
        # Insufficient data — conservative approach: allow trade
        return True, ""

    daily_close = df_daily["close"].iloc[-1]
    daily_ema200 = ema(df_daily["close"], ema_len).iloc[-1]

    if daily_close < daily_ema200:
        return False, (
            f"Altcoin Daily close ({daily_close:.4f}) below EMA {ema_len} ({daily_ema200:.4f})"
            f" — coin khud long-term BEAR mein hai, long skip"
        )

    return True, ""


def check_btc_regime_ok(df_btc: pd.DataFrame | None, df_btc_daily: pd.DataFrame | None = None) -> tuple[bool, str]:
    """
    Enhanced BTC Market Regime Safeguard —
    1. BTC fast drop check (1H drop > config.BTC_MAX_1H_DROP_PCT)
    2. BTC 4H slow-bleed multi-candle drop check (> config.BTC_MAX_4H_DROP_PCT)
    3. BTC 1H RSI dump momentum check (< config.BTC_MIN_RSI_1H)
    4. BTC Daily / 1H EMA 50 trend alignment
    """
    if df_btc is not None and len(df_btc) >= 5:
        last_close = df_btc["close"].iloc[-1]

        # 1-Hour Drop check
        prev_1h = df_btc["close"].iloc[-2] if len(df_btc) >= 2 else last_close
        drop_1h = (prev_1h - last_close) / prev_1h * 100
        max_1h = getattr(config, "BTC_MAX_1H_DROP_PCT", 1.5)
        if drop_1h >= max_1h:
            return False, f"BTC 1H sharp drop {drop_1h:.2f}% (max {max_1h}% allowed)"

        # 4-Hour Cumulative Drop check (Slow bleed dump defense)
        prev_4h = df_btc["close"].iloc[-5] if len(df_btc) >= 5 else last_close
        drop_4h = (prev_4h - last_close) / prev_4h * 100
        max_4h = getattr(config, "BTC_MAX_4H_DROP_PCT", 3.0)
        if drop_4h >= max_4h:
            return False, f"BTC 4H cumulative drop {drop_4h:.2f}% (max {max_4h}% allowed) — slow bleed market dump"

        # 1H RSI Dump Momentum check
        min_rsi = getattr(config, "BTC_MIN_RSI_1H", 40.0)
        if len(df_btc) >= 15:
            btc_rsi = rsi(df_btc["close"], 14).iloc[-1]
            if btc_rsi < min_rsi:
                return False, f"BTC 1H RSI ({btc_rsi:.1f}) < {min_rsi} — aggressive bearish market momentum"

    if getattr(config, "BTC_REQUIRE_EMA_TREND", False):
        if df_btc_daily is not None and len(df_btc_daily) >= config.EMA_LENGTH:
            btc_daily_close = df_btc_daily["close"].iloc[-1]
            btc_daily_ema = ema(df_btc_daily["close"], config.EMA_LENGTH).iloc[-1]
            if btc_daily_close < btc_daily_ema:
                return False, f"BTC Daily close ({btc_daily_close:.1f}) below Daily EMA 50 ({btc_daily_ema:.1f}) — Macro BEAR regime"
        elif df_btc is not None and len(df_btc) >= config.EMA_LENGTH:
            btc_ema = ema(df_btc["close"], config.EMA_LENGTH).iloc[-1]
            last_close = df_btc["close"].iloc[-1]
            if last_close < btc_ema:
                return False, f"BTC close ({last_close:.1f}) below EMA 50 ({btc_ema:.1f}) — Downtrend regime"

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
            df_btc: pd.DataFrame | None = None, df_btc_daily: pd.DataFrame | None = None) -> SignalResult:
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
        btc_ok, btc_detail = check_btc_regime_ok(df_btc, df_btc_daily)
        if not btc_ok:
            result.reject_reason_code = "BTC_DUMP_IMPACT"
            result.reject_reason_detail = btc_detail
            return result

    # --- Improvement 1: Altcoin Individual Trend Filter (Daily EMA 200) ---
    if coin != "BTC/USDT":
        altcoin_ok, altcoin_detail = check_altcoin_macro_trend(df_daily)
        if not altcoin_ok:
            result.reject_reason_code = "ALTCOIN_BEAR_TREND"
            result.reject_reason_detail = altcoin_detail
            return result

    # --- Sunday Shield Filter (Weekly Close & Asian Open Noise Defense) ---
    min_required_score = tf_cfg["min_score"]
    if getattr(config, "ENABLE_SUNDAY_SHIELD", True):
        last_candle_time = df["timestamp"].iloc[-1]
        try:
            ts = pd.Timestamp(last_candle_time)
            # Sunday 18:00 UTC to Monday 04:00 UTC (11:00 PM PKT Sun to 09:00 AM PKT Mon)
            if (ts.dayofweek == 6 and ts.hour >= 18) or (ts.dayofweek == 0 and ts.hour < 4):
                if timeframe == "30m":
                    result.reject_reason_code = "SUNDAY_SHIELD_NOISE"
                    result.reject_reason_detail = "Sunday night / Monday weekly open noise session mein 30m trades blocked hain"
                    return result
                min_required_score = max(min_required_score, 90)
        except Exception:
            pass

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

    # --- Fibonacci zones (61.8% Golden Pocket, 78.6% OTE, 50.0%) ---
    diff = result.swing_high - result.swing_low
    fib_levels = {
        "61.8% Golden Pocket": (result.swing_high - 0.618 * diff, 0.618),
        "78.6% OTE": (result.swing_high - 0.786 * diff, 0.786),
        "50.0%": (result.swing_high - 0.500 * diff, 0.500),
    }

    # --- Indicators ---
    rsi_val = rsi(df["close"], config.RSI_LENGTH).iloc[-1]
    vol_spikes = volume_spike(df["volume"], config.VOLUME_LOOKBACK, config.VOLUME_SPIKE_MULTIPLIER)
    recent_vol_spike = bool(vol_spikes.iloc[-3:].any())
    atr_val = atr(df, 14).iloc[-1]

    # --- Mandatory Hard Filters ---
    if getattr(config, "REQUIRE_RSI_OVERSOLD", False):
        rsi_hard_limit = getattr(config, "RSI_HARD_THRESHOLD", 55)
        if rsi_val > rsi_hard_limit:
            result.reject_reason_code = "RSI_TOO_HIGH"
            result.reject_reason_detail = f"RSI {rsi_val:.1f} > {rsi_hard_limit} — momentum bearish ya overbought, zone skip"
            return result

    if getattr(config, "REQUIRE_VOLUME_SPIKE", False):
        lookback = getattr(config, "VOLUME_SPIKE_LOOKBACK", 3)
        vol_spikes_check = volume_spike(df["volume"], config.VOLUME_LOOKBACK, config.VOLUME_SPIKE_MULTIPLIER)
        has_recent_spike = bool(vol_spikes_check.iloc[-lookback:].any())
        if not has_recent_spike:
            result.reject_reason_code = "NO_VOLUME_SPIKE"
            result.reject_reason_detail = f"Last {lookback} bars mein koi volume spike nahi — low-conviction zone"
            return result

    # --- Fibonacci Candidate Evaluation (Multi-Level Selection) ---
    stop_price = result.swing_low - (config.STOP_LOSS_ATR_MULT * atr_val)
    target_price = result.swing_low + (diff * config.TP1_SWING_HIGH_FACTOR)
    tp2_price = result.swing_low + (config.TP2_EXTENSION * diff)

    result.entry_1 = result.swing_high - 0.618 * diff
    result.entry_2 = result.swing_high - 0.786 * diff
    result.stop_price = stop_price
    result.target_price = target_price
    result.tp1_price = target_price
    result.tp2_price = tp2_price

    valid_candidates = []
    all_evaluated = []

    for name, (price, ratio) in fib_levels.items():
        score, breakdown = score_zone_intraday(df, price, ratio, overall_trend_up, rsi_val, recent_vol_spike, pivot_len)
        risk = price - stop_price
        reward = target_price - price

        if risk <= 0:
            continue

        rr = reward / risk
        candidate = {
            "name": name,
            "price": price,
            "score": score,
            "breakdown": breakdown,
            "rr": rr,
        }
        all_evaluated.append(candidate)

        if score >= min_required_score and rr >= config.MIN_RR:
            valid_candidates.append(candidate)

    if valid_candidates:
        # Best candidate: highest score, tie-break on highest R:R
        best = max(valid_candidates, key=lambda c: (c["score"], c["rr"]))
        result.best_zone_name = best["name"]
        result.best_zone_price = best["price"]
        result.best_score = best["score"]
        result.score_breakdown = best["breakdown"]
        result.actual_rr = best["rr"]
        result.rr_ok = True
        result.qualifies = True
        return result
    else:
        # Best non-qualifying candidate for logging
        if all_evaluated:
            best_attempt = max(all_evaluated, key=lambda c: c["score"])
            result.best_zone_name = best_attempt["name"]
            result.best_zone_price = best_attempt["price"]
            result.best_score = best_attempt["score"]
            result.score_breakdown = best_attempt["breakdown"]
            result.actual_rr = best_attempt["rr"]

            if best_attempt["score"] < tf_cfg["min_score"]:
                result.reject_reason_code = "SCORE_TOO_LOW"
                result.reject_reason_detail = f"Confluence score {best_attempt['score']}/100, minimum {tf_cfg['min_score']} chahiye"
            else:
                result.reject_reason_code = "RR_TOO_LOW"
                result.reject_reason_detail = f"R:R 1:{best_attempt['rr']:.2f}, minimum 1:{config.MIN_RR} chahiye"
        else:
            result.reject_reason_code = "INVALID_RISK"
            result.reject_reason_detail = "Risk zero ya negative nikla"

        return result
