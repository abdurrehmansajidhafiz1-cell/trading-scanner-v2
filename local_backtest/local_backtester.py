"""
local_backtester.py — 1-Year Continuous Historical Backtest Engine.

Bug fix vs. the original hist_backtester.py (used by the 5-year GitHub
version): that engine called backtest_single_coin_month() separately for
each month with swing state reset to None at the start of every month
(only last_recorded_zone_price carried over, and only if truthy). That
does NOT match how the live scanner behaves — live scanner keeps one
continuous swing_state per (coin, timeframe) in the database forever, and
NEVER resets it at arbitrary calendar boundaries.

This engine instead runs ONE continuous candle-by-candle replay across the
full backtest window per (coin, timeframe) — exactly mirroring
scanner.py's process_coin_timeframe() state handling (prev_state read
before analyze(), state written after every candle where a swing
high/low is known). Months are only used afterwards to bucket the
resulting zones for reporting — they never affect the replay itself.

Zero look-ahead bias: every candle only ever sees data up to and including
itself (df_slice = df_main.iloc[:abs_idx+1]).
"""

import sys
import os
import logging
from collections import defaultdict

import pandas as pd
import numpy as np

# Parent directory ko sys.path mein add karo taake signal_engine import ho sake
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signal_engine import analyze

logger = logging.getLogger("local_backtest")


def _truncate_to(df: pd.DataFrame, cutoff_time) -> pd.DataFrame:
    """Look-ahead bias prevention: sirf cutoff_time tak ki candles rakhta hai."""
    if df is None:
        return None
    return df[df["timestamp"] <= cutoff_time].reset_index(drop=True)


def _classify_month_market(df_daily: pd.DataFrame) -> str:
    """Month ke overall market condition classify karta hai (Bull/Bear/Sideways)."""
    if df_daily is None or len(df_daily) < 5:
        return "UNKNOWN"
    start_price = df_daily["close"].iloc[0]
    end_price = df_daily["close"].iloc[-1]
    change_pct = (end_price - start_price) / start_price * 100
    if change_pct > 10:
        return "STRONG BULL"
    elif change_pct > 3:
        return "BULL"
    elif change_pct < -10:
        return "STRONG BEAR"
    elif change_pct < -3:
        return "BEAR"
    else:
        return "SIDEWAYS / CONSOLIDATION"


