"""
Signal Queue — Persistent File-backed Queue (`data/pending_signals.json`).
Agar closed candle par strategy qualify kare lekin alert/execution transient network hiccup,
broker busy ya rate-limit ki wajah se issue kare, to signal yahan persist hota hai
aur aglay scan cycle ke shuru mein automatically evaluate hokar execute hota hai.
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("trading_scanner")

QUEUE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "pending_signals.json")


def _ensure_queue_dir():
    folder = os.path.dirname(QUEUE_FILE)
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)


def load_queue() -> list:
    _ensure_queue_dir()
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Signal queue load error: {e}")
        return []


def save_queue(queue: list):
    _ensure_queue_dir()
    try:
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2)
    except Exception as e:
        logger.error(f"Signal queue save error: {e}")


def push_signal(signal_dict: dict):
    queue = load_queue()
    # Check if duplicate already in queue
    for item in queue:
        if item.get("coin") == signal_dict.get("coin") and item.get("timeframe") == signal_dict.get("timeframe") and item.get("created_at") == signal_dict.get("created_at"):
            return
    queue.append(signal_dict)
    save_queue(queue)
    logger.info(f"Signal queued for retry: {signal_dict.get('coin')} [{signal_dict.get('timeframe')}]")


def process_pending_signals(exchange, current_prices: dict = None) -> list:
    """
    Step 4-PRE: Scan cycle ke bilkul shuru mein queued signals ko evaluate karta hai.
    Agar signal valid hai aur price entry zone mein hai:
      - DB mein zone insert karta hai
      - Instant email alert dispatch karta hai
      - Queue se discard ya mark complete karta hai
    """
    queue = load_queue()
    if not queue:
        return []

    remaining = []
    executed = []
    now = datetime.now(timezone.utc)

    import database as db
    import config

    for sig in queue:
        coin = sig.get("coin")
        timeframe = sig.get("timeframe")
        entry_price = sig.get("entry_price", 0.0)
        stop_price = sig.get("stop_price", 0.0)
        tp1_price = sig.get("tp1_price", sig.get("target_price", 0.0))
        tp2_price = sig.get("tp2_price", 0.0)
        queued_at_str = sig.get("queued_at")

        # 1. Max Age Check (>2h for 30m, >12h for 1h/4h)
        max_hours = 2 if timeframe == "30m" else 12
        if queued_at_str:
            try:
                queued_at = datetime.fromisoformat(queued_at_str)
                if (now - queued_at) > timedelta(hours=max_hours):
                    logger.info(f"[QUEUE EXPIRED] Discarding {coin} [{timeframe}] — exceeded max age {max_hours}h.")
                    continue
            except Exception:
                pass

        # 2. Get current market price
        curr_price = None
        if current_prices and coin in current_prices:
            curr_price = current_prices[coin]
        else:
            try:
                t = exchange.fetch_ticker(coin)
                curr_price = t.get("last")
            except Exception as ex_t:
                logger.warning(f"Could not fetch current price for queued {coin}: {ex_t}")

        if curr_price is None or curr_price <= 0:
            remaining.append(sig)
            continue

        # 3. Breach Checks
        # Price already hit SL or TP1/TP2?
        if curr_price <= stop_price:
            logger.info(f"[QUEUE DISCARD] {coin} [{timeframe}] already breached Stop Loss ({curr_price} <= {stop_price}).")
            continue

        if curr_price >= tp1_price:
            logger.info(f"[QUEUE DISCARD] {coin} [{timeframe}] already hit Target TP1 ({curr_price} >= {tp1_price}).")
            continue

        # Price over-extended past entry by > 2%?
        if curr_price > entry_price * 1.02:
            logger.info(f"[QUEUE DISCARD] {coin} [{timeframe}] over-extended past entry by >2% ({curr_price} > {entry_price * 1.02:.4f}).")
            continue

        # 4. In Entry Zone -> Execute Immediately!
        logger.info(f"[QUEUE BUY] Executing queued setup for {coin} [{timeframe}] @ {curr_price:.4f} (Entry: {entry_price:.4f})")
        zone_id = db.insert_zone(
            coin=coin, timeframe=timeframe, level_name=sig.get("level_name", "78.6% OTE"),
            entry_price=entry_price, stop_price=stop_price,
            target_price=sig.get("target_price", tp1_price), swing_low=sig.get("swing_low"),
            swing_high=sig.get("swing_high"), score=sig.get("score", 85),
            actual_rr=sig.get("actual_rr", 1.5), pivot_len=sig.get("pivot_len", 5),
            created_at=sig.get("created_at"), score_breakdown=sig.get("score_breakdown"),
            entry_1=sig.get("entry_1", entry_price), entry_2=sig.get("entry_2", entry_price),
            tp1_price=tp1_price, tp2_price=tp2_price,
        )

        if getattr(config, "ENABLE_INSTANT_ALERTS", True):
            try:
                from reporting import send_instant_signal_alert
                zone_dict = dict(sig)
                zone_dict["id"] = zone_id
                send_instant_signal_alert(zone_dict)
            except Exception as e_alert:
                logger.error(f"Error dispatching instant alert for queued zone {zone_id}: {e_alert}")

        executed.append(sig)

    save_queue(remaining)
    return executed
