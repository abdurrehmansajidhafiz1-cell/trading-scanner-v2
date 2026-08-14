"""
Failure Analyzer Engine — Automatically diagnoses trade outcomes (Wins & Losses).
Losing trades ko exact physical cause (jaise FALSE_BREAKOUT, BTC_DUMP_IMPACT,
WEAK_MARKET_STRUCTURE, POOR_VOLUME, etc.) tag karta hai.
Winning trades ke top confluence factors ko tag karta hai.
"""

import pandas as pd
import config


def diagnose_trade_outcome(zone: dict, candle_df: pd.DataFrame, btc_df: pd.DataFrame | None = None) -> dict:
    """
    Resolved trade (WIN / LOSS / TIMEOUT) ko analyze kar ke diagnostic tagging metadata return karta hai.
    """
    status = zone.get("status")
    result = {
        "zone_id": zone.get("id"),
        "coin": zone.get("coin"),
        "timeframe": zone.get("timeframe"),
        "status": status,
        "primary_tag": None,
        "detailed_reason": None,
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
        result["detailed_reason"] = "Trade hit target with strong confluence and valid structure."
        return result

    if status == "LOSS":
        # 1. BTC Dump Check
        if btc_df is not None and len(btc_df) > 4:
            btc_last = btc_df["close"].iloc[-1]
            btc_prev = btc_df["close"].iloc[-4]
            if (btc_prev - btc_last) / btc_prev * 100 >= config.BTC_MAX_1H_DROP_PCT:
                result["primary_tag"] = "BTC_DUMP_IMPACT"
                result["detailed_reason"] = "Market-wide BTC sudden drop affected altcoin Fib hold."
                return result

        # 2. Wick Sweep / False Breakout Check
        if candle_df is not None and len(candle_df) > 0:
            stop_price = zone.get("stop_price", 0)
            target_price = zone.get("target_price", 0)
            
            lowest_low = candle_df["low"].min()
            highest_high_after_stop = candle_df["high"].max()

            if lowest_low <= stop_price < candle_df["close"].iloc[-1] and highest_high_after_stop >= target_price:
                result["primary_tag"] = "FALSE_BREAKOUT"
                result["detailed_reason"] = "Stop loss hit by wick sweep, price subsequently moved towards target."
                return result

            # 3. Volume Check
            if candle_df["volume"].mean() < (candle_df["volume"].rolling(20).mean().iloc[-1] * 0.7 if len(candle_df) >= 20 else 1.0):
                result["primary_tag"] = "POOR_VOLUME"
                result["detailed_reason"] = "Low volume participation during Fib zone test."
                return result

        # Default Loss Tag
        result["primary_tag"] = "WEAK_MARKET_STRUCTURE"
        result["detailed_reason"] = "Market structure failed to maintain higher low support."
        return result

    if status == "TIMEOUT":
        result["primary_tag"] = "CHOPPY_SIDEWAYS_MARKET"
        result["detailed_reason"] = "Price entered zone but market momentum flattened into a range."
        return result

    return result
