"""
run_historical_backtest.py — Main Entry Point for Historical Backtest.

Flow:
1. 2021-01 se last completed month tak month windows generate karo
2. Har coin/timeframe ka complete historical OHLCV data fetch karo
3. Data memory mein cache karo
4. Har month ko candle-by-candle replay karo
5. signal_engine.analyze() ko sirf us waqt tak available data do
6. Qualified zones ko future candles ke against resolve karo
7. Monthly + day-by-day metrics generate karo
8. Har completed year ki annual email bhejo
9. End mein complete overall summary email bhejo

IMPORTANT:
- Current/incomplete month ko backtest nahi kiya jata.
- Historical backtest existing live database se independent hai.
- Strategy logic signal_engine.py se reuse hota hai.
"""

import sys
import os
import logging
from datetime import datetime, timezone
from calendar import monthrange

import pandas as pd


# ============================================================
# PATH SETUP
# ============================================================

SELF_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PARENT_DIR = os.path.dirname(
    SELF_DIR
)

# Parent directory = trading_scanner/
sys.path.insert(0, PARENT_DIR)

# Current directory = historical_backtest/
sys.path.insert(0, SELF_DIR)


# ============================================================
# IMPORTS
# ============================================================

import hist_config as hc

# Live strategy config — TF_SETTINGS (zone_tolerance_pct,
# max_structure_age_bars, etc.) yahan se aati hain, taake
# historical backtest live strategy settings se match kare.
# NOTE: Agar aapki live config file "config.py" ke ilawa kisi
# aur naam se hai, ye import line usi naam se update karni hogi.
import config as live_cfg

from hist_data_fetcher import (
    fetch_full_history,
    get_working_exchange_hist,
)

from hist_backtester import (
    backtest_single_coin_month,
    compute_month_metrics,
    compute_day_breakdown,
    _classify_month_market,
)

from hist_reporter import (
    send_year_report,
    send_overall_summary_report,
)


# ============================================================
# LOGGING
# ============================================================

LOG_FILE = os.path.join(
    SELF_DIR,
    "hist_backtest.log",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            LOG_FILE,
            encoding="utf-8",
        ),
    ],
)

logger = logging.getLogger(
    "hist_backtest"
)


# ============================================================
# DATE HELPERS
# ============================================================

def get_last_completed_month():
    """
    Current month se pehle wala month return karta hai.

    Example:
        August 2026 chal raha ho
        -> July 2026 last completed month hoga.

    Return:
        (year, month)
    """

    now = datetime.now(timezone.utc)

    if now.month == 1:
        return now.year - 1, 12

    return now.year, now.month - 1


def generate_month_windows() -> list[tuple]:
    """
    HIST_START_YEAR/HIST_START_MONTH se
    last completed month tak month windows generate karta hai.

    IMPORTANT:
    Current incomplete month intentionally exclude hota hai.
    """

    last_year, last_month = (
        get_last_completed_month()
    )

    year = hc.HIST_START_YEAR
    month = hc.HIST_START_MONTH

    windows = []

    while (year, month) <= (
        last_year,
        last_month,
    ):

        start = datetime(
            year,
            month,
            1,
            0,
            0,
            0,
            tzinfo=timezone.utc,
        )

        # Next month ka first moment
        # exclusive end ke liye use hoga.
        if month == 12:
            next_year = year + 1
            next_month = 1
        else:
            next_year = year
            next_month = month + 1

        end = datetime(
            next_year,
            next_month,
            1,
            0,
            0,
            0,
            tzinfo=timezone.utc,
        )

        windows.append(
            (
                start,
                end,
                year,
                month,
            )
        )

        month += 1

        if month > 12:
            month = 1
            year += 1

    return windows


# ============================================================
# EXPECTED MONTHS FOR YEAR
# ============================================================

def get_expected_month_keys_for_year(
    year: int,
    month_windows: list[tuple],
) -> set[str]:
    """
    Kisi year ke actual backtest months return karta hai.
    """

    return {
        f"{window_year}-{window_month:02d}"
        for _, _, window_year, window_month
        in month_windows
        if window_year == year
    }


# ============================================================
# DATA FETCH
# ============================================================

