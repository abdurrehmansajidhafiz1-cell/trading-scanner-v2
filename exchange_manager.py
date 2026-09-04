"""
Exchange manager — Binance geo-block (451 error) jaisi problems se bachne ke
liye, yeh module priority list ke hisaab se exchanges try karta hai jab tak
koi ek kaam na kar jaye. Ek baar working exchange mil jaye, poori scan run
usi se hoti hai (taake beech mein exchange switch na ho aur data consistent rahe).
"""

import logging

import ccxt

import config

logger = logging.getLogger("trading_scanner")


class NoExchangeAvailableError(Exception):
    """Jab koi bhi exchange (poori priority list mein se) accessible na ho."""
    pass


BINANCE_FALLBACK_BASES = [
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api3.binance.com",
    "https://api.binance.com",
]


def _create_binance_exchange(base_url: str):
    exchange = ccxt.binance({
        "enableRateLimit": True,
        "timeout": 30000,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        "urls": {
            "api": {
                "public": f"{base_url}/api/v3",
                "sapi": f"{base_url}/sapi/v1",
            }
        },
    })
    return exchange


def get_working_exchange():
    """
    Priority list mein se ek ek exchange try karta hai jab tak koi respond na kare.
    Binance ke liye official open non-geoblocked gateway (data-api.binance.vision) aur
    fallback rotation endpoints use karta hai taake US cloud geoblock (451) se bacha ja sake.
    """
    errors = []

    for exchange_id in config.EXCHANGE_PRIORITY:
        if exchange_id == "binance":
            for base_url in BINANCE_FALLBACK_BASES:
                try:
                    exchange = _create_binance_exchange(base_url)
                    exchange.fetch_time()
                    logger.info(f"Exchange 'binance' endpoint '{base_url}' accessible hai, isay use kar rahe hain.")
                    return exchange, "binance"
                except Exception as e:
                    error_msg = f"binance ({base_url}): {type(e).__name__} — {e}"
                    errors.append(error_msg)
                    logger.warning(f"Binance endpoint '{base_url}' accessible nahi: {e}")
            continue

        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({
                "enableRateLimit": True,
                "timeout": 25000,
                "headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            })
            exchange.fetch_time()  # confirm exchange accessible
            logger.info(f"Exchange '{exchange_id}' accessible hai, isay use kar rahe hain.")
            return exchange, exchange_id
        except Exception as e:
            error_msg = f"{exchange_id}: {type(e).__name__} — {e}"
            errors.append(error_msg)
            logger.warning(f"Exchange '{exchange_id}' accessible nahi: {e}")
            continue

    error_summary = "\n".join(errors)
    raise NoExchangeAvailableError(
        f"Koi bhi exchange (in mein se: {config.EXCHANGE_PRIORITY}) accessible nahi tha.\n"
        f"Detail:\n{error_summary}"
    )
