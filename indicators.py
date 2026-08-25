"""
Basic technical indicators, Pine Script ke built-in ta.* functions ka Python equivalent.
"""

import pandas as pd
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def volume_spike(volume: pd.Series, lookback: int = 20, multiplier: float = 1.5) -> pd.Series:
    avg_volume = volume.rolling(lookback).mean()
    return volume > (avg_volume * multiplier)


def percentile_rank(series: pd.Series, lookback: int) -> pd.Series:
    """
    ta.percentrank(series, lookback) ka Python equivalent — har point ke liye
    batata hai ke wo apni pichli 'lookback' values ke muqable kis percentile pe hai.
    """
    def rank_of_last(window):
        if len(window) < 2:
            return np.nan
        current = window[-1]
        return (window[:-1] < current).sum() / (len(window) - 1) * 100

    return series.rolling(lookback + 1).apply(rank_of_last, raw=True)
