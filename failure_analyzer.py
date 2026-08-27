"""
Failure Analyzer Engine — Automatically diagnoses trade outcomes (Wins & Losses).
Losing trades ko exact physical cause (jaise FALSE_BREAKOUT, BTC_DUMP_IMPACT,
WEAK_MARKET_STRUCTURE, POOR_VOLUME, etc.) tag karta hai.
Winning trades ke top confluence factors ko tag karta hai.
"""

import pandas as pd
import config


def analyze_post_sl_price_action(zone: dict, candle_df: pd.DataFrame | None) -> dict:
    """
    Loss trade ke baad candle price action check karta hai:
    - Kya price sirf SL wick karke wapis pump ho gayi (Wick Sweep Fakeout)?
    - Ya SL break karke continuously cascade dump hoti rahi (Cascade Breakdown)?
    """
    if candle_df is None or len(candle_df) == 0:
        return {
            "behavior": "UNKNOWN",
            "overshoot_pct": 0.0,
            "max_bounce_pct": 0.0,
            "details": "Post-SL candle data unavailable."
        }

    stop_price = zone.get("stop_price") or 0.0
    entry_price = zone.get("entry_price") or 0.0
    target_price = zone.get("target_price") or 0.0

    if stop_price <= 0:
        return {
            "behavior": "UNKNOWN",
            "overshoot_pct": 0.0,
            "max_bounce_pct": 0.0,
            "details": "Invalid stop price."
        }

    min_low_after = float(candle_df["low"].min())
    max_high_after = float(candle_df["high"].max())

    overshoot_pct = max(0.0, (stop_price - min_low_after) / stop_price * 100)
    bounce_from_sl_pct = (max_high_after - stop_price) / stop_price * 100

    # 1. Fakeout check: price hit SL but then rebounded back above entry or towards TP
    rebound_threshold = entry_price + (target_price - entry_price) * 0.50
    if max_high_after >= rebound_threshold or max_high_after >= entry_price:
        behavior = "WICK_SWEEP_FAKEOUT"
        details = (
            f"Price sirf {overshoot_pct:.2f}% SL se neeche wick hui aur phir wapis pump kar ke "
            f"{max_high_after:.4f} tak chali gayi (Entry: {entry_price:.4f}, TP: {target_price:.4f}). "
            f"💡 Insight: Setup direction sahi thi, SL buffer thora tight tha."
        )
    elif min_low_after < stop_price * 0.97:
        # Price dumped > 3% below SL
        behavior = "CASCADE_BREAKDOWN"
        details = (
            f"Price SL break karne ke baad mazeed -{overshoot_pct:.2f}% deep dump ho gayi (Low: {min_low_after:.4f}). "
            f"🛡️ Insight: Stop Loss ne capital ko heavy drawdown se bacha liya."
        )
    else:
        behavior = "SIDEWAYS_DRIFT"
        details = (
            f"Price SL ke aas-paas sideways drift karti rahi (Max Dip: -{overshoot_pct:.2f}%, Max Bounce: +{bounce_from_sl_pct:.2f}%). "
            f"⚠️ Insight: Market mein momentum khatam ho gaya tha."
        )

    return {
        "behavior": behavior,
        "overshoot_pct": overshoot_pct,
        "max_bounce_pct": bounce_from_sl_pct,
        "details": details,
    }


def diagnose_trade_outcome(zone: dict, candle_df: pd.DataFrame | None = None, btc_df: pd.DataFrame | None = None) -> dict:
    """
    Resolved trade (WIN / LOSS / TIMEOUT / EXPIRED) ko analyze kar ke diagnostic tagging metadata return karta hai.
    """
    status = zone.get("status")
    result = {
        "zone_id": zone.get("id"),
        "coin": zone.get("coin"),
        "timeframe": zone.get("timeframe"),
        "status": status,
        "primary_tag": None,
        "detailed_reason": None,
        "post_sl_behavior": None,
        "post_sl_details": None,
        "confluence_tags": [],
    }

    if status == "WIN":
        tags = ["OTE_ZONE_BOUNCE"]
        if zone.get("score", 0) >= 80:
            tags.append("HIGH_CONFLUENCE_80+")
        if zone.get("actual_rr", 0) >= 2.0:
            tags.append("HIGH_RR_2.0+")
        result["primary_tag"] = "SUCCESSFUL_OTE_BOUNCE"
        result["confluence_tags"] = tags
        result["detailed_reason"] = "Trade hit target with strong confluence and valid bullish confirmation."
        return result

    if status == "LOSS":
        post_sl_info = analyze_post_sl_price_action(zone, candle_df)
        result["post_sl_behavior"] = post_sl_info["behavior"]
        result["post_sl_details"] = post_sl_info["details"]

        # 1. BTC Dump Check
        if btc_df is not None and len(btc_df) > 4:
            btc_last = btc_df["close"].iloc[-1]
            btc_prev = btc_df["close"].iloc[-4]
            if (btc_prev - btc_last) / btc_prev * 100 >= config.BTC_MAX_1H_DROP_PCT:
                result["primary_tag"] = "BTC_DUMP_IMPACT"
                result["detailed_reason"] = f"Market-wide BTC drop ne altcoin support tod di. {post_sl_info['details']}"
                return result

        # 2. Fakeout Check
        if post_sl_info["behavior"] == "WICK_SWEEP_FAKEOUT":
            result["primary_tag"] = "WICK_SWEEP_FAKEOUT"
            result["detailed_reason"] = post_sl_info["details"]
            return result

        # 3. Volume Check
        if candle_df is not None and len(candle_df) >= 20:
            if candle_df["volume"].mean() < (candle_df["volume"].rolling(20).mean().iloc[-1] * 0.7):
                result["primary_tag"] = "POOR_VOLUME_PARTICIPATION"
                result["detailed_reason"] = f"Low volume participation during OTE zone test. {post_sl_info['details']}"
                return result

        # Default Loss Tag
        result["primary_tag"] = "STRUCTURE_BREAKDOWN"
        result["detailed_reason"] = f"Market structure higher-low maintain nahi kar saki. {post_sl_info['details']}"
        return result

    if status == "TIMEOUT":
        result["primary_tag"] = "CHOPPY_SIDEWAYS_MARKET"
        result["detailed_reason"] = "Price ne entry trigger ki lekin market chop/consolidation mein phans gayi."
        return result

    if status == "EXPIRED":
        result["primary_tag"] = "ZONE_INVALIDATED_BEFORE_CONFIRMATION"
        result["detailed_reason"] = "Price ne green confirmation candle close kiye baghair SL cross kar diya ya setup expire ho gaya."
        return result

    return result
