"""
Pivot detection — Pine Script ke ta.pivothigh/ta.pivotlow + adaptive bucket
selection ka Python equivalent. Yeh "locked" state database mein persist
hoti hai (swing_state table), taake har naya run purani values yaad rakhe
jab tak genuinely naya, zyada recent pivot na mil jaye — bilkul Pine Script
ke 'var' variables jaisa behavior.
"""

import pandas as pd
import numpy as np

import config
from indicators import atr, percentile_rank


def compute_adaptive_pivot_len(df: pd.DataFrame) -> int:
    """
    Coin ki apni pichli 200 candles ki ATR history se percentile nikal kar
    4 buckets (3/6/9/12) mein se best-fit choose karta hai.
    """
    atr_series = atr(df, 14)
    atr_pct = atr_series / df["close"] * 100
    percentile = percentile_rank(atr_pct, config.PERCENTILE_LOOKBACK)

    latest_percentile = percentile.iloc[-1]
    if pd.isna(latest_percentile):
        return config.PIVOT_BUCKETS[1]  # default middle bucket agar enough history na ho

    if latest_percentile < 25:
        return config.PIVOT_BUCKETS[0]
    elif latest_percentile < 50:
        return config.PIVOT_BUCKETS[1]
    elif latest_percentile < 75:
        return config.PIVOT_BUCKETS[2]
    else:
        return config.PIVOT_BUCKETS[3]


def find_confirmed_pivots(df: pd.DataFrame, pivot_len: int):
    """
    Poori dataframe mein se saare CONFIRMED pivot highs aur lows dhoondta hai
    (jaise Pine Script ka ta.pivothigh/pivotlow). Dataframe mein sirf CLOSED
    candles honi chahiye (live/incomplete candle already drop ki hui ho).

    Returns: (pivot_highs, pivot_lows) — dono list of (index, price, pd.Timestamp)
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    pivot_highs = []
    pivot_lows = []

    for i in range(pivot_len, n - pivot_len):
        window_high = highs[i - pivot_len: i + pivot_len + 1]
        if highs[i] == window_high.max():
            pivot_highs.append((i, highs[i], df["timestamp"].iloc[i]))

        window_low = lows[i - pivot_len: i + pivot_len + 1]
        if lows[i] == window_low.min():
            pivot_lows.append((i, lows[i], df["timestamp"].iloc[i]))

    return pivot_highs, pivot_lows


def get_locked_swing_structure(df: pd.DataFrame, pivot_len: int, prev_state: dict | None):
    """
    Naye confirmed pivots dhoondta hai aur unhe purani (database se aayi) state
    ke sath compare karta hai — sirf tab update karta hai jab genuinely naya,
    zyada recent pivot mile. Warna purani locked values wapas kar deta hai.

    Returns dict: swing_high, swing_high_time, swing_low, swing_low_time
    (times hamesha ISO-format strings hain, consistent, taake baad mein
    signal_engine mein reliably parse/compare ho sakein)
    """
    pivot_highs, pivot_lows = find_confirmed_pivots(df, pivot_len)

    prev_high_time = _parse_timestamp(prev_state["swing_high_time"]) if prev_state and prev_state.get("swing_high_time") else None
    prev_low_time = _parse_timestamp(prev_state["swing_low_time"]) if prev_state and prev_state.get("swing_low_time") else None

    result = {
        "swing_high": prev_state["swing_high"] if prev_state else None,
        "swing_high_time": prev_high_time.isoformat() if prev_high_time is not None else None,
        "swing_low": prev_state["swing_low"] if prev_state else None,
        "swing_low_time": prev_low_time.isoformat() if prev_low_time is not None else None,
    }

    if pivot_highs:
        latest_high = pivot_highs[-1]  # sabse recent confirmed pivot high
        latest_high_ts = latest_high[2]  # already ek proper pd.Timestamp hai
        if prev_high_time is None or latest_high_ts > prev_high_time:
            result["swing_high"] = float(latest_high[1])
            result["swing_high_time"] = latest_high_ts.isoformat()

    if pivot_lows:
        latest_low = pivot_lows[-1]  # sabse recent confirmed pivot low
        latest_low_ts = latest_low[2]
        if prev_low_time is None or latest_low_ts > prev_low_time:
            result["swing_low"] = float(latest_low[1])
            result["swing_low_time"] = latest_low_ts.isoformat()

    return result


def _parse_timestamp(value) -> pd.Timestamp | None:
    """
    Kisi bhi format mein aayi hui timestamp string (purani buggy format ho ya
    nayi) ko ek consistent, tz-aware pd.Timestamp mein convert karta hai —
    taake purani database rows ke sath bhi yeh function safely kaam kare.
    """
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts
