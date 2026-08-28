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
# BACKTEST WINDOW — FULL YEAR 2025 (Jan 01, 2025 -> Dec 31, 2025)
# ============================================================
BACKTEST_START = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
BACKTEST_END = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
WARMUP_DAYS = int(os.environ.get("WARMUP_DAYS", 90))
FETCH_START = BACKTEST_START - timedelta(days=WARMUP_DAYS)

# ============================================================
# DYNAMIC MONTHLY UNIVERSE ENGINE
# ============================================================
# Har month system candidate pool mein se us month ki volume aur volatility
# ke mutabiq Top coins dynamically select karega (har month alag selection).
ENABLE_DYNAMIC_MONTHLY_SELECTION = True
MONTHLY_UNIVERSE_SIZE = 15  # Har month Top 15 most liquid & volatile coins

# Comprehensive Candidate Pool jo fetch aur rank hoga
COIN_UNIVERSE = [
    "BTC/USDT",  "ETH/USDT",  "SOL/USDT",  "BNB/USDT",  "XRP/USDT",
    "DOGE/USDT", "ADA/USDT",  "LTC/USDT",  "LINK/USDT", "AVAX/USDT",
    "NEAR/USDT", "TRX/USDT",  "ETC/USDT",  "FIL/USDT",  "AAVE/USDT",
    "UNI/USDT",  "ATOM/USDT", "XLM/USDT",  "ALGO/USDT", "SUI/USDT",
    "PEPE/USDT", "FET/USDT",  "ICP/USDT",  "TAO/USDT",  "ENA/USDT",
]

# ============================================================
# TIMEFRAMES
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
