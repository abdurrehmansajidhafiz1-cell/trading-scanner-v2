"""
Scanner — Orchestration Module for Intraday Fibonacci Trading & Backtesting System.
1. Multi-exchange fallback & dynamic Binance liquidity selection
2. Candle-by-candle chronological replay without look-ahead bias
3. BTC Market Regime filter integration
4. Trade resolution (WIN/LOSS/EXPIRED/TIMEOUT) with timestamp parsing fixes
5. Exit code handling for CI/CD integration
"""

import logging
import traceback
import json
import pandas as pd

import config
import database as db
import timezone_utils as tz
from exchange_manager import get_working_exchange, NoExchangeAvailableError
from coin_universe import fetch_top_coins
from data_fetcher import fetch_ohlcv
from signal_engine import analyze

logger = logging.getLogger("trading_scanner")


def get_or_set_start_datetime() -> str:
    stored = db.get_config("system_start_datetime")
    if stored:
        return stored

    if config.SYSTEM_START_DATETIME:
        start_utc = tz.parse_pkt_input(config.SYSTEM_START_DATETIME).isoformat()
    else:
        start_utc = db.now_iso()

    db.set_config("system_start_datetime", start_utc)
    logger.info(f"System start datetime set: {start_utc} (UTC)")
    return start_utc


def resolve_pending_zones(exchange, coin: str, timeframe: str):
    pending = db.get_pending_zones(coin=coin, timeframe=timeframe)
    if not pending:
        return

    df = fetch_ohlcv(exchange, coin, timeframe, limit=config.CANDLES_TO_FETCH)
    if len(df) == 0:
        return

    tf_cfg = config.TF_SETTINGS[timeframe]
    from failure_analyzer import diagnose_trade_outcome

    for zone in pending:
        created_at_ts = pd.Timestamp(zone["created_at"])
        if created_at_ts.tzinfo is None:
            created_at_ts = created_at_ts.tz_localize("UTC")

        relevant_candles = df[df["timestamp"] >= created_at_ts].reset_index(drop=True)
        touched = zone["status"] == "ACTIVE"
        touched_at = zone["touched_at"]
        resolved = False
        lock_stage = 0
        current_stop = zone["stop_price"]

        entry_price = zone["entry_price"]
        target_price = zone["target_price"]
        dist = target_price - entry_price

        lock_t1 = entry_price + (dist * getattr(config, "PROFIT_LOCK_STAGE1_TRIGGER", 0.60))
        lock_p1 = entry_price + (dist * getattr(config, "PROFIT_LOCK_STAGE1_LOCK", 0.25))
        lock_t2 = entry_price + (dist * getattr(config, "PROFIT_LOCK_STAGE2_TRIGGER", 0.80))
        lock_p2 = entry_price + (dist * getattr(config, "PROFIT_LOCK_STAGE2_LOCK", 0.50))
        has_touched_zone = False

        for idx, candle in relevant_candles.iterrows():
            candle_ts_str = str(candle["timestamp"])

            if not touched:
                touch_threshold = entry_price * (1 + tf_cfg["zone_tolerance_pct"] / 100)
                if candle["low"] <= touch_threshold:
                    has_touched_zone = True

                if has_touched_zone:
                    # Agar confirmation se pehle hi stop loss hit ho jaye -> EXPIRED (invalidated)
                    if candle["low"] <= current_stop:
                        db.update_zone_status(zone["id"], "EXPIRED", resolved_at=candle_ts_str)
                        resolved = True
                        break

                    # Reversal Green Candle Confirmation
                    if candle["close"] > candle["open"]:
                        touched = True
                        touched_at = candle_ts_str
                        db.update_zone_status(zone["id"], "ACTIVE", touched_at=touched_at)

            if touched:
                # Dynamic Trailing Profit Lock
                if getattr(config, "ENABLE_PROFIT_LOCK", True):
                    if candle["high"] >= lock_t2:
                        if lock_p2 > current_stop:
                            current_stop = lock_p2
                            lock_stage = 2
                    elif candle["high"] >= lock_t1:
                        if lock_p1 > current_stop:
                            current_stop = lock_p1
                            lock_stage = 1

                if candle["high"] >= target_price:
                    db.update_zone_status(zone["id"], "WIN", touched_at=touched_at, resolved_at=candle_ts_str)
                    resolved = True
                    break
                elif candle["low"] <= current_stop:
                    if lock_stage > 0:
                        db.update_zone_status(zone["id"], "BREAKEVEN", touched_at=touched_at, resolved_at=candle_ts_str)
                    else:
                        db.update_zone_status(zone["id"], "LOSS", touched_at=touched_at, resolved_at=candle_ts_str)
                        # Post-SL Price Action Diagnosis
                        candles_after_sl = relevant_candles.iloc[idx + 1: idx + 20]
                        diag = diagnose_trade_outcome(zone, candles_after_sl)
                        if diag.get("post_sl_behavior"):
                            db.update_zone_post_sl_info(zone["id"], diag["post_sl_behavior"], diag["post_sl_details"])

                    resolved = True
                    break

        if resolved:
            continue

        age_limit = tf_cfg["max_structure_age_bars"] * 3

        if not touched:
            if len(relevant_candles) > age_limit:
                db.update_zone_status(zone["id"], "EXPIRED", resolved_at=db.now_iso())
        else:
            touched_at_ts = pd.Timestamp(touched_at)
            if touched_at_ts.tzinfo is None:
                touched_at_ts = touched_at_ts.tz_localize("UTC")
            candles_since_touch = relevant_candles[relevant_candles["timestamp"] >= touched_at_ts]
            if len(candles_since_touch) > age_limit:
                db.update_zone_status(zone["id"], "TIMEOUT", touched_at=touched_at, resolved_at=db.now_iso())


