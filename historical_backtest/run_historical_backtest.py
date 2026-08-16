"""
run_historical_backtest.py — Main Entry Point for 5-Year Historical Backtest.

Flow:
1. 2021-01 se current month tak, har month ki window set karo
2. Har coin ke liye paginated full history fetch karo (cache in memory)
3. Har month ki candle-by-candle replay + signal_engine.analyze() chalao
4. Zone resolve karo (WIN/LOSS/EXPIRED/TIMEOUT) + Day-by-Day breakdown banao
5. Year-by-year emails bhejo (max 6 emails: 2021/2022/2023/2024/2025/2026)
6. Aakhir mein 5-year overall summary email bhejo

Usage:
  cd historical_backtest
  python run_historical_backtest.py

Ya GitHub Actions se:
  Workflow manually trigger karo "Historical Backtest — 5-Year Analysis"
"""

import sys
import os
import logging
from datetime import datetime, timezone
from calendar import monthrange

# ─── Path setup: parent dir mein jao taake signal_engine etc. import ho sake ───
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF_DIR   = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PARENT_DIR)
sys.path.insert(0, SELF_DIR)

import hist_config as hc
from hist_data_fetcher  import fetch_full_history, get_working_exchange_hist
from hist_backtester    import (
    backtest_single_coin_month,
    compute_month_metrics,
    compute_day_breakdown,
    _classify_month_market,
)
from hist_reporter import (
    send_year_report,
    send_overall_summary_report,
)

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(SELF_DIR, "hist_backtest.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("hist_backtest")


# ─── Helper: Generate Month Windows ─────────────────────────────────────────

def generate_month_windows() -> list[tuple]:
    """
    2021-01 se current month (exclusive) tak ke (month_start, month_end, year, month) tuples generate karta hai.
    """
    now   = datetime.now(timezone.utc)
    windows = []
    year  = hc.HIST_START_YEAR
    month = hc.HIST_START_MONTH

    while (year, month) < (now.year, now.month):
        _, last_day = monthrange(year, month)
        start = datetime(year, month,    1,        0, 0, 0, tzinfo=timezone.utc)
        end   = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
        windows.append((start, end, year, month))
        month += 1
        if month > 12:
            month  = 1
            year  += 1

    return windows


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("  5-YEAR HISTORICAL BACKTEST STARTING")
    logger.info(f"  Coins: {len(hc.HIST_COIN_UNIVERSE)}")
    logger.info(f"  Timeframes: {hc.TIMEFRAMES}")
    logger.info("=" * 60)

    exchange, exchange_id = get_working_exchange_hist()

    month_windows = generate_month_windows()
    logger.info(f"Total months to backtest: {len(month_windows)}")

    # ─── Step 1: Fetch full history for all coins (in-memory cache) ──────────
    logger.info("\n[PHASE 1] Fetching full historical data for all coins...")
    full_data_cache: dict[tuple, object] = {}   # (coin, timeframe) → DataFrame

    fetch_start = datetime(hc.HIST_START_YEAR, hc.HIST_START_MONTH, 1, tzinfo=timezone.utc)
    fetch_end   = datetime.now(timezone.utc)

    for coin in hc.HIST_COIN_UNIVERSE:
        for tf in hc.TIMEFRAMES:
            logger.info(f"  Fetching {coin} [{tf}]...")
            try:
                df = fetch_full_history(exchange, coin, tf, fetch_start, fetch_end, hc.CANDLES_PER_PAGE)
                full_data_cache[(coin, tf)] = df
            except Exception as e:
                logger.error(f"  FETCH FAILED {coin} [{tf}]: {e}")
                full_data_cache[(coin, tf)] = None

        # BTC 1H for regime filter
        if coin == "BTC/USDT":
            try:
                df_btc_1h = fetch_full_history(exchange, "BTC/USDT", "1h", fetch_start, fetch_end, hc.CANDLES_PER_PAGE)
                full_data_cache[("BTC/USDT", "1h_regime")] = df_btc_1h
                logger.info("  BTC/USDT [1h] regime filter data fetched.")
            except Exception as e:
                logger.warning(f"  BTC 1H regime data fetch failed: {e}")
                full_data_cache[("BTC/USDT", "1h_regime")] = None

        # Daily data for all coins
        try:
            df_daily = fetch_full_history(exchange, coin, "1d", fetch_start, fetch_end, hc.CANDLES_PER_PAGE)
            full_data_cache[(coin, "1d")] = df_daily
        except Exception as e:
            logger.error(f"  Daily data FAILED {coin}: {e}")
            full_data_cache[(coin, "1d")] = None

    logger.info(f"\n[PHASE 1 COMPLETE] Data cached for {len(hc.HIST_COIN_UNIVERSE)} coins.\n")

    # ─── Step 2: Month-by-Month Backtest ─────────────────────────────────────
    logger.info("[PHASE 2] Running month-by-month backtest...")

    all_monthly_results:  list[dict] = []
    monthly_metrics_agg:  dict       = {}

    years_processed = set()

    for (month_start, month_end, year, month) in month_windows:
        month_key = f"{year}-{month:02d}"
        logger.info(f"  Processing: {month_key}...")

        all_zones_this_month: list[dict] = []
        coin_errors_this_month: list[str] = []

        df_btc_1h = full_data_cache.get(("BTC/USDT", "1h_regime"))

        for coin in hc.HIST_COIN_UNIVERSE:
            df_daily = full_data_cache.get((coin, "1d"))
            market_type = "UNKNOWN"
            if df_daily is not None and len(df_daily) > 0:
                import pandas as pd
                daily_month = df_daily[
                    (df_daily["timestamp"] >= pd.Timestamp(month_start)) &
                    (df_daily["timestamp"] <  pd.Timestamp(month_end))
                ]
                market_type = _classify_month_market(daily_month)

            for tf in hc.TIMEFRAMES:
                df_main = full_data_cache.get((coin, tf))
                if df_main is None or len(df_main) == 0:
                    coin_errors_this_month.append(f"{coin}[{tf}]")
                    continue

                df_inter = full_data_cache.get((coin, "4h")) if tf == "1h" else None

                try:
                    zones = backtest_single_coin_month(
                        df_main          = df_main,
                        df_daily         = df_daily if df_daily is not None else df_main.head(0),
                        df_intermediate  = df_inter,
                        df_btc_1h        = df_btc_1h,
                        coin             = coin,
                        timeframe        = tf,
                        month_start      = month_start,
                        month_end        = month_end,
                        tf_cfg           = hc.TF_SETTINGS[tf],
                    )
                    all_zones_this_month.extend(zones)
                except Exception as e:
                    err_str = f"{coin}[{tf}]:{type(e).__name__}"
                    coin_errors_this_month.append(err_str)
                    logger.warning(f"    {err_str} — {e}")

        # Metrics & day breakdown
        metrics_this_month  = compute_month_metrics(all_zones_this_month, hc.BINANCE_FEE_PCT, hc.SLIPPAGE_PCT)
        day_breakdown       = compute_day_breakdown(all_zones_this_month)

        # Market type from BTC daily (most representative)
        df_btc_daily = full_data_cache.get(("BTC/USDT", "1d"))
        if df_btc_daily is not None and len(df_btc_daily) > 0:
            import pandas as pd
            btc_month_daily = df_btc_daily[
                (df_btc_daily["timestamp"] >= pd.Timestamp(month_start)) &
                (df_btc_daily["timestamp"] <  pd.Timestamp(month_end))
            ]
            market_type = _classify_month_market(btc_month_daily)
        else:
            market_type = "UNKNOWN"

        monthly_metrics_agg[month_key] = metrics_this_month
        all_monthly_results.append({
            "month_key":    month_key,
            "year":         year,
            "month":        month,
            "market_type":  market_type,
            "metrics":      metrics_this_month,
            "day_breakdown": day_breakdown,
            "zones":        all_zones_this_month,
            "coin_errors":  coin_errors_this_month,
        })

        logger.info(
            f"    {month_key}: {metrics_this_month['total_trades']} trades, "
            f"{metrics_this_month['wins']}W/{metrics_this_month['losses']}L, "
            f"P&L={metrics_this_month['net_pnl_r']:+.2f}R, "
            f"WR={metrics_this_month['win_rate_pct']:.1f}%"
        )

        # ─── Email current year as soon as its last month is done ───────────
        years_in_results = set(r["year"] for r in all_monthly_results)
        for y in sorted(years_in_results):
            if y in years_processed:
                continue
            # Check if all months of year y are done
            year_months_expected = [
                f"{y}-{m:02d}" for m in range(1, 13)
                if (y, m) < (datetime.now(timezone.utc).year, datetime.now(timezone.utc).month)
                and (y > hc.HIST_START_YEAR or m >= hc.HIST_START_MONTH)
            ]
            year_months_done = [r["month_key"] for r in all_monthly_results if r["year"] == y]
            if set(year_months_expected).issubset(set(year_months_done)):
                logger.info(f"\n[PHASE 3] Sending {y} Annual Report email...")
                send_year_report(y, all_monthly_results, monthly_metrics_agg, hc)
                years_processed.add(y)

    # ─── Step 3: 5-Year Overall Summary email ────────────────────────────────
    logger.info("\n[PHASE 3] Sending 5-Year Overall Summary email...")
    send_overall_summary_report(all_monthly_results, monthly_metrics_agg, hc)

    logger.info("\n" + "=" * 60)
    logger.info("  5-YEAR HISTORICAL BACKTEST COMPLETE!")
    logger.info(f"  Total months processed: {len(all_monthly_results)}")
    logger.info(f"  Total zones detected:   {sum(r['metrics']['total_trades'] for r in all_monthly_results)}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
