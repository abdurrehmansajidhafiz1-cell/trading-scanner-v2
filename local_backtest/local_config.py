"""
local_config.py — Configuration for the LOCAL 1-Year Historical Backtest.
Runs on your own machine (not GitHub Actions).

IMPORTANT — read this before editing anything:
signal_engine.py (the strategy engine) always does `import config` internally
— NOT hist_config.py, and NOT this file. So the actual strategy behaviour
(TF_SETTINGS, CONFLUENCE_WEIGHTS, MIN_RR, ATR stop multiplier, TP factors,
etc.) always comes from config.py sitting next to signal_engine.py. This
file only controls things specific to running the backtest locally: which
coins to test, what time window, where to save output. If you want to tune
the strategy itself, edit config.py directly (not this file).
"""

import os
from datetime import datetime, timezone, timedelta

# ============================================================
# BACKTEST WINDOW — 1 YEAR (the GitHub version does 5 years)
# ============================================================
BACKTEST_DAYS = int(os.environ.get("BACKTEST_DAYS", 365))

# Warmup buffer BEFORE the window start so indicators (200-candle ATR
# percentile for adaptive pivot length, 50-period daily EMA trend, swing
# structure) already have valid history on day 1 of the reporting window.
# Zones whose *structure* formed before the window start are computed
# correctly for state purposes but simply not recorded/counted — this
# mirrors exactly how the live scanner gates on `start_datetime`.
WARMUP_DAYS = int(os.environ.get("WARMUP_DAYS", 90))

# Set date range explicitly to Calendar Year 2024 (Jan 01, 2024 -> Dec 31, 2024)
BACKTEST_START = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
BACKTEST_END = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
FETCH_START = BACKTEST_START - timedelta(days=WARMUP_DAYS)

# ============================================================
# COIN UNIVERSE — same 20 coins as the 5-year GitHub version.
# Trim this list if your machine/network is slow — fewer coins = faster run.
# (Each coin needs 2 timeframes + daily fetched via paginated API calls.)
# ============================================================
COIN_UNIVERSE = [
    "BTC/USDT",  "ETH/USDT",  "BNB/USDT",  "XRP/USDT",  "ADA/USDT",
    "SOL/USDT",  "DOGE/USDT", "LTC/USDT",  "LINK/USDT", "MATIC/USDT",
    "AVAX/USDT", "UNI/USDT",  "ATOM/USDT", "XLM/USDT",  "TRX/USDT",
    "ETC/USDT",  "NEAR/USDT", "ALGO/USDT", "FIL/USDT",  "AAVE/USDT",
]

# ============================================================
# TIMEFRAMES (30m dropped — historical 30m data is sparse/unreliable on
# most exchanges going back a full year; same choice as the 5-year version)
# ============================================================
TIMEFRAMES = ["4h", "1h"]

# ============================================================
# EXCHANGE PRIORITY — same fallback order as the GitHub 5-year version.
# kucoin/okx tried first since Binance sometimes geo-blocks historical
# pagination depending on where the request originates.
# ============================================================
EXCHANGE_PRIORITY = ["kucoin", "okx", "bybit", "gate", "mexc", "binance"]
CANDLES_PER_PAGE = 500

# ============================================================
# OUTPUT — local files instead of GitHub Actions artifacts
# ============================================================
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")

# ============================================================
# EMAIL — OPTIONAL for local runs. Leave SEND_EMAIL=false (default) to
# skip email entirely; a full text report + CSV are always saved locally
# either way, so email is not required to see results.
# ============================================================
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
REPORT_EMAIL_TO = os.environ.get("REPORT_EMAIL_TO", "")
SEND_EMAIL = os.environ.get("SEND_EMAIL", "false").lower() == "true"