def _truncate_to(df: pd.DataFrame, cutoff_time) -> pd.DataFrame:
    return df[df["timestamp"] <= cutoff_time].reset_index(drop=True)


def process_coin_timeframe(exchange, coin: str, timeframe: str, start_datetime: str, df_btc: pd.DataFrame | None = None, df_btc_daily: pd.DataFrame | None = None):
    tf_cfg = config.TF_SETTINGS[timeframe]

    df = fetch_ohlcv(exchange, coin, timeframe, limit=config.CANDLES_TO_FETCH)
    if len(df) < 100:
        return 0, 0, []

    df_daily = fetch_ohlcv(exchange, coin, "1d", limit=config.PERCENTILE_LOOKBACK + 60)
    df_intermediate = None
    if tf_cfg["intermediate_tf"]:
        df_intermediate = fetch_ohlcv(exchange, coin, tf_cfg["intermediate_tf"], limit=config.CANDLES_TO_FETCH)

    cursor = db.get_processing_cursor(coin, timeframe)

    if cursor is None:
        new_indices = [len(df) - 1]
    else:
        cursor_ts = pd.Timestamp(cursor)
        if cursor_ts.tzinfo is None:
            cursor_ts = cursor_ts.tz_localize("UTC")
        new_indices = [i for i in range(len(df)) if df["timestamp"].iloc[i] > cursor_ts]
        if not new_indices:
            resolve_pending_zones(exchange, coin, timeframe)
            return 0, 0, []

    qualified_count = 0
    rejected_count = 0
    qualifying = []

    for i in new_indices:
        candle_time = df["timestamp"].iloc[i]
        df_slice = df.iloc[: i + 1].reset_index(drop=True)
        df_daily_slice = _truncate_to(df_daily, candle_time)
        df_intermediate_slice = _truncate_to(df_intermediate, candle_time) if df_intermediate is not None else None
        df_btc_slice = _truncate_to(df_btc, candle_time) if df_btc is not None else None
        df_btc_daily_slice = _truncate_to(df_btc_daily, candle_time) if df_btc_daily is not None else None

        prev_state = db.get_swing_state(coin, timeframe)
        result = analyze(coin, timeframe, df_slice, df_daily_slice, df_intermediate_slice, prev_state, df_btc_slice, df_btc_daily_slice)

        if result.swing_high is not None and result.swing_low is not None:
            prev_zone_price = prev_state["last_recorded_zone_price"] if prev_state else None
            new_zone_price = result.best_zone_price if result.qualifies else prev_zone_price
            db.set_swing_state(
                coin, timeframe,
                result.swing_high, result.swing_high_time,
                result.swing_low, result.swing_low_time,
                new_zone_price,
            )

        checked_at = str(candle_time)

        if result.qualifies:
            already_recorded = prev_state and prev_state["last_recorded_zone_price"] == result.best_zone_price
            structure_after_start = result.structure_created_at and result.structure_created_at >= start_datetime

            if not already_recorded and structure_after_start:
                db.insert_zone(
                    coin=coin, timeframe=timeframe, level_name=result.best_zone_name,
                    entry_price=result.best_zone_price, stop_price=result.stop_price,
                    target_price=result.target_price, swing_low=result.swing_low,
                    swing_high=result.swing_high, score=result.best_score,
                    actual_rr=result.actual_rr, pivot_len=result.pivot_len,
                    created_at=result.structure_created_at, score_breakdown=result.score_breakdown,
                    entry_1=result.entry_1, entry_2=result.entry_2, tp1_price=result.tp1_price,
                )
                qualified_count += 1
                logger.info(f"NAYA ZONE: {coin} [{timeframe}] {result.best_zone_name} "
                            f"@ {result.best_zone_price:.4f} (Tier1: {result.entry_1:.4f}, Tier2: {result.entry_2:.4f}), "
                            f"score {result.best_score}, R:R 1:{result.actual_rr:.2f} (candle: {checked_at})")

            qualifying.append({
                "coin": coin, "timeframe": timeframe, "level": result.best_zone_name,
                "entry": result.best_zone_price, "score": result.best_score, "rr": result.actual_rr,
            })
        elif result.reject_reason_code and result.reject_reason_code not in ("INSUFFICIENT_DATA",):
            is_new_or_changed = db.insert_rejected_zone_deduped(
                coin=coin, timeframe=timeframe, reason_code=result.reject_reason_code,
                reason_detail=result.reject_reason_detail, score=result.best_score,
                actual_rr=result.actual_rr, checked_at=checked_at,
            )
            if is_new_or_changed:
                rejected_count += 1

    db.set_processing_cursor(coin, timeframe, str(df["timestamp"].iloc[new_indices[-1]]))
    resolve_pending_zones(exchange, coin, timeframe)

    return qualified_count, rejected_count, qualifying


