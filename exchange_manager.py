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


def get_working_exchange():
    """
    Priority list mein se ek ek exchange try karta hai (halka sa test call —
    fetch_time) jab tak koi respond na kare. Working ccxt exchange instance
    return karta hai.
    """
    errors = []

    for exchange_id in config.EXCHANGE_PRIORITY:
        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({"enableRateLimit": True})
            exchange.fetch_time()  # halka test call — confirm karta hai exchange accessible hai
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