def _resolve_zone(zone: dict, df_after_entry: pd.DataFrame, tf_cfg: dict) -> dict:
    """
    Zone ko Dual-Tier Entry (61.8% + 78.6%) aur Partial TP1 + Breakeven ke against test karta hai.
    1. Tier 1 (61.8%): 50% position fill.
    2. Tier 2 (78.6%): 50% position fill (dono fill hon to avg price ~70.2% Fib).
    3. Partial TP1 (50% distance): 50% profit booked + SL shifts to Entry (Risk-Free).
    4. TP2 (100% Target): Final target execution.
    """
    import config
    swing_low = zone["swing_low"]
    swing_high = zone["swing_high"]
    diff = swing_high - swing_low

    entry_1 = zone.get("entry_1") or (swing_high - 0.618 * diff)
    entry_2 = zone.get("entry_2") or (swing_high - 0.786 * diff)
    tp1 = zone.get("tp1_price") or (swing_low + 0.50 * diff)
    tp2 = zone["target_price"]

    zone["entry_1"] = entry_1
    zone["entry_2"] = entry_2
    zone["tp1_price"] = tp1

    current_stop = zone["stop_price"]
    age_limit = tf_cfg["max_structure_age_bars"] * 3
    tol = tf_cfg["zone_tolerance_pct"] / 100

    tier1_filled = False
    tier2_filled = False
    active_entry = None
    touched_at = None
    tp1_hit = False

    min_before_touch = float("inf")
    max_before_touch = float("-inf")
    max_trade_high = float("-inf")

    for idx, (_, candle) in enumerate(df_after_entry.iterrows()):
        candle_low = candle["low"]
        candle_high = candle["high"]
        candle_open = candle["open"]
        candle_close = candle["close"]
        candle_ts = str(candle["timestamp"])

        is_green = candle_close > candle_open

        # --- Phase A: Entry Evaluation (Dual-Tier) ---
        if not tier1_filled:
            min_before_touch = min(min_before_touch, candle_low)
            max_before_touch = max(max_before_touch, candle_high)

            # Check Tier 1 Touch (61.8%)
            if candle_low <= entry_1 * (1 + tol):
                if candle_low <= current_stop:
                    # Invalidation before confirmation
                    zone["status"] = "EXPIRED"
                    zone["resolved_at"] = candle_ts
                    zone["diagnosis"] = "Invalidated: Price crashed below Stop Loss before bullish green confirmation."
                    return zone

                if is_green:
                    tier1_filled = True
                    active_entry = entry_1
                    touched_at = candle_ts
                    zone["touched_at"] = touched_at
                    max_trade_high = candle_high

        # If already Tier 1 filled, check if Tier 2 (78.6%) also fills on this candle
        if tier1_filled and not tier2_filled:
            if candle_low <= entry_2 * (1 + tol):
                tier2_filled = True
                active_entry = (entry_1 + entry_2) / 2.0  # Average price of both tiers

        # --- Phase B: In-Trade Management (TP1, TP2, Breakeven, SL) ---
        if tier1_filled:
            max_trade_high = max(max_trade_high, candle_high)

            # 1. Partial TP1 Trigger (50% target distance hit)
            if not tp1_hit and candle_high >= tp1:
                tp1_hit = True
                current_stop = active_entry  # Breakeven SL active

            # 2. Final TP2 Trigger (Full Target Hit)
            if candle_high >= tp2:
                zone["status"] = "WIN"
                zone["resolved_at"] = candle_ts
                allocation_pct = 100 if tier2_filled else 50
                risk_amt = active_entry - zone["stop_price"]
                reward_amt = tp2 - active_entry
                tier_rr = (reward_amt / risk_amt) if risk_amt > 0 else zone.get("actual_rr", 1.5)
                final_rr = tier_rr if tier2_filled else (tier_rr * 0.5)
                zone["actual_rr"] = round(final_rr, 2)
                zone["diagnosis"] = (
                    f"Clean Dual-Tier Win ({allocation_pct}% Size): Reached Target {tp2:.4f} "
                    f"(+{final_rr:.2f}R Net Profit | Avg Entry: {active_entry:.4f})."
                )
                return zone

            # 3. Stop Loss / Breakeven Trigger
            if candle_low <= current_stop:
                if tp1_hit:
                    zone["status"] = "BREAKEVEN"
                    zone["resolved_at"] = candle_ts
                    risk_amt = active_entry - zone["stop_price"]
                    reward_tp1 = tp1 - active_entry
                    tp1_r = (reward_tp1 / risk_amt * 0.5) if risk_amt > 0 else 0.5
                    zone["actual_rr"] = round(tp1_r, 2)
                    zone["diagnosis"] = (
                        f"Partial Profit + Breakeven (+{tp1_r:.2f}R): TP1 hit at {tp1:.4f} (50% profit booked), "
                        f"remaining 50% closed at Entry Breakeven ({active_entry:.4f})."
                    )
                    return zone
                else:
                    zone["status"] = "LOSS"
                    zone["resolved_at"] = candle_ts
                    loss_r = -1.0 if tier2_filled else -0.5  # Only 50% loss if only Tier 1 filled
                    zone["actual_rr"] = loss_r
                    try:
                        from failure_analyzer import diagnose_trade_outcome
                        candles_after_sl = df_after_entry.iloc[idx + 1: idx + 25]
                        diag = diagnose_trade_outcome(zone, candles_after_sl)
                        zone["post_sl_behavior"] = diag.get("post_sl_behavior")
                        zone["post_sl_details"] = diag.get("post_sl_details")
                        zone["diagnosis"] = diag.get("post_sl_details") or "Price crashed below Stop Loss."
                    except Exception:
                        zone["diagnosis"] = "SL hit: price dumped below structural stop loss."
                    return zone

        # --- Phase C: Age Limit Check ---
        if idx > age_limit:
            if not tier1_filled:
                zone["status"] = "EXPIRED"
                zone["resolved_at"] = candle_ts
                if min_before_touch <= entry_1:
                    zone["diagnosis"] = (
                        f"Missed Dip (Shallow Pullback): Price dipped to {min_before_touch:.4f} but lacked green confirmation."
                    )
                else:
                    zone["diagnosis"] = f"Impulse Rally: Price moved up without pullback to 61.8% Fib (Lowest: {min_before_touch:.4f})."
                if max_before_touch >= tp2:
                    zone["diagnosis"] += f" Target ({tp2:.4f}) was hit during impulse."
            else:
                zone["status"] = "TIMEOUT"
                zone["resolved_at"] = candle_ts
                zone["diagnosis"] = f"Timeout: Position stayed active for {age_limit} bars without hitting TP or SL."
            return zone

    zone["status"] = "PENDING"
    zone["resolved_at"] = None
    zone["diagnosis"] = "Pending: Zone currently open, awaiting entry or target resolution."
    return zone


