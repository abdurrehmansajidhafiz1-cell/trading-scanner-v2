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

        touched = zone["status"] == "ACTIVE"
        touched_at = zone.get("touched_at")
        resolved = False
        be_moved = False
        current_stop = zone["stop_price"]

        # CRITICAL BUG FIX: If trade is already ACTIVE, evaluate ONLY candles AFTER entry touched_at
        if touched and touched_at:
            touched_at_ts = pd.Timestamp(touched_at)
            if touched_at_ts.tzinfo is None:
                touched_at_ts = touched_at_ts.tz_localize("UTC")
            relevant_candles = df[df["timestamp"] > touched_at_ts].reset_index(drop=True)
        else:
            relevant_candles = df[df["timestamp"] > created_at_ts].reset_index(drop=True)

        be_ratio = getattr(config, "BREAKEVEN_TRIGGER_RATIO", 0.55)
        fee_rate = getattr(config, "BINANCE_FEE_PCT", 0.075) / 100.0
        pkr_rate = getattr(config, "USDT_PKR_RATE", 280.0)

        # Dual-Tier Entry Support (61.8% Golden Pocket & 78.6% OTE)
        tier1_price = zone.get("entry_1") or zone["entry_price"]
        tier2_price = zone.get("entry_2") or zone["entry_price"]
        tol_pct = tf_cfg["zone_tolerance_pct"] / 100

        tier1_threshold = tier1_price * (1 + tol_pct)
        tier2_threshold = tier2_price * (1 + tol_pct)

        fill_type = zone.get("fill_type") or "SINGLE_618"
        capital_allocated = float(zone.get("capital_allocated") or 50.0)
        sold_pct = float(zone.get("sold_pct") or 0.0)

        effective_entry = zone["entry_price"]
        if fill_type == "DOUBLE_618_786":
            effective_entry = (tier1_price + tier2_price) / 2.0
        elif tier1_price:
            effective_entry = tier1_price

        be_trigger = effective_entry + (zone["target_price"] - effective_entry) * be_ratio
        has_touched_zone = False

        for idx, candle in relevant_candles.iterrows():
            candle_ts_str = str(candle["timestamp"])

            # Step 1: Wait for price to touch Entry Zone (Tier 1: 61.8% or Tier 2: 78.6%)
            # and confirm with a green reversal candle
            if not touched:
                swing_high = zone.get("swing_high")
                if getattr(config, "ENABLE_BREAKOUT_EXPIRY", True) and swing_high and candle["high"] > (swing_high * 1.002):
                    db.update_zone_status(zone["id"], "EXPIRED", resolved_at=candle_ts_str)
                    resolved = True
                    break

                touched_tier1 = candle["low"] <= tier1_threshold
                touched_tier2 = candle["low"] <= tier2_threshold

                if touched_tier2:
                    has_touched_zone = True
                    fill_type = "DOUBLE_618_786"
                    capital_allocated = 100.0
                    effective_entry = (tier1_price + tier2_price) / 2.0
                elif touched_tier1 and getattr(config, "ENABLE_DUAL_TIER_ENTRY", True):
                    has_touched_zone = True
                    fill_type = "SINGLE_618"
                    capital_allocated = 50.0
                    effective_entry = tier1_price

                if has_touched_zone:
                    if candle["low"] <= current_stop:
                        db.update_zone_status(zone["id"], "EXPIRED", resolved_at=candle_ts_str)
                        resolved = True
                        break

                    if candle["close"] > candle["open"]:
                        touched = True
                        touched_at = candle_ts_str
                        be_trigger = effective_entry + (zone["target_price"] - effective_entry) * be_ratio
                        db.update_zone_status(zone["id"], "ACTIVE", touched_at=touched_at)
                        db.update_zone_position(zone["id"], fill_type=fill_type, capital_allocated=capital_allocated, sold_pct=0.0)

                continue

            # Step 2: Trade is ACTIVE -> Track Breakeven, Take-Profit (TP1 & TP2), and Stop-Loss
            if touched:
                # Agar trade SINGLE_618 par active hui thi aur baad mein Tier 2 dip kiya (before BE)
                if fill_type == "SINGLE_618" and candle["low"] <= tier2_threshold and not be_moved:
                    fill_type = "DOUBLE_618_786"
                    capital_allocated = 100.0
                    effective_entry = (tier1_price + tier2_price) / 2.0
                    be_trigger = effective_entry + (zone["target_price"] - effective_entry) * be_ratio
                    db.update_zone_position(zone["id"], fill_type=fill_type, capital_allocated=capital_allocated)

                # 55% Breakeven SL Activation
                if getattr(config, "ENABLE_BREAKEVEN_SL", True) and not be_moved:
                    if candle["high"] >= be_trigger:
                        be_moved = True
                        current_stop = effective_entry * (1.0 + fee_rate)
                        if not zone.get("is_be_alert_sent"):
                            from reporting import send_be_hit_alert
                            send_be_hit_alert(zone, fill_type, capital_allocated)
                            db.mark_zone_alert_stage(zone["id"], "is_be_alert_sent")
                            zone["is_be_alert_sent"] = 1
                        sold_pct = max(sold_pct, 50.0)
                        db.update_zone_position(zone["id"], sold_pct=sold_pct)

                tp1_target = zone.get("tp1_price") or zone["target_price"]
                tp2_target = zone.get("tp2_price") or (zone["target_price"] * 1.05)

                # Target 1 (TP1) Check
                if candle["high"] >= tp1_target and not zone.get("is_tp1_alert_sent"):
                    from reporting import send_tp1_hit_alert
                    send_tp1_hit_alert(zone, fill_type, capital_allocated)
                    db.mark_zone_alert_stage(zone["id"], "is_tp1_alert_sent")
                    zone["is_tp1_alert_sent"] = 1
                    sold_pct = max(sold_pct, 80.0)
                    db.update_zone_position(zone["id"], sold_pct=sold_pct)

                # Target 2 (TP2) Full Exit Check
                if candle["high"] >= tp2_target:
                    if not zone.get("is_tp2_alert_sent"):
                        from reporting import send_tp2_hit_alert
                        send_tp2_hit_alert(zone, fill_type, capital_allocated)
                        db.mark_zone_alert_stage(zone["id"], "is_tp2_alert_sent")
                        zone["is_tp2_alert_sent"] = 1

                    c_total = capital_allocated / effective_entry if effective_entry > 0 else 0.0
                    rev = (c_total * 0.50 * be_trigger) + (c_total * 0.30 * tp1_target) + (c_total * 0.20 * tp2_target)
                    fees = (capital_allocated + rev) * fee_rate
                    net_usd = rev - capital_allocated - fees
                    net_pkr = net_usd * pkr_rate

                    if not zone.get("is_closed_alert_sent"):
                        from reporting import send_trade_closed_alert
                        send_trade_closed_alert(zone, "FULL_TP2_WIN", net_usd, net_pkr)
                        db.mark_zone_alert_stage(zone["id"], "is_closed_alert_sent")
                        zone["is_closed_alert_sent"] = 1

                    db.update_zone_position(zone["id"], sold_pct=100.0, realized_pnl_usd=net_usd, realized_pnl_pkr=net_pkr)
                    db.update_zone_status(zone["id"], "WIN", touched_at=touched_at, resolved_at=candle_ts_str)
                    resolved = True
                    break

                # Stop-Loss or Reversal to Entry SL Check
                elif candle["low"] <= current_stop:
                    c_total = capital_allocated / effective_entry if effective_entry > 0 else 0.0
                    if be_moved:
                        if zone.get("is_tp1_alert_sent"):
                            rev = (c_total * 0.50 * be_trigger) + (c_total * 0.30 * tp1_target) + (c_total * 0.20 * current_stop)
                            outcome = "TP1_THEN_BE"
                            status = "WIN"
                        else:
                            rev = (c_total * 0.50 * be_trigger) + (c_total * 0.50 * current_stop)
                            outcome = "BREAK_EVEN"
                            status = "BREAKEVEN"
                        fees = (capital_allocated + rev) * fee_rate
                        net_usd = rev - capital_allocated - fees
                        net_pkr = net_usd * pkr_rate
                    else:
                        rev = c_total * current_stop
                        fees = (capital_allocated + rev) * fee_rate
                        net_usd = rev - capital_allocated - fees
                        net_pkr = net_usd * pkr_rate
                        outcome = "STOP_LOSS"
                        status = "LOSS"
                        candles_after_sl = relevant_candles.iloc[idx + 1: idx + 20]
                        diag = diagnose_trade_outcome(zone, candles_after_sl)
                        if diag.get("post_sl_behavior"):
                            db.update_zone_post_sl_info(zone["id"], diag["post_sl_behavior"], diag["post_sl_details"])

                    if not zone.get("is_closed_alert_sent"):
                        from reporting import send_trade_closed_alert
                        send_trade_closed_alert(zone, outcome, net_usd, net_pkr)
                        db.mark_zone_alert_stage(zone["id"], "is_closed_alert_sent")
                        zone["is_closed_alert_sent"] = 1

                    db.update_zone_position(zone["id"], sold_pct=100.0, realized_pnl_usd=net_usd, realized_pnl_pkr=net_pkr)
                    db.update_zone_status(zone["id"], status, touched_at=touched_at, resolved_at=candle_ts_str)
                    resolved = True
                    break

        if resolved:
            continue

        # Strict 24-hour timeout & expiry limit (30m: 48 bars, 1h: 24 bars, 4h: 6 bars)
        max_holding_hours = getattr(config, "MAX_HOLDING_HOURS", 24)
        hours_to_bars = {"30m": int(max_holding_hours * 2), "1h": int(max_holding_hours), "4h": max(1, int(max_holding_hours / 4))}
        age_limit = hours_to_bars.get(timeframe, 24)

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


