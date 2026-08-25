"""
run_local_backtest.py — Main Entry Point for the LOCAL 1-Year Backtest.

Flow:
1. Working exchange dhoondo (kucoin/okx/... priority list)
2. Har coin ke liye paginated full history fetch karo (window + warmup buffer)
3. Har (coin, timeframe) ka ONE continuous candle-by-candle replay chalao
   (zero look-ahead, zero mid-window state resets)
4. Zones ko month-wise bucket karke report + CSV banao
5. Local files mein save karo (+ optional email agar SEND_EMAIL=true)

Usage:
  cd local_backtest
  python run_local_backtest.py
"""

import sys
import os
import logging
from datetime import datetime, timezone

# Path setup: parent dir mein jao taake signal_engine, config, etc. import ho sakein
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PARENT_DIR)
sys.path.insert(0, SELF_DIR)

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(SELF_DIR, ".env"))
except ImportError:
    pass  # python-dotenv optional -- env vars can also be set directly in the shell

import config
import local_config as lc
from local_data_fetcher import fetch_full_history, get_working_exchange_local
from local_backtester import (
    backtest_coin_timeframe_period,
    apply_portfolio_protection,
    compute_metrics,
    compute_day_breakdown,
    bucket_zones_by_month,
    _classify_month_market,
)
from local_reporter import write_full_report, write_zones_csv, send_email_report