def backtest_coin_timeframe_period(
    df_main: pd.DataFrame,
    df_daily: pd.DataFrame,
    df_intermediate: pd.DataFrame | None,
    df_btc_1h: pd.DataFrame | None,
    df_btc_daily: pd.DataFrame | None,
    coin: str,
    timeframe: str,
    period_start,
    period_end,
    tf_cfg: dict,
) -> list[dict]:
    """
    Ek coin/timeframe ka poora backtest window ek hi CONTINUOUS pass mein
    chalata hai (bilkul live scanner.process_coin_timeframe() jaisa).

    df_main should already include a WARMUP buffer of candles before
    period_start (so indicators/swing structure are already "warmed up" by
    the time period_start arrives) and should extend far enough past
    period_end that late-window zones have a real chance to resolve.

    Returns: list of zone dicts whose structure_created_at falls inside
    [period_start, period_end) — matching the live system's start_datetime
    gate, just with period_start playing that role instead.
    """
    if len(df_main) < 100:
        return []

    period_start_ts = pd.Timestamp(period_start)
    period_end_ts = pd.Timestamp(period_end)

    # We only need to RUN the replay up to period_end — no point generating
    # signals for candles after that (nothing after period_end should count).
    candles_to_process = df_main[df_main["timestamp"] < period_end_ts]
    if len(candles_to_process) < 100:
        return []

    zones_found = []
    swing_state = None  # in-memory equivalent of db.get_swing_state/set_swing_state — carried continuously

    for abs_idx in range(99, len(candles_to_process)):
        candle_time = df_main["timestamp"].iloc[abs_idx]

        start_slice = max(0, abs_idx - 299)
        df_slice = df_main.iloc[start_slice: abs_idx + 1].reset_index(drop=True)
        df_daily_slice = _truncate_to(df_daily, candle_time)
        df_inter_slice = _truncate_to(df_intermediate, candle_time) if df_intermediate is not None else None
        df_btc_slice = _truncate_to(df_btc_1h, candle_time) if df_btc_1h is not None else None
        df_btc_daily_slice = _truncate_to(df_btc_daily, candle_time) if df_btc_daily is not None else None

        # Snapshot state BEFORE this candle updates it — needed for the
        # "already_recorded" de-dup check below, exactly like scanner.py
        # reading prev_state from the DB before calling analyze().
        prev_state_snapshot = swing_state

        result = analyze(coin, timeframe, df_slice, df_daily_slice, df_inter_slice, prev_state_snapshot, df_btc_slice, df_btc_daily_slice)

        if result.swing_high is not None and result.swing_low is not None:
            prev_zone_price = prev_state_snapshot["last_recorded_zone_price"] if prev_state_snapshot else None
            new_zone_price = result.best_zone_price if result.qualifies else prev_zone_price
            swing_state = {
                "swing_high": result.swing_high,
                "swing_high_time": result.swing_high_time,
                "swing_low": result.swing_low,
                "swing_low_time": result.swing_low_time,
                "last_recorded_zone_price": new_zone_price,
            }

        if result.qualifies:
            already_recorded = (
                prev_state_snapshot is not None
                and prev_state_snapshot.get("last_recorded_zone_price") == result.best_zone_price
            )
            structure_after_start = (
                result.structure_created_at is not None
                and pd.Timestamp(result.structure_created_at) >= period_start_ts
            )

            if not already_recorded and structure_after_start:
                df_after = df_main.iloc[abs_idx + 1:].reset_index(drop=True)
                zone = {
                    "coin": coin,
                    "timeframe": timeframe,
                    "created_at": str(result.structure_created_at),
                    "entry_price": result.best_zone_price,
                    "stop_price": result.stop_price,
                    "target_price": result.target_price,
                    "swing_low": result.swing_low,
                    "swing_high": result.swing_high,
                    "score": result.best_score,
                    "actual_rr": result.actual_rr,
                    "level_name": result.best_zone_name,
                    "score_breakdown": result.score_breakdown,
                    "status": "PENDING",
                    "touched_at": None,
                    "resolved_at": None,
                }
                zone = _resolve_zone(zone, df_after, tf_cfg)
                zones_found.append(zone)

    return zones_found