def fetch_all_historical_data(
    exchange,
    fetch_start: datetime,
    fetch_end: datetime,
) -> dict:
    """
    Sab coins/timeframes ka historical data fetch karke
    memory cache mein store karta hai.

    Cache keys:
        (coin, timeframe)
        (coin, "1d")
        ("BTC/USDT", "1h_regime")
    """

    full_data_cache = {}

    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "[PHASE 1] FETCHING HISTORICAL DATA"
    )
    logger.info("=" * 60)

    total_coins = len(
        hc.HIST_COIN_UNIVERSE
    )

    for coin_index, coin in enumerate(
        hc.HIST_COIN_UNIVERSE,
        start=1,
    ):

        logger.info(
            "[%d/%d] Processing %s",
            coin_index,
            total_coins,
            coin,
        )

        # ----------------------------------------------------
        # Main strategy timeframes
        # ----------------------------------------------------

        for timeframe in hc.TIMEFRAMES:

            logger.info(
                "  Fetching %s [%s]...",
                coin,
                timeframe,
            )

            try:

                df = fetch_full_history(
                    exchange=exchange,
                    symbol=coin,
                    timeframe=timeframe,
                    since_dt=fetch_start,
                    until_dt=fetch_end,
                    candles_per_page=hc.CANDLES_PER_PAGE,
                )

                full_data_cache[
                    (coin, timeframe)
                ] = df

                logger.info(
                    "  ✓ %s [%s]: %d candles",
                    coin,
                    timeframe,
                    len(df),
                )

            except Exception as e:

                logger.error(
                    "  ✗ FETCH FAILED %s [%s]: %s",
                    coin,
                    timeframe,
                    e,
                )

                full_data_cache[
                    (coin, timeframe)
                ] = None

        # ----------------------------------------------------
        # Daily data
        # ----------------------------------------------------

        logger.info(
            "  Fetching %s [1d]...",
            coin,
        )

        try:

            df_daily = fetch_full_history(
                exchange=exchange,
                symbol=coin,
                timeframe="1d",
                since_dt=fetch_start,
                until_dt=fetch_end,
                candles_per_page=hc.CANDLES_PER_PAGE,
            )

            full_data_cache[
                (coin, "1d")
            ] = df_daily

            logger.info(
                "  ✓ %s [1d]: %d candles",
                coin,
                len(df_daily),
            )

        except Exception as e:

            logger.error(
                "  ✗ DAILY FETCH FAILED %s: %s",
                coin,
                e,
            )

            full_data_cache[
                (coin, "1d")
            ] = None

        # ----------------------------------------------------
        # BTC 1H regime data
        # ----------------------------------------------------

        if coin == "BTC/USDT":

            logger.info(
                "  Fetching BTC/USDT [1h regime]..."
            )

            try:

                df_btc_1h = fetch_full_history(
                    exchange=exchange,
                    symbol="BTC/USDT",
                    timeframe="1h",
                    since_dt=fetch_start,
                    until_dt=fetch_end,
                    candles_per_page=hc.CANDLES_PER_PAGE,
                )

                full_data_cache[
                    ("BTC/USDT", "1h_regime")
                ] = df_btc_1h

                logger.info(
                    "  ✓ BTC/USDT [1h regime]: %d candles",
                    len(df_btc_1h),
                )

            except Exception as e:

                logger.warning(
                    "  ⚠ BTC 1H regime fetch failed: %s",
                    e,
                )

                full_data_cache[
                    ("BTC/USDT", "1h_regime")
                ] = None

    logger.info("")
    logger.info(
        "[PHASE 1 COMPLETE] Cache entries: %d",
        len(full_data_cache),
    )

    return full_data_cache


# ============================================================
# MONTH BACKTEST
# ============================================================