def live_check(exchange, coin: str, timeframe: str, df_btc: pd.DataFrame | None = None, df_btc_daily: pd.DataFrame | None = None):
    tf_cfg = config.TF_SETTINGS[timeframe]

    df = fetch_ohlcv(exchange, coin, timeframe, limit=config.CANDLES_TO_FETCH)
    if len(df) < 100:
        return None

    df_daily = fetch_ohlcv(exchange, coin, "1d", limit=config.PERCENTILE_LOOKBACK + 60)
    df_intermediate = None
    if tf_cfg["intermediate_tf"]:
        df_intermediate = fetch_ohlcv(exchange, coin, tf_cfg["intermediate_tf"], limit=config.CANDLES_TO_FETCH)

    return analyze(coin, timeframe, df, df_daily, df_intermediate, None, df_btc, df_btc_daily)


def live_check_all():
    exchange, exchange_id = get_working_exchange()
    logger.info(f"Live check shuru — exchange: {exchange_id}")

    coins = fetch_top_coins(exchange)
    if not coins:
        raise RuntimeError(f"Exchange '{exchange_id}' se coin list khaali mili.")

    df_btc = None
    df_btc_daily = None
    try:
        df_btc = fetch_ohlcv(exchange, "BTC/USDT", "1h", limit=100)
        df_btc_daily = fetch_ohlcv(exchange, "BTC/USDT", "1d", limit=100)
    except Exception as e:
        logger.warning(f"Could not fetch BTC data for regime check: {e}")

    qualifying = []
    for coin in coins:
        for timeframe in config.TIMEFRAMES:
            try:
                result = live_check(exchange, coin, timeframe, df_btc, df_btc_daily)
                if result and result.qualifies:
                    qualifying.append({
                        "coin": coin, "timeframe": timeframe, "level": result.best_zone_name,
                        "entry": result.best_zone_price, "score": result.best_score, "rr": result.actual_rr,
                    })
            except Exception as e:
                logger.error(f"{coin} [{timeframe}]: {type(e).__name__} — {e}")

    return qualifying


def scan_once():
    db.init_db()
    start_datetime = get_or_set_start_datetime()

    exchange, exchange_id = get_working_exchange()
    logger.info(f"Scan shuru — exchange: {exchange_id}")

    coins = fetch_top_coins(exchange)
    if not coins:
        raise RuntimeError(f"Exchange '{exchange_id}' se coin list khaali mili.")

    df_btc = None
    df_btc_daily = None
    try:
        df_btc = fetch_ohlcv(exchange, "BTC/USDT", "1h", limit=100)
        df_btc_daily = fetch_ohlcv(exchange, "BTC/USDT", "1d", limit=100)
    except Exception as e:
        logger.warning(f"BTC data fetch warning: {e}")

    qualifying = []
    zones_qualified_count = 0
    zones_rejected_count = 0
    coin_errors = []
    scan_time = db.now_iso()

    for coin in coins:
        for timeframe in config.TIMEFRAMES:
            try:
                q_count, r_count, q_list = process_coin_timeframe(exchange, coin, timeframe, start_datetime, df_btc, df_btc_daily)
                zones_qualified_count += q_count
                zones_rejected_count += r_count
                qualifying.extend(q_list)
            except Exception as e:
                error_detail = f"{coin} [{timeframe}]: {type(e).__name__} — {e}"
                coin_errors.append(error_detail)
                logger.error(error_detail)

    legacy_combos = [(c, tf) for c, tf in db.get_distinct_pending_coin_timeframes() if c not in coins]
    for coin, timeframe in legacy_combos:
        try:
            resolve_pending_zones(exchange, coin, timeframe)
        except Exception as e:
            error_detail = f"[legacy] {coin} [{timeframe}]: {type(e).__name__} — {e}"
            coin_errors.append(error_detail)

    # Save coin_list in scan_log
    db.insert_scan_log(scan_time, len(coins), zones_qualified_count, zones_rejected_count, coin_list=json.dumps(coins))
    logger.info(f"Scan complete: {len(coins)} coins scanned, {zones_qualified_count} new zones, {zones_rejected_count} rejected.")

    total_checks = len(coins) * len(config.TIMEFRAMES) + len(legacy_combos)
    if total_checks > 0 and len(coin_errors) / total_checks > 0.8:
        raise RuntimeError(
            f"{len(coin_errors)}/{total_checks} checks fail hue — systemic error. Pehla error: {coin_errors[0] if coin_errors else 'N/A'}"
        )

    return qualifying