def apply_portfolio_protection(all_zones: list[dict]) -> list[dict]:
    """
    Cross-coin Global Portfolio Protection Engine:
    1. Groups all candidate zones across the 20-coin universe by calendar date (YYYY-MM-DD).
    2. Limits daily exposure to MAX_SAME_DAY_ZONES (default 3) highest-quality (score & R:R) setups.
    3. Enforces DAILY_MAX_LOSS_R circuit breaker (-2.0R): stops taking further trades on any date
       once the portfolio has absorbed 2 consecutive losses.
    4. [Improvement 2] MONTHLY_MAX_TRADES cap: bear months mein overtrading ko rok (max 20/month).
    5. [Improvement 3] CONSECUTIVE_LOSS_PAUSE: 3 losses ke baad 36 ghante ka cooling period.
    """
    import config as cfg
    from datetime import datetime, timezone, timedelta

    if not all_zones:
        return []

    enable_cap = getattr(cfg, "ENABLE_DAILY_ZONE_CAP", True)
    max_daily_zones = getattr(cfg, "MAX_SAME_DAY_ZONES", 3)
    enable_breaker = getattr(cfg, "ENABLE_DAILY_CIRCUIT_BREAKER", True)
    max_loss_r = getattr(cfg, "DAILY_MAX_LOSS_R", -2.0)

    # Improvement 2: Monthly Trade Cap
    enable_monthly_cap = getattr(cfg, "ENABLE_MONTHLY_TRADE_CAP", False)
    monthly_max_trades = getattr(cfg, "MONTHLY_MAX_TRADES", 20)

    # Improvement 3: Consecutive Loss Pause
    enable_consec_pause = getattr(cfg, "ENABLE_CONSEC_LOSS_PAUSE", False)
    max_consec_losses = getattr(cfg, "MAX_CONSEC_LOSSES_BEFORE_PAUSE", 3)
    pause_hours = getattr(cfg, "CONSEC_LOSS_PAUSE_HOURS", 36)

    total_cost_pct = (0.075 + 0.04) / 100 * 2

    # Date ke hisaab se group karo
    by_day = defaultdict(list)
    for z in all_zones:
        day_key = str(z["created_at"])[:10]
        by_day[day_key].append(z)

    final_portfolio_zones = []

    # Improvement 2 & 3: Cross-day state tracking
    monthly_trade_count = defaultdict(int)   # month_key -> accepted trade count
    consec_loss_streak = 0                    # global consecutive loss counter
    pause_until: datetime | None = None      # pause end timestamp

    for day_key in sorted(by_day.keys()):
        day_candidates = by_day[day_key]

        # Highest score and highest R:R setups ko priority do
        day_candidates = sorted(
            day_candidates,
            key=lambda z: (z.get("score", 0), z.get("actual_rr", 0)),
            reverse=True
        )

        # Portfolio Daily Zone Cap
        if enable_cap and len(day_candidates) > max_daily_zones:
            day_candidates = day_candidates[:max_daily_zones]

        # Portfolio Daily Circuit Breaker
        if enable_breaker:
            accepted_day_zones = []
            running_day_pnl = 0.0

            # Resolution / Touch sequence ke mutabiq sort
            time_sorted = sorted(
                day_candidates,
                key=lambda z: (z.get("touched_at") or z.get("created_at"))
            )

            for z in time_sorted:
                # ── Improvement 3: Consecutive Loss Pause Check ──────────────
                if enable_consec_pause and pause_until is not None:
                    # zone creation time parse karo
                    z_time_str = str(z.get("created_at", ""))
                    try:
                        z_ts = pd.Timestamp(z_time_str)
                        if z_ts.tzinfo is None:
                            z_ts = z_ts.tz_localize("UTC")
                        z_dt = z_ts.to_pydatetime()
                    except Exception:
                        z_dt = pause_until  # safe fallback: still within pause

                    if z_dt < pause_until:
                        # Pause period mein hai — yeh zone skip
                        continue
                    else:
                        # Pause khatam
                        pause_until = None

                # ── Improvement 2: Monthly Trade Cap Check ───────────────────
                if enable_monthly_cap:
                    month_key = str(z.get("created_at", ""))[:7]
                    if monthly_trade_count[month_key] >= monthly_max_trades:
                        continue  # Is month ka quota full — skip

                if running_day_pnl <= max_loss_r:
                    # Daily circuit breaker triggered
                    continue

                accepted_day_zones.append(z)

                # Monthly count update
                if enable_monthly_cap:
                    month_key = str(z.get("created_at", ""))[:7]
                    monthly_trade_count[month_key] += 1

                # P&L aur streak update karo
                if z["status"] == "WIN":
                    running_day_pnl += z["actual_rr"] - total_cost_pct
                    consec_loss_streak = 0       # win ne streak tod diya
                elif z["status"] == "LOSS":
                    running_day_pnl += -1.0 - total_cost_pct
                    consec_loss_streak += 1
                    # ── Improvement 3: Pause activate karo ─────────────────
                    if enable_consec_pause and consec_loss_streak >= max_consec_losses:
                        z_time_str = str(z.get("resolved_at") or z.get("created_at", ""))
                        try:
                            z_ts = pd.Timestamp(z_time_str)
                            if z_ts.tzinfo is None:
                                z_ts = z_ts.tz_localize("UTC")
                            pause_until = z_ts.to_pydatetime() + timedelta(hours=pause_hours)
                        except Exception:
                            pause_until = None
                        consec_loss_streak = 0   # streak reset
                elif z["status"] == "BREAKEVEN":
                    running_day_pnl += 0.0 - total_cost_pct
                    # Breakeven streak nahi todata, but bhi positive direction
                    consec_loss_streak = 0

            final_portfolio_zones.extend(accepted_day_zones)
        else:
            final_portfolio_zones.extend(day_candidates)

    return sorted(final_portfolio_zones, key=lambda z: z["created_at"])


