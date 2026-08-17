"""
hist_config.py — Historical Backtest System ke liye separate configuration.
Existing system (config.py) se bilkul independent hai.
Wohi exact Fibonacci strategy rules, risk parameters aur scoring weights use karta hai.
"""

import os

# ============================================================
# HISTORICAL BACKTEST DATE RANGE
# ============================================================
HIST_START_YEAR  = 2021
HIST_START_MONTH = 1
# End: current month automatically detect hoga

# ============================================================
# COIN UNIVERSE (Survivorship-bias-free: sirf woh coins
# jo 2021 se consistently Binance par listed hain)
# ============================================================
HIST_COIN_UNIVERSE = [
    "BTC/USDT",  "ETH/USDT",  "BNB/USDT",  "XRP/USDT",  "ADA/USDT",
    "SOL/USDT",  "DOGE/USDT", "LTC/USDT",  "LINK/USDT", "MATIC/USDT",
    "AVAX/USDT", "UNI/USDT",  "ATOM/USDT", "XLM/USDT",  "TRX/USDT",
    "ETC/USDT",  "NEAR/USDT", "ALGO/USDT", "FIL/USDT",  "AAVE/USDT",
]

# ============================================================
# TIMEFRAMES (same as live system)
# ============================================================
TIMEFRAMES = ["4h", "1h"]   # 30m panchani historical data mein sparse hoti hai

TF_SETTINGS = {
    "4h": {"max_structure_age_bars": 18, "min_score": 70, "zone_tolerance_pct": 0.4, "intermediate_tf": None},
    "1h": {"max_structure_age_bars": 36, "min_score": 70, "zone_tolerance_pct": 0.3, "intermediate_tf": "4h"},
}

# ============================================================
# FIBONACCI STRATEGY (EXACT same as live config.py)
# ============================================================
FIB_OTE_MIN  = 0.618
FIB_OTE_MAX  = 0.786
ALLOWED_FIB_LEVELS = [0.500, 0.618, 0.786]

CONFLUENCE_WEIGHTS = {
    "ote_zone":             30,
    "htf_bos_alignment":    25,
    "volume_expansion":     20,
    "rsi_divergence_or_os": 15,
    "prior_level_flip":     10,
}

RSI_LENGTH                = 14
RSI_OVERSOLD_THRESHOLD    = 40
VOLUME_LOOKBACK           = 20
VOLUME_SPIKE_MULTIPLIER   = 1.5
EMA_LENGTH                = 50
EMA_PROXIMITY_PCT         = 0.6
PRIOR_LEVEL_TOLERANCE_PCT = 0.5
PIVOT_BUCKETS             = [3, 6, 9, 12]
PERCENTILE_LOOKBACK       = 200

# ============================================================
# RISK-REWARD & EXECUTION MODEL (same as live)
# ============================================================
MIN_RR                = float(os.environ.get("MIN_RR", 1.5))
STOP_LOSS_ATR_MULT    = 1.5
MIN_RANGE_PCT         = 1.0
TP1_SWING_HIGH_FACTOR = 0.90
TP2_EXTENSION         = 1.618
BINANCE_FEE_PCT       = 0.075
SLIPPAGE_PCT          = 0.04
ENABLE_BTC_REGIME_FILTER = True
BTC_MAX_1H_DROP_PCT   = 2.0

# ============================================================
# DATA FETCH (Paginated Historical)
# ============================================================
EXCHANGE_PRIORITY = ["kucoin", "okx", "bybit", "gate", "mexc", "binance"]
CANDLES_PER_PAGE  = 500   # Max candles per API call (safe limit)

# ============================================================
# EMAIL CREDENTIALS (same env vars as live system)
# ============================================================
SMTP_HOST         = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER         = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD     = os.environ.get("SMTP_PASSWORD", "")
REPORT_EMAIL_TO   = os.environ.get("REPORT_EMAIL_TO", "")
