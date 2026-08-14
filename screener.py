"""
Screener — jab bhi tum manually chalao ("python screener.py"), yeh turant
poori watchlist scan karta hai aur batata hai ke ABHI kaun se coins zone
qualify kar rahe hain. Sirf TERMINAL pe output deta hai — koi email nahi
bhejta (yeh main.py ka kaam hai).

Zaroori: yeh scanner.py ke backtest/replay system se poori tarah ALAG hai
— koi database write nahi karta, koi cursor advance nahi karta. Isay jitni
baar chaho chalao, backtest ke permanent record pe koi asar nahi padega.
"""

import sys
import traceback

import logging_setup  # noqa: F401
import logging

from scanner import live_check_all
from exchange_manager import NoExchangeAvailableError

logger = logging.getLogger("trading_scanner")


def main():
    print("Scanning market (live, read-only check)... (yeh 1-2 minute le sakta hai, 50 coins x 3 timeframes)\n")

    try:
        results = live_check_all()
    except NoExchangeAvailableError as e:
        print(f"\n❌ ERROR: Koi bhi exchange accessible nahi hai.\n{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: Scan fail ho gaya — {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

    if not results:
        print("Abhi koi coin zone qualify nahi kar raha. Koi trading opportunity nahi mili.")
        return

    print(f"{len(results)} qualifying zone(s) mile:\n")
    print(f"{'COIN':<14}{'TF':<6}{'LEVEL':<8}{'ENTRY':<14}{'SCORE':<8}{'R:R'}")
    print("-" * 60)
    for r in sorted(results, key=lambda x: x["score"], reverse=True):
        print(f"{r['coin']:<14}{r['timeframe']:<6}{r['level']:<8}{r['entry']:<14.4f}"
              f"{r['score']}/100{'':<3}1:{r['rr']:.2f}")
    print("\nTradingView pe ja kar in coins ko visually verify kar sakte ho.")


if __name__ == "__main__":
    main()
