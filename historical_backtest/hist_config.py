"""
hist_config.py — Historical Backtest System Configuration.

Historical backtest ke liye sirf woh settings rakhi gayi hain
jo historical execution/reporting ke liye specific hain.

IMPORTANT:
Strategy ke core rules (Fib, scoring, RSI, EMA, ATR, RR, etc.)
live system ke config.py se liye jayenge, taake historical
backtest aur live strategy mein mismatch na ho.
"""

import os


# ============================================================
# HISTORICAL BACKTEST DATE RANGE
# ============================================================

HIST_START_YEAR = 2021
HIST_START_MONTH = 1

# Current month automatically detect hoga.
# Current month ko complete historical month nahi maana jayega.


# ============================================================
# COIN UNIVERSE
# ============================================================
#
# IMPORTANT:
# Ye current historical test universe hai.
# Listing-date filtering ko backtester mein separately handle
# kiya jayega taake unavailable historical data silently use
# na ho.
#

HIST_COIN_UNIVERSE = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "SOL/USDT",
    "DOGE/USDT",
    "LTC/USDT",
    "LINK/USDT",
    "MATIC/USDT",
    "AVAX/USDT",
    "UNI/USDT",
    "ATOM/USDT",
    "XLM/USDT",
    "TRX/USDT",
    "ETC/USDT",
    "NEAR/USDT",
    "ALGO/USDT",
    "FIL/USDT",
    "AAVE/USDT",
]


# ============================================================
# TIMEFRAMES
# ============================================================
#
# Historical analysis ke liye 4H aur 1H.
#
# IMPORTANT:
# TF_SETTINGS ki strategy values yahan duplicate nahi ki ja rahi.
# signal_engine.py live config.py se actual settings lega.
#

TIMEFRAMES = [
    "4h",
    "1h",
]


# ============================================================
# HISTORICAL DATA FETCH SETTINGS
# ============================================================

EXCHANGE_PRIORITY = [
    "kucoin",
    "okx",
    "bybit",
    "gate",
    "mexc",
    "binance",
]

CANDLES_PER_PAGE = 500

# API request ke darmiyan small delay
REQUEST_DELAY_SECONDS = 0.30

# Failed API request retry delay
RETRY_DELAY_SECONDS = 5


# ============================================================
# HISTORICAL EXECUTION / TRADE LIFETIME
# ============================================================
#
# Zone qualify hone ke baad future candles mein kitni der tak
# TP/SL resolve karna hai.
#
# Ye structure-age se alag execution lifetime hai.
#

TRADE_LIFETIME_BARS = {
    "4h": 54,
    "1h": 108,
}


# ============================================================
# SAME-CANDLE TP/SL RULE
# ============================================================
#
# Agar ek hi OHLC candle mein TP aur SL dono touch ho jayein,
# OHLC data se exact intrabar order pata nahi hota.
#
# Conservative backtest ke liye LOSS assume kiya jayega.
#

SAME_CANDLE_TP_SL_IS_LOSS = True


# ============================================================
# MARKET CONDITION CLASSIFICATION
# ============================================================

MARKET_BULL_THRESHOLD_PCT = 3.0
MARKET_STRONG_BULL_THRESHOLD_PCT = 10.0

MARKET_BEAR_THRESHOLD_PCT = -3.0
MARKET_STRONG_BEAR_THRESHOLD_PCT = -10.0


# ============================================================
# COST MODEL
# ============================================================
#
# IMPORTANT:
# Strategy ka core config config.py se aayega.
#
# Ye values historical performance calculation ke liye
# explicitly define ki ja rahi hain.
#

BINANCE_FEE_PCT = float(
    os.environ.get("BINANCE_FEE_PCT", "0.075")
)

SLIPPAGE_PCT = float(
    os.environ.get("SLIPPAGE_PCT", "0.04")
)


# ============================================================
# MINIMUM R:R
# ============================================================
#
# signal_engine.py config.MIN_RR use karta hai.
#
# Environment variable yahan sirf reporting / validation ke
# liye available rakha gaya hai.
#

MIN_RR = float(
    os.environ.get("MIN_RR", "1.5")
)


# ============================================================
# EMAIL CONFIGURATION
# ============================================================

SMTP_HOST = os.environ.get(
    "SMTP_HOST",
    "smtp.gmail.com",
)

SMTP_PORT = int(
    os.environ.get("SMTP_PORT", "587")
)

SMTP_USER = os.environ.get(
    "SMTP_USER",
    "",
)

SMTP_PASSWORD = os.environ.get(
    "SMTP_PASSWORD",
    "",
)

REPORT_EMAIL_TO = os.environ.get(
    "REPORT_EMAIL_TO",
    "",
)


# ============================================================
# REPORT CONFIGURATION
# ============================================================

REPORT_START_YEAR = HIST_START_YEAR

REPORT_TITLE = (
    "Historical Backtest — Fibonacci Intraday Strategy"
)

REPORT_TIMEZONE = "UTC"


# ============================================================
# LOGGING
# ============================================================

LOG_FILE_NAME = "hist_backtest.log"