os.makedirs(lc.OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(lc.OUTPUT_DIR, "local_backtest.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("local_backtest")


def main():
    logger.info("=" * 60)
    logger.info("  LOCAL 1-YEAR HISTORICAL BACKTEST STARTING")
    logger.info(f"  Window: {lc.BACKTEST_START.strftime('%Y-%m-%d')} -> {lc.BACKTEST_END.strftime('%Y-%m-%d')}")
    logger.info(f"  Warmup buffer: {lc.WARMUP_DAYS} days (fetch starts {lc.FETCH_START.strftime('%Y-%m-%d')})")
    logger.info(f"  Coins: {len(lc.COIN_UNIVERSE)}")
    logger.info(f"  Timeframes: {lc.TIMEFRAMES}")
    logger.info("=" * 60)

    exchange, exchange_id = get_working_exchange_local()

    # ─── Phase 1: fetch full history for all coins (in-memory cache) ────────
    logger.info("\n[PHASE 1] Fetching historical data for all coins...")
    data_cache: dict[tuple, object] = {}  # (coin, timeframe) -> DataFrame

    fetch_start = lc.FETCH_START
    fetch_end = lc.BACKTEST_END

    for coin in lc.COIN_UNIVERSE:
        for tf in lc.TIMEFRAMES:
            logger.info(f"  Fetching {coin} [{tf}]...")
            try:
                df = fetch_full_history(exchange, coin, tf, fetch_start, fetch_end, lc.CANDLES_PER_PAGE)
                data_cache[(coin, tf)] = df
            except Exception as e:
                logger.error(f"  FETCH FAILED {coin} [{tf}]: {e}")
                data_cache[(coin, tf)] = None

        if coin == "BTC/USDT":
            try:
                df_btc_1h = fetch_full_history(exchange, "BTC/USDT", "1h", fetch_start, fetch_end, lc.CANDLES_PER_PAGE)
                data_cache[("BTC/USDT", "1h_regime")] = df_btc_1h
                logger.info("  BTC/USDT [1h] regime filter data fetched.")
            except Exception as e:
                logger.warning(f"  BTC 1H regime data fetch failed: {e}")
                data_cache[("BTC/USDT", "1h_regime")] = None

        try:
            df_daily = fetch_full_history(exchange, coin, "1d", fetch_start, fetch_end, lc.CANDLES_PER_PAGE)
            data_cache[(coin, "1d")] = df_daily
        except Exception as e:
            logger.error(f"  Daily data FAILED {coin}: {e}")
            data_cache[(coin, "1d")] = None

    logger.info(f"\n[PHASE 1 COMPLETE] Data cached for {len(lc.COIN_UNIVERSE)} coins.\n")

    # ─── Phase 2: continuous per-(coin, timeframe) replay across full window ─
    logger.info("[PHASE 2] Running continuous 1-year replay per coin/timeframe...")

    all_zones: list[dict] = []
    coin_errors: list[str] = []

    df_btc_1h = data_cache.get(("BTC/USDT", "1h_regime"))

    for coin in lc.COIN_UNIVERSE:
        df_daily = data_cache.get((coin, "1d"))

        for tf in lc.TIMEFRAMES:
            df_main = data_cache.get((coin, tf))
            if df_main is None or len(df_main) == 0:
                coin_errors.append(f"{coin}[{tf}]")
                continue

            df_inter = data_cache.get((coin, "4h")) if tf == "1h" else None
            tf_cfg = config.TF_SETTINGS[tf]

            df_btc_daily = data_cache.get(("BTC/USDT", "1d"))

            logger.info(f"  Replaying {coin} [{tf}] ({len(df_main)} candles)...")
            try:
                zones = backtest_coin_timeframe_period(
                    df_main=df_main,
                    df_daily=df_daily if df_daily is not None else df_main.head(0),
                    df_intermediate=df_inter,
                    df_btc_1h=df_btc_1h,
                    df_btc_daily=df_btc_daily,
                    coin=coin,
                    timeframe=tf,
                    period_start=lc.BACKTEST_START,
                    period_end=lc.BACKTEST_END,
                    tf_cfg=tf_cfg,
                )
                all_zones.extend(zones)
                logger.info(f"    -> {len(zones)} zone(s) found.")
            except Exception as e:
                err_str = f"{coin}[{tf}]:{type(e).__name__}"
                coin_errors.append(err_str)
                logger.warning(f"    {err_str} -- {e}")

    logger.info(f"\n[PHASE 2 COMPLETE] Raw zones found: {len(all_zones)} across {len(lc.COIN_UNIVERSE)} coins.")
    
    # Portfolio-wide Global Daily Protection (Max 3 daily setups, -2.0R circuit breaker)
    all_zones = apply_portfolio_protection(all_zones)
    logger.info(f"[PORTFOLIO PROTECTION] Final shielded zones: {len(all_zones)}\n")

    # ─── Phase 3: month-wise bucketing (reporting only, replay already done) ─
    logger.info("[PHASE 3] Building monthly + overall report...")

    monthly_zone_buckets = bucket_zones_by_month(all_zones)
    monthly_results = []
    monthly_metrics = {}

    for month_key, zones in monthly_zone_buckets.items():
        year, month = int(month_key[:4]), int(month_key[5:7])
        df_btc_daily = data_cache.get(("BTC/USDT", "1d"))
        market_type = "UNKNOWN"
        if df_btc_daily is not None and len(df_btc_daily) > 0:
            month_start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
            month_end = (month_start + pd.offsets.MonthBegin(1))
            btc_month = df_btc_daily[(df_btc_daily["timestamp"] >= month_start) & (df_btc_daily["timestamp"] < month_end)]
            market_type = _classify_month_market(btc_month)

        metrics = compute_metrics(zones)
        day_breakdown = compute_day_breakdown(zones)
        monthly_metrics[month_key] = metrics
        monthly_results.append({
            "month_key": month_key,
            "market_type": market_type,
            "metrics": metrics,
            "day_breakdown": day_breakdown,
            "zones": zones,
        })
        logger.info(f"    {month_key}: {metrics['total_trades']} trades, "
                    f"{metrics['wins']}W/{metrics['losses']}L, P&L={metrics['net_pnl_r']:+.2f}R")

    overall_metrics = compute_metrics(all_zones)

    report_path = write_full_report(
        output_dir=lc.OUTPUT_DIR,
        overall_metrics=overall_metrics,
        monthly_results=monthly_results,
        monthly_metrics=monthly_metrics,
        all_zones=all_zones,
        coin_universe=lc.COIN_UNIVERSE,
        timeframes=lc.TIMEFRAMES,
        start_dt=lc.BACKTEST_START,
        end_dt=lc.BACKTEST_END,
    )
    csv_path = write_zones_csv(lc.OUTPUT_DIR, all_zones)

    if coin_errors:
        logger.warning(f"\n[!] Data gaps / fetch errors ({len(coin_errors)}): {', '.join(coin_errors[:10])}"
                       + ("..." if len(coin_errors) > 10 else ""))

    # ─── Phase 4: optional email ──────────────────────────────────────────
    if lc.SEND_EMAIL:
        with open(report_path, "r", encoding="utf-8") as f:
            report_text = f.read()
        send_email_report(report_text, lc)

    logger.info("\n" + "=" * 60)
    logger.info("  LOCAL 1-YEAR BACKTEST COMPLETE!")
    logger.info(f"  Total zones: {len(all_zones)}")
    logger.info(f"  Net P&L: {overall_metrics['net_pnl_r']:+.2f} R")
    logger.info(f"  Win Rate: {overall_metrics['win_rate_pct']:.1f}%")
    logger.info(f"  Report: {report_path}")
    logger.info(f"  CSV:    {csv_path}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
