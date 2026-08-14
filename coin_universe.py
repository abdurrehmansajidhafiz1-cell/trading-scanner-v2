"""
Dynamic Binance Liquidity Engine — Binance par intraday trading ke liye sab se suitable
aur liquid USDT trading pairs ko automatically filter aur select karta hai.
Volume (> $15M USDT), Spread (< 0.08%), Volatility (2.5% - 12%), aur Data Continuity
ke filters apply hote hain. Stablecoins (USDC, FDUSD, DAI) filter out hote hain.
Network / Exchange restriction ki surat mein safe fallback `FIXED_COIN_UNIVERSE` par hoti hai.
"""

import logging
import config

logger = logging.getLogger("trading_scanner")

STABLECOIN_SYMBOLS = {
    "USDC/USDT", "FDUSD/USDT", "TUSD/USDT", "DAI/USDT", "EUR/USDT",
    "USDE/USDT", "AEUR/USDT", "PAX/USDT", "BUSD/USDT", "USDP/USDT",
}


def fetch_dynamic_binance_universe(exchange=None, limit: int = None) -> list:
    """
    Exchange tickers se dynamically top liquid USDT pairs select karta hai.
    """
    limit = limit or config.DYNAMIC_UNIVERSE_LIMIT

    if exchange is not None and hasattr(exchange, "fetch_tickers"):
        try:
            tickers = exchange.fetch_tickers()
            candidates = []

            for symbol, t in tickers.items():
                if not symbol.endswith(f"/{config.QUOTE_CURRENCY}"):
                    continue
                if symbol in STABLECOIN_SYMBOLS:
                    continue

                quote_volume = t.get("quoteVolume") or 0.0
                high = t.get("high") or 0.0
                low = t.get("low") or 0.0
                bid = t.get("bid") or 0.0
                ask = t.get("ask") or 0.0

                # 1. 24h Volume Filter (> $15M USDT)
                if quote_volume < config.MIN_24H_VOLUME_USD:
                    continue

                # 2. Volatility Filter (2.5% - 12%)
                if low > 0:
                    volatility_pct = (high - low) / low * 100
                    if not (config.MIN_DAILY_VOLATILITY_PCT <= volatility_pct <= config.MAX_DAILY_VOLATILITY_PCT):
                        continue

                # 3. Spread Filter (< 0.08%)
                if ask > 0 and bid > 0:
                    spread_pct = (ask - bid) / ask * 100
                    if spread_pct > config.MAX_BID_ASK_SPREAD_PCT:
                        continue

                candidates.append((symbol, quote_volume))

            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                selected = [c[0] for c in candidates[:limit]]
                logger.info(f"Dynamic Binance Universe selected: {len(selected)} coins (Top 24h volume > ${config.MIN_24H_VOLUME_USD:,.0f}).")
                return selected

        except Exception as e:
            logger.warning(f"Dynamic ticker fetch failed ({e}). Fallback to FIXED_COIN_UNIVERSE.")

    # Fallback to Fixed Universe
    result = list(config.FIXED_COIN_UNIVERSE[:limit])
    logger.info(f"Using fixed coin universe fallback: {len(result)} coins.")
    return result


def fetch_top_coins(exchange=None, limit: int = None) -> list:
    """
    Main interface function for scanner — attempts dynamic selection, falls back safely.
    """
    return fetch_dynamic_binance_universe(exchange=exchange, limit=limit)


if __name__ == "__main__":
    coins = fetch_top_coins()
    print(f"Coin universe — {len(coins)} coins:")
    for c in coins:
        print(f"  {c}")
