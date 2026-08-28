"""
run_realistic_backtest.py -- Realistic Historical Backtest (Optimized: Pre-Compute + Hourly Filter)

ARCHITECTURE (Fast Version):
  OLD (slow): Har 720 hourly slots ke liye har coin ka full scan dobara chalaao
              --> 720 * 15 coins * 2 TFs = ~21,600 full scan calls = 6+ hours

  NEW (fast): Ek baar sab coins ka full month scan karo, zones collect karo
              --> Phir har zone ki created_at timestamp check karo: kya us waqt
                  woh coin hourly dynamic universe mein tha?
              --> 30 coins * 2 TFs = 60 scan calls = ~15-30 minutes

COIN SELECTION LOGIC (same as live system):
  - Har zone ki created_at timestamp ke waqt simulate karo: kaunse coins select hote?
  - Volume > $15M (last 24 x 1H candles se), Volatility 2.5%-12%
  - Sort by volume, top 20
  - Agar zone ka coin us time selected tha -> keep, warna discard

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

# Exact same filters as live system
MIN_24H_VOLUME_USD       = config.MIN_24H_VOLUME_USD        # $15M
MIN_DAILY_VOLATILITY_PCT = config.MIN_DAILY_VOLATILITY_PCT  # 2.5%
MAX_DAILY_VOLATILITY_PCT = config.MAX_DAILY_VOLATILITY_PCT  # 12.0%
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


# ============================================================
# FAST UNIVERSE SIMULATION -- O(1) lookup per zone
# ============================================================
def build_hourly_universe_cache(data_cache, candidate_coins, start_dt, end_dt, top_n=DYNAMIC_UNIVERSE_LIMIT):
    """
    Ek baar sab hourly slots ke liye coin universe pre-compute kar lo.
    Returns: dict { pd.Timestamp -> list[str] }  (hour -> selected coins)

    Yeh sab hourly selections ek hi baar calculate karta hai -- phir
    har zone ke liye O(1) lookup hota hai.
    """
    hourly_slots = pd.date_range(start=start_dt, end=end_dt, freq="1h", tz="UTC")
    hour_to_coins = {}

    logger.info(f"  Pre-computing hourly universe for {len(hourly_slots)} slots...")
    prev_selected = []
    changed_count = 0

    for slot_ts in hourly_slots:
        scored = []
        for coin in candidate_coins:
            if coin in STABLECOIN_SYMBOLS:
                continue
            df_1h = data_cache.get((coin, "1h"))
            if df_1h is None or len(df_1h) < 5:
                continue
            past = df_1h[df_1h["timestamp"] < slot_ts].tail(24)
            if len(past) < 8:
                continue
            vol_usd = float((past["volume"] * past["close"]).sum())
            if vol_usd < MIN_24H_VOLUME_USD:
                continue
            max_h = float(past["high"].max())
            min_l = float(past["low"].min())
            if min_l <= 0:
                continue
            vol_pct = (max_h - min_l) / min_l * 100
            if not (MIN_DAILY_VOLATILITY_PCT <= vol_pct <= MAX_DAILY_VOLATILITY_PCT):
                continue
            scored.append((coin, vol_usd))
        scored.sort(key=lambda x: -x[1])
        selected = [c[0] for c in scored[:top_n]]
        hour_to_coins[slot_ts] = selected

        if selected != prev_selected:
            changed_count += 1
            prev_selected = selected.copy()

    logger.info(f"  Universe cache built. Selection changed {changed_count} times across {len(hourly_slots)} hours.")
    return hour_to_coins


def was_coin_selected_at(hour_to_coins, coin, zone_created_at_str):
    """
    Zone ki created_at timestamp ke waqt kya coin selected tha?
    Zone created_at ko nearest hour pe round karke check karo.
    """
    try:
        ts = pd.Timestamp(zone_created_at_str, tz="UTC") if zone_created_at_str else None
        if ts is None:
            return False
        # Round down to nearest hour
        hour_ts = ts.floor("h")
        selected = hour_to_coins.get(hour_ts, [])
        return coin in selected
    except Exception:
        return False


def main():
    logger.info("=" * 65)
    logger.info("  REALISTIC BACKTEST -- January 2025 (OPTIMIZED)")
    logger.info("  Pre-Compute All Zones, Then Apply Hourly Dynamic Filter")
    logger.info(f"  Period  : {BACKTEST_START.strftime('%Y-%m-%d')} -> {BACKTEST_END.strftime('%Y-%m-%d')}")
    logger.info(f"  Pool    : {len(CANDIDATE_COINS)} coins | Top {DYNAMIC_UNIVERSE_LIMIT}/hour selected")
    logger.info(f"  Filters : Volume > ${MIN_24H_VOLUME_USD/1e6:.0f}M | Volatility {MIN_DAILY_VOLATILITY_PCT}%-{MAX_DAILY_VOLATILITY_PCT}%")
    logger.info(f"  TFs     : {TIMEFRAMES}")
    logger.info("=" * 65)

    exchange, _ = get_working_exchange_local()

    # ── Phase 1: Fetch full history ───────────────────────────────────────────
    logger.info("\n[PHASE 1] Fetching historical candle data...")
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

    # ── Phase 2: Pre-compute hourly universe cache ────────────────────────────
    logger.info("[PHASE 2] Pre-computing hourly dynamic universe cache...")
    start_ts_pd = pd.Timestamp(BACKTEST_START)
    end_ts_pd   = pd.Timestamp(BACKTEST_END)
    hour_to_coins = build_hourly_universe_cache(
        data_cache, CANDIDATE_COINS, start_ts_pd, end_ts_pd
    )

    # Print sample selection on Jan 2 noon
    sample_key = pd.Timestamp("2025-01-02 12:00:00", tz="UTC")
    if sample_key in hour_to_coins:
        logger.info(f"  Sample [Jan 2 12:00 UTC]: {hour_to_coins[sample_key]}")
    logger.info("[PHASE 2 COMPLETE]\n")

    # ── Phase 3: Full month scan -- ek baar har coin/TF ke liye ──────────────
    logger.info("[PHASE 3] Running full-period signal scan for ALL candidate coins...")
    logger.info("  (Ek baar scan, phir hourly filter apply hoga -- much faster!)")

    df_btc_1h    = data_cache.get(("BTC/USDT", "1h_regime"))
    df_btc_daily = data_cache.get(("BTC/USDT", "1d"))

    all_raw_zones = []   # sab zones -- unfiltered

    for coin in CANDIDATE_COINS:
        df_daily = data_cache.get((coin, "1d"))
        for tf in TIMEFRAMES:
            df_main = data_cache.get((coin, tf))
            if df_main is None or len(df_main) == 0:
                continue
            df_inter = data_cache.get((coin, "4h")) if tf == "1h" else None
            try:
                zones = backtest_coin_timeframe_period(
                    df_main=df_main,
                    df_daily=df_daily if df_daily is not None else df_main.head(0),
                    df_intermediate=df_inter,
                    df_btc_1h=df_btc_1h,
                    df_btc_daily=df_btc_daily,
                    coin=coin,
                    timeframe=tf,
                    period_start=BACKTEST_START,
                    period_end=BACKTEST_END,
                    tf_cfg=config.TF_SETTINGS[tf],
                )
                all_raw_zones.extend(zones)
                if zones:
                    logger.info(f"  {coin} [{tf}] -> {len(zones)} zones found")
            except Exception as e:
                logger.warning(f"  Error {coin}[{tf}]: {e}")

    logger.info(f"\n[PHASE 3 COMPLETE] Total raw zones (all coins, unfiltered): {len(all_raw_zones)}")

    # ── Phase 4: Apply hourly dynamic filter ──────────────────────────────────
    logger.info("\n[PHASE 4] Applying hourly dynamic coin selection filter...")
    logger.info("  (Sirf woh zones rakhenge jahan us waqt coin selected tha)")

    filtered_zones = []
    rejected_count = 0

    for zone in all_raw_zones:
        coin       = zone["coin"]
        created_at = zone.get("created_at", "")

        if was_coin_selected_at(hour_to_coins, coin, created_at):
            filtered_zones.append(zone)
        else:
            rejected_count += 1

    logger.info(f"  Zones after hourly filter : {len(filtered_zones)}")
    logger.info(f"  Zones rejected (coin not selected that hour): {rejected_count}")
    logger.info("[PHASE 4 COMPLETE]\n")

    # ── Phase 5: Portfolio protection ────────────────────────────────────────
    logger.info("[PHASE 5] Applying portfolio protection rules...")
    final_zones = apply_portfolio_protection(filtered_zones)
    logger.info(f"  Final zones after protection: {len(final_zones)}")

    month_key   = "2025-01"
    market_type = "UNKNOWN"
    if df_btc_daily is not None and len(df_btc_daily) > 0:
        btc_jan = df_btc_daily[
            (df_btc_daily["timestamp"] >= start_ts_pd) &
            (df_btc_daily["timestamp"] <= end_ts_pd)
        ]
        market_type = _classify_month_market(btc_jan)

    overall_metrics = compute_metrics(final_zones)
    day_breakdown   = compute_day_breakdown(final_zones)
    monthly_metrics = {month_key: overall_metrics}
    monthly_results = [{
        "month_key":      month_key,
        "market_type":    market_type,
        "selected_coins": CANDIDATE_COINS,
        "metrics":        overall_metrics,
        "day_breakdown":  day_breakdown,
        "zones":          final_zones,
    }]

    # ── Phase 6: Report & CSV ─────────────────────────────────────────────────
    logger.info("[PHASE 6] Writing report and CSV...")
    report_path = write_full_report(
        output_dir=OUTPUT_DIR, overall_metrics=overall_metrics,
        monthly_results=monthly_results, monthly_metrics=monthly_metrics,
        all_zones=final_zones, coin_universe=CANDIDATE_COINS,
        timeframes=TIMEFRAMES, start_dt=BACKTEST_START, end_dt=BACKTEST_END,
    )
    write_zones_csv(OUTPUT_DIR, final_zones)
    generic_csv = os.path.join(OUTPUT_DIR, "backtest_zones.csv")
    jan_csv     = os.path.join(OUTPUT_DIR, "jan2025_realistic_zones.csv")
    if os.path.exists(generic_csv):
        os.replace(generic_csv, jan_csv)

    pf     = overall_metrics["profit_factor"]
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

    # ── Phase 7: Email results ────────────────────────────────────────────────
    try:
        sys.path.insert(0, PARENT_DIR)
        from email_sender import send_email
        with open(report_path, "r", encoding="utf-8") as f:
            report_body = f.read()
        subject = (
            f"[Backtest] Jan 2025 Complete | "
            f"WR: {overall_metrics['win_rate_pct']:.1f}% | "
            f"P&L: {overall_metrics['net_pnl_r']:+.2f}R | "
            f"PF: {pf_str} | Regime: {market_type}"
        )
        sep = "-" * 65  # "=" Gmail mein quoted-printable issue karta hai, isliye "-" use karo
        header = "\n".join([
            sep,
            "  BACKTEST COMPLETE -- January 2025",
            "  Hourly Dynamic Coin Selection (Live System Logic Simulated)",
            sep,
            "",
            f"  Market Regime   : {market_type}",
            f"  Total Zones     : {overall_metrics['total_trades']}",
            f"  Wins            : {overall_metrics['wins']}",
            f"  Losses          : {overall_metrics['losses']}",
            f"  Breakevens      : {overall_metrics.get('breakevens', 0)}",
            f"  Expired         : {overall_metrics['expired']}",
            f"  Timed Out       : {overall_metrics['timed_out']}",
            f"  Win Rate        : {overall_metrics['win_rate_pct']:.1f}%",
            f"  Net P&L         : {overall_metrics['net_pnl_r']:+.2f} R",
            f"  Profit Factor   : {pf_str}",
            f"  Max Drawdown    : {overall_metrics['max_drawdown_r']:.2f} R",
            "",
            sep,
            "  FULL DETAILED REPORT BELOW",
            sep,
            "",
        ]) + "\n"
        success = send_email(subject, header + report_body)
        if success:
            logger.info("[EMAIL] Backtest results email bhej diya!")
        else:
            logger.warning("[EMAIL] Email nahi bheja ja saka.")
    except Exception as e:
        logger.error(f"[EMAIL] Error: {e}")
        logger.info("  (Report file GitHub Artifacts mein available hai.)")


if __name__ == "__main__":
    main()