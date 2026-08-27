"""
run_realistic_backtest.py -- Realistic Historical Backtest with Hourly Dynamic Coin Selection.

LIVE SYSTEM (har 30 min):
  - Exchange se live tickers fetch karo
  - Volume > $15M, Volatility 2.5%-12%, Spread < 0.08% filters apply karo
  - Top coins sort by volume

BACKTEST (yeh script -- har 1 ghanta):
  - Us waqt ke historical 1H candle data se same filters simulate karo
  - Volume > $15M  -> last 24 x 1H candles ka sum(volume * close)
  - Volatility 2.5%-12% -> (max_high - min_low) / min_low * 100 over 24H
  - Top coins sort by volume -> signal_engine chalao

Period: 2 January 2025 -> 31 January 2025

Usage:
  cd local_backtest
  python run_realistic_backtest.py
"""

import sys, os, logging
from datetime import datetime, timezone, timedelta

PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF_DIR   = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PARENT_DIR)
sys.path.insert(0, SELF_DIR)

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(SELF_DIR, ".env"))
except ImportError:
    pass

import config
from local_data_fetcher import fetch_full_history, get_working_exchange_local
from local_backtester import (
    backtest_coin_timeframe_period, apply_portfolio_protection,
    compute_metrics, compute_day_breakdown, _classify_month_market,
)
from local_reporter import write_full_report, write_zones_csv

