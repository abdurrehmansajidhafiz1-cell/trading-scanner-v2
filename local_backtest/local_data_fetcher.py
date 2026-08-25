"""
local_data_fetcher.py — Paginated historical OHLCV data fetcher for the
local 1-year backtest. Same pagination approach as hist_data_fetcher.py
(exchanges only return 500-1000 candles per call, so we page through).
"""

import time
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger("local_backtest")


def fetch_full_history(exchange, symbol: str, timeframe: str,
                        since_dt: datetime, until_dt: datetime,
                        candles_per_page: int = 500) -> pd.DataFrame:
    """
    Paginated fetch: since_dt se until_dt tak poora OHLCV data fetch karta hai.
    """
    since_ms = int(since_dt.timestamp() * 1000)
    until_ms = int(until_dt.timestamp() * 1000)

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

        # We've reached (or passed) the requested end of the window -- done.
        if last_ts >= until_ms:
            break

        # IMPORTANT: do NOT stop just because this page returned fewer than
        # candles_per_page rows. Some exchanges (KuCoin especially) return a
        # short/partial page mid-history even though far more history is
        # still available further forward -- stopping here would silently
        # truncate the fetch to just the first page or two. We only stop for
        # a genuinely real reason: either we've reached `until_ms` (above),
        # or the exchange stops making forward progress at all (below).
        if last_ts <= current_since:
            logger.warning(f"  [{symbol}][{timeframe}] pagination stalled (no forward progress) @ {current_since}. Stopping.")
            break

        current_since = last_ts + 1
        time.sleep(0.3)  # rate limit courtesy

    if not all_candles:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)

    df = df[(df["timestamp"] >= pd.Timestamp(since_dt)) & (df["timestamp"] < pd.Timestamp(until_dt))]
    df = df.reset_index(drop=True)

    # Sanity check: warn loudly if what we actually got covers noticeably
    # less time than what was requested (a sign pagination stopped early,
    # or the exchange simply doesn't have history that far back for this
    # symbol/timeframe). This would previously fail silently.
    if len(df) > 0:
        actual_span_days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds() / 86400
        requested_span_days = (until_dt - since_dt).total_seconds() / 86400
        if requested_span_days > 0 and actual_span_days < requested_span_days * 0.8:
            logger.warning(
                f"  [{symbol}][{timeframe}] COVERAGE GAP: only {actual_span_days:.0f} of "
                f"{requested_span_days:.0f} requested days were actually returned "
                f"(earliest candle: {df['timestamp'].iloc[0]}). This coin/timeframe's "
                f"backtest results will be based on less history than requested."
            )

    logger.info(f"  [{symbol}][{timeframe}] {len(df)} candles fetched "
                f"({since_dt.strftime('%Y-%m-%d')} -> {until_dt.strftime('%Y-%m-%d')})")
    return df


def get_working_exchange_local():
    """
    Local backtest ke liye working exchange dhundhta hai (local_config.py
    ki EXCHANGE_PRIORITY list use karta hai).
    """
    import ccxt
    import local_config as lc

    errors = []
    for exchange_id in lc.EXCHANGE_PRIORITY:
        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({"enableRateLimit": True})
            exchange.fetch_time()
            logger.info(f"Local backtest exchange: '{exchange_id}' accessible.")
            return exchange, exchange_id
        except Exception as e:
            errors.append(f"{exchange_id}: {e}")
            continue

    raise RuntimeError(
        "Koi bhi exchange local backtest ke liye accessible nahi.\n"
        "Apna internet connection check karein, ya kisi VPN/proxy ki wajah se "
        "exchange block ho rahi ho to woh disable karein.\n" + "\n".join(errors)
    )