def reconcile_historical_zones(exchange):
    """
    Past database zones ko clean historical OHLCV data ke sath re-evaluate karta hai
    taake purani reports ka timing bug 100% correct ho jaye.
    """
    all_zones = db.get_all_zones()
    if not all_zones:
        return

    logger.info(f"Reconciling {len(all_zones)} historical zones for timing accuracy...")
    for zone in all_zones:
        # Reset to pending temporarily for clean re-evaluation
        db.update_zone_status(zone["id"], "PENDING", touched_at=None, resolved_at=None)
        resolve_pending_zones(exchange, zone["coin"], zone["timeframe"])


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
            # 1. Daily Zone Cap Check (Max 3 per day)
            today_str = str(candle_time)[:10]
            if getattr(config, "ENABLE_DAILY_ZONE_CAP", True):
                daily_count = db.get_daily_zone_count(today_str)
                max_daily = getattr(config, "MAX_SAME_DAY_ZONES", 3)
                if daily_count >= max_daily:
                    result.qualifies = False
                    result.reject_reason_code = "DAILY_ZONE_CAP_REACHED"
                    result.reject_reason_detail = f"Aaj ke din ki maximum {max_daily} trades poori ho chuki hain (Daily Cap)"

            # 2. Daily Circuit Breaker Check (Max 2 losses per day)
            if result.qualifies and getattr(config, "ENABLE_DAILY_CIRCUIT_BREAKER", True):
                loss_count = db.get_daily_realized_loss_count(today_str)
                if loss_count >= 2:
                    result.qualifies = False
                    result.reject_reason_code = "DAILY_CIRCUIT_BREAKER_TRIGGERED"
                    result.reject_reason_detail = f"Aaj {loss_count} losses hone ki wajah se Circuit Breaker active hai — trading paused for today"

            # 3. Max Concurrent Active Trades Check (Anti-Correlation Guard)
            if result.qualifies:
                active_count = db.get_active_zones_count()
                max_active = getattr(config, "MAX_ACTIVE_TRADES", 3)
                if active_count >= max_active:
                    result.qualifies = False
                    result.reject_reason_code = "MAX_ACTIVE_TRADES_REACHED"
                    result.reject_reason_detail = f"Portfolio par pehle se {active_count} trades active hain (Max {max_active} allowed) — correlation risk defense"

            # 4. Consecutive Loss Pause Check
            if result.qualifies and getattr(config, "ENABLE_CONSEC_LOSS_PAUSE", True):
                consec_losses = db.get_recent_consecutive_losses()
                max_consec = getattr(config, "MAX_CONSEC_LOSSES_BEFORE_PAUSE", 3)
                if consec_losses >= max_consec:
                    result.qualifies = False
                    result.reject_reason_code = "CONSEC_LOSS_PAUSE"
                    result.reject_reason_detail = f"{consec_losses} consecutive losses ke baad cooling period active hai"

        if result.qualifies:
            already_recorded = prev_state and prev_state["last_recorded_zone_price"] == result.best_zone_price
            structure_after_start = result.structure_created_at and result.structure_created_at >= start_datetime

            if not already_recorded and structure_after_start:
                zone_id = db.insert_zone(
                    coin=coin, timeframe=timeframe, level_name=result.best_zone_name,
                    entry_price=result.best_zone_price, stop_price=result.stop_price,
                    target_price=result.target_price, swing_low=result.swing_low,
                    swing_high=result.swing_high, score=result.best_score,
                    actual_rr=result.actual_rr, pivot_len=result.pivot_len,
                    created_at=result.structure_created_at, score_breakdown=result.score_breakdown,
                    entry_1=result.entry_1, entry_2=result.entry_2, tp1_price=result.tp1_price,
                    tp2_price=result.tp2_price,
                )
                qualified_count += 1
                logger.info(f"NAYA ZONE: {coin} [{timeframe}] {result.best_zone_name} "
                            f"@ {result.best_zone_price:.4f} (Tier1: {result.entry_1:.4f}, Tier2: {result.entry_2:.4f}), "
                            f"score {result.best_score}, R:R 1:{result.actual_rr:.2f} (candle: {checked_at})")

                # Instant email alerts sirf latest live candle par jane chahiye
                is_latest_candle = (i == new_indices[-1])
                if getattr(config, "ENABLE_INSTANT_ALERTS", True) and is_latest_candle:
                    from reporting import send_zone_created_alert, send_instant_signal_alert
                    zone_dict = {
                        "id": zone_id, "coin": coin, "timeframe": timeframe,
                        "level_name": result.best_zone_name, "entry_price": result.best_zone_price,
                        "stop_price": result.stop_price, "target_price": result.target_price,
                        "swing_low": result.swing_low, "swing_high": result.swing_high,
                        "score": result.best_score, "actual_rr": result.actual_rr,
                        "pivot_len": result.pivot_len, "created_at": result.structure_created_at,
                        "score_breakdown": result.score_breakdown, "entry_1": result.entry_1,
                        "entry_2": result.entry_2, "tp1_price": result.tp1_price,
                        "tp2_price": result.tp2_price,
                    }
                    # 1. Zone Created Alert
                    created_sent = send_zone_created_alert(zone_dict)
                    if created_sent:
                        db.mark_zone_alert_stage(zone_id, "is_created_alert_sent")
                        logger.info(f"Zone created alert sent for {coin} [{timeframe}]!")

                    # 2. Trade Signal Alert (10 Scenarios Playbook)
                    sent = send_instant_signal_alert(zone_dict)
                    if sent:
                        db.mark_zone_alert_sent(zone_id)
                        logger.info(f"Instant trade signal alert sent for {coin} [{timeframe}]!")
                    else:
                        from engine.signal_queue import push_signal
                        push_signal(zone_dict)
                        logger.warning(f"Instant alert dispatch failed or pending. Pushed {coin} [{timeframe}] to persistent retry queue.")

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

    # One-time auto-reconciliation of past historical zones to fix timestamps
    if not db.get_config("historical_reconciled_v2"):
        try:
            reconcile_historical_zones(exchange)
            db.set_config("historical_reconciled_v2", "true")
            logger.info("Historical zones reconciled successfully with accurate timestamps!")
        except Exception as e:
            logger.warning(f"Historical reconciliation error: {e}")

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

    # Step 4-PRE: Process persistent signal queue first
    try:
        from engine.signal_queue import process_pending_signals
        executed_queued = process_pending_signals(exchange)
        if executed_queued:
            logger.info(f"Signal queue processed: {len(executed_queued)} setup(s) executed successfully.")
    except Exception as e_queue:
        logger.warning(f"Error processing pending signal queue: {e_queue}")

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