# ============================================================
# CONFIGURATION -- January 2025
# ============================================================
BACKTEST_START           = datetime(2025, 1, 2,  0, 0, 0, tzinfo=timezone.utc)
BACKTEST_END             = datetime(2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
WARMUP_DAYS              = 90
FETCH_START              = BACKTEST_START - timedelta(days=WARMUP_DAYS)
OUTPUT_DIR               = os.path.join(PARENT_DIR, "output")

MIN_24H_VOLUME_USD       = config.MIN_24H_VOLUME_USD
MIN_DAILY_VOLATILITY_PCT = config.MIN_DAILY_VOLATILITY_PCT
MAX_DAILY_VOLATILITY_PCT = config.MAX_DAILY_VOLATILITY_PCT
DYNAMIC_UNIVERSE_LIMIT   = 20

CANDIDATE_COINS = [
    "BTC/USDT",  "ETH/USDT",  "SOL/USDT",  "BNB/USDT",  "XRP/USDT",
    "DOGE/USDT", "ADA/USDT",  "AVAX/USDT", "LTC/USDT",  "LINK/USDT",
    "NEAR/USDT", "TRX/USDT",  "UNI/USDT",  "ATOM/USDT", "ETC/USDT",
    "FIL/USDT",  "AAVE/USDT", "ICP/USDT",  "SUI/USDT",  "PEPE/USDT",
    "FET/USDT",  "TAO/USDT",  "ENA/USDT",  "XLM/USDT",  "ALGO/USDT",
    "ONDO/USDT", "WLD/USDT",  "INJ/USDT",  "PYTH/USDT", "TIA/USDT",
]

TIMEFRAMES = [tf for tf in config.TIMEFRAMES if tf in ("4h", "1h")]

STABLECOIN_SYMBOLS = {
    "USDC/USDT", "FDUSD/USDT", "TUSD/USDT", "DAI/USDT",
    "EUR/USDT", "USDE/USDT", "BUSD/USDT", "USDP/USDT",
}

os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(OUTPUT_DIR, "realistic_backtest.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("realistic_backtest")


def simulate_dynamic_universe_at(data_cache, candidate_coins, snapshot_ts, top_n=DYNAMIC_UNIVERSE_LIMIT):
    """
    snapshot_ts ke waqt par live coin_universe.py jaisi selection simulate karta hai.
    Last 24 x 1H candles se volume aur volatility compute karta hai (no look-ahead).
    """
    scored = []
    for coin in candidate_coins:
        if coin in STABLECOIN_SYMBOLS:
            continue
        df_1h = data_cache.get((coin, "1h"))
        if df_1h is None or len(df_1h) < 5:
            continue
        past = df_1h[df_1h["timestamp"] < snapshot_ts].tail(24)
        if len(past) < 8:
            continue
        vol_usd_24h = float((past["volume"] * past["close"]).sum())
        if vol_usd_24h < MIN_24H_VOLUME_USD:
            continue
        max_h = float(past["high"].max())
        min_l = float(past["low"].min())
        if min_l <= 0:
            continue
        vol_pct = (max_h - min_l) / min_l * 100
        if not (MIN_DAILY_VOLATILITY_PCT <= vol_pct <= MAX_DAILY_VOLATILITY_PCT):
            continue
        scored.append((coin, vol_usd_24h))
    scored.sort(key=lambda x: -x[1])
    return [c[0] for c in scored[:top_n]]


def main():
    logger.info("=" * 65)
    logger.info("  REALISTIC BACKTEST -- January 2025")
    logger.info("  Hourly Dynamic Coin Selection (Exact Live System Logic)")
    logger.info(f"  Period : {BACKTEST_START.strftime('%Y-%m-%d')} -> {BACKTEST_END.strftime('%Y-%m-%d')}")
    logger.info(f"  Candidate Pool : {len(CANDIDATE_COINS)} coins | Top {DYNAMIC_UNIVERSE_LIMIT}/hour selected")
    logger.info(f"  Filters : Volume > ${MIN_24H_VOLUME_USD/1e6:.0f}M | Volatility {MIN_DAILY_VOLATILITY_PCT}%-{MAX_DAILY_VOLATILITY_PCT}%")
    logger.info(f"  Timeframes : {TIMEFRAMES}")
    logger.info("=" * 65)

    exchange, _ = get_working_exchange_local()

    # Phase 1: Fetch data
    logger.info("\n[PHASE 1] Fetching historical candle data for all candidates...")
    data_cache = {}
    for coin in CANDIDATE_COINS:
        for tf in list(set(["1h"] + TIMEFRAMES + ["1d"])):
            if (coin, tf) in data_cache:
                continue
            try:
                df = fetch_full_history(exchange, coin, tf, FETCH_START, BACKTEST_END, 500)
                data_cache[(coin, tf)] = df
                logger.info(f"  {coin} [{tf}] -> {len(df)} candles")
            except Exception as e:
                logger.warning(f"  FAIL {coin} [{tf}]: {e}")
                data_cache[(coin, tf)] = None
        if coin == "BTC/USDT":
            data_cache[("BTC/USDT", "1h_regime")] = data_cache.get(("BTC/USDT", "1h"))
    logger.info("\n[PHASE 1 COMPLETE]\n")

    # Phase 2: Hourly replay
    logger.info("[PHASE 2] Hourly Dynamic Replay starting...")
    df_btc_1h    = data_cache.get(("BTC/USDT", "1h_regime"))
    df_btc_daily = data_cache.get(("BTC/USDT", "1d"))

    hourly_slots = pd.date_range(start=BACKTEST_START, end=BACKTEST_END, freq="1h", tz="UTC")
    logger.info(f"  Total hourly slots: {len(hourly_slots)}")

    all_zones      = []
    seen_zone_keys = set()
    prev_selected  = []

    for slot_idx, slot_ts in enumerate(hourly_slots):
        selected = simulate_dynamic_universe_at(data_cache, CANDIDATE_COINS, slot_ts)
        if not selected:
            continue

        if selected != prev_selected or slot_idx % 24 == 0:
            logger.info(
                f"  [{slot_ts.strftime('%Y-%m-%d %H:00')} UTC] "
                f"{len(selected)} coins: {', '.join(selected[:8])}{'...' if len(selected) > 8 else ''}"
            )
            prev_selected = selected.copy()

        slot_end = slot_ts + timedelta(hours=1)

        for coin in selected:
            df_daily = data_cache.get((coin, "1d"))
            for tf in TIMEFRAMES:
                df_main = data_cache.get((coin, tf))
                if df_main is None or len(df_main) == 0:
                    continue
                df_inter = data_cache.get((coin, "4h")) if tf == "1h" else None
                try:
                    new_zones = backtest_coin_timeframe_period(
                        df_main=df_main,
                        df_daily=df_daily if df_daily is not None else df_main.head(0),
                        df_intermediate=df_inter,
                        df_btc_1h=df_btc_1h,
                        df_btc_daily=df_btc_daily,
                        coin=coin, timeframe=tf,
                        period_start=slot_ts.to_pydatetime(),
                        period_end=slot_end.to_pydatetime(),
                        tf_cfg=config.TF_SETTINGS[tf],
                    )
                    for z in new_zones:
                        key = (z["coin"], z["timeframe"], str(z.get("created_at", ""))[:16])
                        if key not in seen_zone_keys:
                            seen_zone_keys.add(key)
                            all_zones.append(z)
                except Exception as e:
                    logger.debug(f"    Error {coin}[{tf}] @ {slot_ts}: {e}")

    logger.info(f"\n[PHASE 2 COMPLETE] Raw zones: {len(all_zones)}")

    # Phase 3: Portfolio protection
    logger.info("[PHASE 3] Applying portfolio protection...")
    all_zones = apply_portfolio_protection(all_zones)
    logger.info(f"  Final zones: {len(all_zones)}")

    month_key   = "2025-01"
    market_type = "UNKNOWN"
    if df_btc_daily is not None and len(df_btc_daily) > 0:
        btc_jan = df_btc_daily[
            (df_btc_daily["timestamp"] >= pd.Timestamp(BACKTEST_START)) &
            (df_btc_daily["timestamp"] <= pd.Timestamp(BACKTEST_END))
        ]
        market_type = _classify_month_market(btc_jan)

    overall_metrics = compute_metrics(all_zones)
    day_breakdown   = compute_day_breakdown(all_zones)
    monthly_metrics = {month_key: overall_metrics}
    monthly_results = [{
        "month_key": month_key, "market_type": market_type,
        "selected_coins": CANDIDATE_COINS,
        "metrics": overall_metrics, "day_breakdown": day_breakdown, "zones": all_zones,
    }]

    # Phase 4: Report
    logger.info("[PHASE 4] Writing report and CSV...")
    report_path = write_full_report(
        output_dir=OUTPUT_DIR, overall_metrics=overall_metrics,
        monthly_results=monthly_results, monthly_metrics=monthly_metrics,
        all_zones=all_zones, coin_universe=CANDIDATE_COINS,
        timeframes=TIMEFRAMES, start_dt=BACKTEST_START, end_dt=BACKTEST_END,
    )
    write_zones_csv(OUTPUT_DIR, all_zones)
    generic_csv = os.path.join(OUTPUT_DIR, "backtest_zones.csv")
    jan_csv     = os.path.join(OUTPUT_DIR, "jan2025_realistic_zones.csv")
    if os.path.exists(generic_csv):
        os.replace(generic_csv, jan_csv)

    pf = overall_metrics["profit_factor"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"

    logger.info(f"\n{'=' * 65}")
    logger.info("  REALISTIC BACKTEST COMPLETE -- January 2025")
    logger.info(f"  Market Regime   : {market_type}")
    logger.info(f"  Total Zones     : {overall_metrics['total_trades']}")
    logger.info(f"  Wins            : {overall_metrics['wins']}")
    logger.info(f"  Losses          : {overall_metrics['losses']}")
    logger.info(f"  Breakevens      : {overall_metrics.get('breakevens', 0)}")
    logger.info(f"  Expired         : {overall_metrics['expired']}")
    logger.info(f"  Timed Out       : {overall_metrics['timed_out']}")
    logger.info(f"  Win Rate        : {overall_metrics['win_rate_pct']:.1f}%")
    logger.info(f"  Net P&L         : {overall_metrics['net_pnl_r']:+.2f} R")
    logger.info(f"  Profit Factor   : {pf_str}")
    logger.info(f"  Max Drawdown    : {overall_metrics['max_drawdown_r']:.2f} R")
    logger.info(f"  Report : {report_path}")
    logger.info(f"  CSV    : {jan_csv}")
    logger.info("=" * 65)

    # ── Phase 5: Email results ────────────────────────────────────────────────
    # GitHub Actions ya local — dono jagah kaam karega agar SMTP secrets set hon
    try:
        sys.path.insert(0, PARENT_DIR)  # email_sender.py parent dir mein hai
        from email_sender import send_email

        # Report file read karo
        with open(report_path, "r", encoding="utf-8") as f:
            report_body = f.read()

        subject = (
            f"[Backtest] Jan 2025 Complete | "
            f"WR: {overall_metrics['win_rate_pct']:.1f}% | "
            f"P&L: {overall_metrics['net_pnl_r']:+.2f}R | "
            f"PF: {pf_str} | "
            f"Regime: {market_type}"
        )

        # Email body: summary + full report
        header = (
            "=" * 65 + "\n"
            "  BACKTEST COMPLETE — January 2025\n"
            "  Hourly Dynamic Coin Selection (Live System Logic Simulated)\n"
            "=" * 65 + "\n\n"
            f"  Market Regime   : {market_type}\n"
            f"  Total Zones     : {overall_metrics['total_trades']}\n"
            f"  Wins            : {overall_metrics['wins']}\n"
            f"  Losses          : {overall_metrics['losses']}\n"
            f"  Breakevens      : {overall_metrics.get('breakevens', 0)}\n"
            f"  Expired         : {overall_metrics['expired']}\n"
            f"  Timed Out       : {overall_metrics['timed_out']}\n"
            f"  Win Rate        : {overall_metrics['win_rate_pct']:.1f}%\n"
            f"  Net P&L         : {overall_metrics['net_pnl_r']:+.2f} R\n"
            f"  Profit Factor   : {pf_str}\n"
            f"  Max Drawdown    : {overall_metrics['max_drawdown_r']:.2f} R\n"
            "\n" + "=" * 65 + "\n"
            "  FULL DETAILED REPORT BELOW\n"
            "=" * 65 + "\n\n"
        )

        success = send_email(subject, header + report_body)
        if success:
            logger.info("[EMAIL] Backtest results email bhej diya!")
        else:
            logger.warning("[EMAIL] Email nahi bheja ja saka (credentials check karo).")

    except Exception as e:
        logger.error(f"[EMAIL] Email bhejte waqt error: {e}")
        logger.info("  (Report file GitHub Artifacts mein available hai.)")


if __name__ == "__main__":
    main()