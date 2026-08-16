"""
hist_data_fetcher.py — Paginated historical OHLCV data fetcher.
2021 se ab tak ka poora data fetch karta hai — multiple API calls karke
(kyunke exchanges single call mein sirf 500-1000 candles dete hain).
Existing data_fetcher.py se bilkul independent hai.
"""

import time
import logging
import pandas as pd
from datetime import datetime, timezone

logger = logging.getLogger("hist_backtest")


def fetch_full_history(exchange, symbol: str, timeframe: str,
                       since_dt: datetime, until_dt: datetime,
                       candles_per_page: int = 500) -> pd.DataFrame:
    """
    Paginated fetch: since_dt se until_dt tak poora OHLCV data fetch karta hai.
    Multiple API calls karta hai jab tak sari candles na aa jayen.
    """
    since_ms = int(since_dt.timestamp() * 1000)
    until_ms  = int(until_dt.timestamp() * 1000)

    all_candles = []
    current_since = since_ms

    while True:
        try:
            raw = exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                since=current_since,
                limit=candles_per_page,
            )
        except Exception as e:
            logger.warning(f"  [{symbol}][{timeframe}] fetch error @ {current_since}: {e}. Retry 5s...")
            time.sleep(5)
            try:
                raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=current_since, limit=candles_per_page)
            except Exception as e2:
                logger.error(f"  [{symbol}][{timeframe}] double-fail: {e2}. Stopping pagination.")
                break

        if not raw:
            break

        all_candles.extend(raw)

        last_ts = raw[-1][0]
        if last_ts >= until_ms or len(raw) < candles_per_page:
            break

        current_since = last_ts + 1
        time.sleep(0.3)   # Rate limit courtesy

    if not all_candles:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)

    # Sirf requested window keep karo
    df = df[(df["timestamp"] >= pd.Timestamp(since_dt)) & (df["timestamp"] < pd.Timestamp(until_dt))]
    df = df.reset_index(drop=True)

    logger.info(f"  [{symbol}][{timeframe}] {len(df)} candles fetched "
                f"({since_dt.strftime('%Y-%m')} → {until_dt.strftime('%Y-%m')})")
    return df


def get_working_exchange_hist():
    """
    Historical backtest ke liye working exchange dhundhta hai.
    hist_config.py ki EXCHANGE_PRIORITY list use karta hai.
    """
    import ccxt
    import hist_config as hc

    errors = []
    for exchange_id in hc.EXCHANGE_PRIORITY:
        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({"enableRateLimit": True})
            exchange.fetch_time()
            logger.info(f"Historical fetch exchange: '{exchange_id}' accessible.")
            return exchange, exchange_id
        except Exception as e:
            errors.append(f"{exchange_id}: {e}")
            continue

    raise RuntimeError(
        f"Koi bhi exchange historical data ke liye accessible nahi.\n" + "\n".join(errors)
    )
