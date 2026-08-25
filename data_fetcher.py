"""
Data fetcher — ccxt se OHLCV candles fetch karta hai. Zaroori: exchange
hamesha last candle current/incomplete deta hai — hum usay hamesha drop
karte hain taake sirf CLOSED candles pe calculation ho (Pine Script mein
bhi live candle kabhi pivot nahi ban sakti, isi tarah).
"""

import pandas as pd


def fetch_ohlcv(exchange, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    # Last candle hamesha abhi bhi ban rahi hoti hai (incomplete) — drop karo
    df = df.iloc[:-1].reset_index(drop=True)
    return df