def process_single_month(
    month_start: datetime,
    month_end: datetime,
    year: int,
    month: int,
    full_data_cache: dict,
) -> dict:
    """
    Ek complete month ka backtest execute karta hai.
    """

    month_key = f"{year}-{month:02d}"

    logger.info("")
    logger.info(
        "=" * 60
    )
    logger.info(
        "[PHASE 2] PROCESSING %s",
        month_key,
    )
    logger.info(
        "=" * 60
    )

    all_zones_this_month = []

    coin_errors_this_month = []

    df_btc_1h = full_data_cache.get(
        ("BTC/USDT", "1h_regime")
    )

    # --------------------------------------------------------
    # Coin loop
    # --------------------------------------------------------

    for coin in hc.HIST_COIN_UNIVERSE:

        df_daily = full_data_cache.get(
            (coin, "1d")
        )

        for timeframe in hc.TIMEFRAMES:

            df_main = full_data_cache.get(
                (coin, timeframe)
            )

            if (
                df_main is None
                or len(df_main) == 0
            ):

                coin_errors_this_month.append(
                    f"{coin}[{timeframe}]"
                )

                continue

            # 1H strategy ko 4H intermediate data chahiye
            if timeframe == "1h":

                df_intermediate = (
                    full_data_cache.get(
                        (coin, "4h")
                    )
                )

            else:

                df_intermediate = None

            # Daily data unavailable ho to empty DF
            if (
                df_daily is None
                or len(df_daily) == 0
            ):

                empty_daily = df_main.iloc[
                    :0
                ].copy()

            else:

                empty_daily = df_daily

            try:

                zones = (
                    backtest_single_coin_month(
                        df_main=df_main,
                        df_daily=empty_daily,
                        df_intermediate=df_intermediate,
                        df_btc_1h=df_btc_1h,
                        coin=coin,
                        timeframe=timeframe,
                        month_start=month_start,
                        month_end=month_end,
                        # NOTE: TF_SETTINGS live config.py se
                        # aati hai (hist_config.py mein nahi hai —
                        # dono files ka jaan-bhoojh kar alag design).
                        tf_cfg=live_cfg.TF_SETTINGS[
                            timeframe
                        ],
                    )
                )

                all_zones_this_month.extend(
                    zones
                )

            except Exception as e:

                error_string = (
                    f"{coin}[{timeframe}]:"
                    f"{type(e).__name__}"
                )

                coin_errors_this_month.append(
                    error_string
                )

                logger.warning(
                    "    %s — %s",
                    error_string,
                    e,
                )

    # --------------------------------------------------------
    # Monthly metrics
    # --------------------------------------------------------

    metrics_this_month = (
        compute_month_metrics(
            all_zones_this_month,
            hc.BINANCE_FEE_PCT,
            hc.SLIPPAGE_PCT,
        )
    )

    day_breakdown = (
        compute_day_breakdown(
            all_zones_this_month
        )
    )

    # --------------------------------------------------------
    # BTC market condition
    # --------------------------------------------------------

    market_type = "UNKNOWN"

    df_btc_daily = full_data_cache.get(
        ("BTC/USDT", "1d")
    )

    if (
        df_btc_daily is not None
        and len(df_btc_daily) > 0
    ):

        btc_month_daily = df_btc_daily[
            (
                df_btc_daily["timestamp"]
                >= pd.Timestamp(month_start)
            )
            &
            (
                df_btc_daily["timestamp"]
                < pd.Timestamp(month_end)
            )
        ]

        market_type = (
            _classify_month_market(
                btc_month_daily
            )
        )

    result = {
        "month_key": month_key,
        "year": year,
        "month": month,
        "market_type": market_type,
        "metrics": metrics_this_month,
        "day_breakdown": day_breakdown,
        "zones": all_zones_this_month,
        "coin_errors": coin_errors_this_month,
    }

    logger.info(
        "    %s: %d trades | %dW/%dL | "
        "P&L=%+.2fR | WR=%.1f%%",
        month_key,
        metrics_this_month["total_trades"],
        metrics_this_month["wins"],
        metrics_this_month["losses"],
        metrics_this_month["net_pnl_r"],
        metrics_this_month["win_rate_pct"],
    )

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "  HISTORICAL FIBONACCI BACKTEST STARTING"
    )
    logger.info("=" * 60)

    logger.info(
        "  Coins: %d",
        len(hc.HIST_COIN_UNIVERSE),
    )

    logger.info(
        "  Timeframes: %s",
        hc.TIMEFRAMES,
    )

    logger.info(
        "  Start: %04d-%02d",
        hc.HIST_START_YEAR,
        hc.HIST_START_MONTH,
    )

    # --------------------------------------------------------
    # Generate completed-month windows
    # --------------------------------------------------------

    month_windows = (
        generate_month_windows()
    )

    if not month_windows:

        logger.error(
            "No completed months available for backtest."
        )

        return 1

    first_window = month_windows[0]
    last_window = month_windows[-1]

    logger.info(
        "  First month: %04d-%02d",
        first_window[2],
        first_window[3],
    )

    logger.info(
        "  Last completed month: %04d-%02d",
        last_window[2],
        last_window[3],
    )

    logger.info(
        "  Total months: %d",
        len(month_windows),
    )

    # --------------------------------------------------------
    # Exchange
    # --------------------------------------------------------

    logger.info("")
    logger.info(
        "Finding working historical-data exchange..."
    )

    try:

        exchange, exchange_id = (
            get_working_exchange_hist()
        )

    except Exception as e:

        logger.exception(
            "Could not connect to any historical exchange."
        )

        return 1

    logger.info(
        "Using exchange: %s",
        exchange_id,
    )

    # --------------------------------------------------------
    # Fetch range
    # --------------------------------------------------------

    fetch_start = datetime(
        hc.HIST_START_YEAR,
        hc.HIST_START_MONTH,
        1,
        tzinfo=timezone.utc,
    )

    # Fetch only up to current time.
    # Current incomplete month candles can exist in cache,
    # but generate_month_windows() never backtests them.
    fetch_end = datetime.now(
        timezone.utc
    )

    # --------------------------------------------------------
    # PHASE 1
    # --------------------------------------------------------

    full_data_cache = (
        fetch_all_historical_data(
            exchange,
            fetch_start,
            fetch_end,
        )
    )

    # --------------------------------------------------------
    # PHASE 2
    # --------------------------------------------------------

    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "[PHASE 2] MONTH-BY-MONTH BACKTEST"
    )
    logger.info("=" * 60)

    all_monthly_results = []

    monthly_metrics_agg = {}

    years_processed = set()

    # --------------------------------------------------------
    # Month loop
    # --------------------------------------------------------

    for (
        month_start,
        month_end,
        year,
        month,
    ) in month_windows:

        result = process_single_month(
            month_start=month_start,
            month_end=month_end,
            year=year,
            month=month,
            full_data_cache=full_data_cache,
        )

        all_monthly_results.append(
            result
        )

        monthly_metrics_agg[
            result["month_key"]
        ] = result["metrics"]

        # ----------------------------------------------------
        # Check whether complete year is ready
        # ----------------------------------------------------

        if year in years_processed:
            continue

        expected_months = (
            get_expected_month_keys_for_year(
                year,
                month_windows,
            )
        )

        completed_months = {
            r["month_key"]
            for r in all_monthly_results
            if r["year"] == year
        }

        if expected_months.issubset(
            completed_months
        ):

            logger.info("")
            logger.info(
                "=" * 60
            )

            logger.info(
                "[PHASE 3] Sending %d annual report...",
                year,
            )

            logger.info(
                "=" * 60
            )

            try:

                send_year_report(
                    year=year,
                    monthly_results=all_monthly_results,
                    monthly_metrics=monthly_metrics_agg,
                    cfg=hc,
                )

                years_processed.add(
                    year
                )

            except Exception:

                logger.exception(
                    "Annual email failed for %d",
                    year,
                )

    # --------------------------------------------------------
    # PHASE 3 — Overall summary
    # --------------------------------------------------------

    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "[PHASE 3] Sending overall summary..."
    )
    logger.info("=" * 60)

    try:

        send_overall_summary_report(
            monthly_results=all_monthly_results,
            monthly_metrics=monthly_metrics_agg,
            cfg=hc,
        )

    except Exception:

        logger.exception(
            "Overall summary email failed."
        )

    # --------------------------------------------------------
    # Final summary
    # --------------------------------------------------------

    total_zones = sum(
        r["metrics"]["total_trades"]
        for r in all_monthly_results
    )

    total_wins = sum(
        r["metrics"]["wins"]
        for r in all_monthly_results
    )

    total_losses = sum(
        r["metrics"]["losses"]
        for r in all_monthly_results
    )

    total_pnl_r = sum(
        r["metrics"]["net_pnl_r"]
        for r in all_monthly_results
    )

    resolved = total_wins + total_losses

    overall_win_rate = (
        (total_wins / resolved * 100.0)
        if resolved > 0
        else 0.0
    )

    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "  HISTORICAL BACKTEST COMPLETE"
    )
    logger.info("=" * 60)

    logger.info(
        "  Total Trades:  %d",
        total_zones,
    )

    logger.info(
        "  Wins / Losses: %d / %d",
        total_wins,
        total_losses,
    )

    logger.info(
        "  Win Rate:      %.1f%%",
        overall_win_rate,
    )

    logger.info(
        "  Net P&L (R):   %+.2f R",
        total_pnl_r,
    )

    logger.info("=" * 60)

    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    exit_code = main()

    sys.exit(exit_code)