def compute_metrics(zones: list[dict], fee_pct: float = 0.075, slip_pct: float = 0.04) -> dict:
    """Zones ki list se complete performance metrics calculate karta hai."""
    wins = [z for z in zones if z["status"] == "WIN"]
    losses = [z for z in zones if z["status"] == "LOSS"]
    breakevens = [z for z in zones if z["status"] == "BREAKEVEN"]
    resolved = wins + losses + breakevens

    total_cost_pct = (fee_pct + slip_pct) / 100 * 2  # round-trip

    win_r = sum(z["actual_rr"] - total_cost_pct for z in wins)
    loss_r = sum(-1.0 - total_cost_pct for z in losses)
    be_r = sum(0.0 - total_cost_pct for z in breakevens)
    net_pnl_r = win_r + loss_r + be_r

    win_rate = (len(wins) / len(resolved) * 100) if resolved else 0.0
    profit_factor = (win_r / abs(loss_r)) if abs(loss_r) > 0 else (float("inf") if win_r > 0 else 1.0)

    running_r = 0.0
    peak_r = 0.0
    max_dd = 0.0
    max_consec_wins = max_consec_losses = 0
    streak_w = streak_l = 0

    for z in sorted(zones, key=lambda x: x["created_at"]):
        if z["status"] == "WIN":
            running_r += z["actual_rr"] - total_cost_pct
            streak_w += 1
            streak_l = 0
        elif z["status"] == "LOSS":
            running_r += -1.0 - total_cost_pct
            streak_l += 1
            streak_w = 0
        elif z["status"] == "BREAKEVEN":
            running_r += 0.0 - total_cost_pct

        peak_r = max(peak_r, running_r)
        max_dd = max(max_dd, peak_r - running_r)
        max_consec_wins = max(max_consec_wins, streak_w)
        max_consec_losses = max(max_consec_losses, streak_l)

    return {
        "total_trades": len(zones),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "expired": sum(1 for z in zones if z["status"] == "EXPIRED"),
        "timed_out": sum(1 for z in zones if z["status"] == "TIMEOUT"),
        "pending": sum(1 for z in zones if z["status"] == "PENDING"),
        "win_rate_pct": win_rate,
        "net_pnl_r": net_pnl_r,
        "profit_factor": profit_factor,
        "max_drawdown_r": max_dd,
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
    }


def compute_day_breakdown(zones: list[dict]) -> dict:
    """Zones ko day-by-day breakdown mein aggregate karta hai."""
    day_data = defaultdict(lambda: {"zones": 0, "wins": 0, "losses": 0, "breakevens": 0, "pnl_r": 0.0})
    total_cost_pct = (0.075 + 0.04) / 100 * 2

    for z in zones:
        day_str = str(z["created_at"])[:10]
        day_data[day_str]["zones"] += 1
        if z["status"] == "WIN":
            day_data[day_str]["wins"] += 1
            day_data[day_str]["pnl_r"] += z["actual_rr"] - total_cost_pct
        elif z["status"] == "LOSS":
            day_data[day_str]["losses"] += 1
            day_data[day_str]["pnl_r"] += -1.0 - total_cost_pct
        elif z["status"] == "BREAKEVEN":
            day_data[day_str]["breakevens"] += 1
            day_data[day_str]["pnl_r"] += 0.0 - total_cost_pct

    return dict(sorted(day_data.items()))


def bucket_zones_by_month(zones: list[dict]) -> dict:
    """Zones ko month-key (YYYY-MM) ke hisaab se group karta hai — reporting ONLY, replay isse independent hai."""
    buckets = defaultdict(list)
    for z in zones:
        month_key = str(z["created_at"])[:7]
        buckets[month_key].append(z)
    return dict(sorted(buckets.items()))
