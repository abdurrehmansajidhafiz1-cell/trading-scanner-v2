"""
Config — Complete Trading & Backtesting System Settings.
Updated for Intraday Fibonacci Strategy with Dynamic Binance Liquidity Universe,
ATR-based Stop Losses, Dual Take-Profit targets, and 15-Day Rolling Evaluation.
"""

import os

# ============================================================
# TIMEZONE
# ============================================================
TIMEZONE = "Asia/Karachi"  # Pakistan Time (PKT, UTC+5, no DST)

# ============================================================
# TIMEFRAMES SCAN KARNI HAIN
# ============================================================
TIMEFRAMES = ["4h", "1h", "30m"]

TF_SETTINGS = {
    "4h": {
        "max_structure_age_bars": 18,      # ~3 din
        "min_score": 70,
        "zone_tolerance_pct": 0.4,
        "intermediate_tf": None,           # sirf Daily/4H check
    },
    "1h": {
        "max_structure_age_bars": 36,      # ~1.5 din
        "min_score": 70,
        "zone_tolerance_pct": 0.3,
        "intermediate_tf": "4h",           # 4H + 1H check
    },
    "30m": {
        "max_structure_age_bars": 30,      # ~15 ghante
        "min_score": 70,
        "zone_tolerance_pct": 0.25,
        "intermediate_tf": "1h",           # 4H + 1H + 30M check
    },
}

# ============================================================
# ADAPTIVE PIVOT LENGTH (ATR percentile buckets)
# ============================================================
PIVOT_BUCKETS = [3, 6, 9, 12]
PERCENTILE_LOOKBACK = 200

# ============================================================
# FIBONACCI & INTRADAY CONFLUENCE SCORING WEIGHTS
# ============================================================
# Primary OTE Zone: 61.8% to 78.6% Retracement
FIB_OTE_MIN = 0.618
FIB_OTE_MAX = 0.786
ALLOWED_FIB_LEVELS = [0.500, 0.618, 0.786]

CONFLUENCE_WEIGHTS = {
    "ote_zone": 30,             # 61.8% - 78.6% Fib OTE zone
    "htf_bos_alignment": 25,     # 4H Market Structure / BOS Alignment
    "volume_expansion": 20,     # Volume > 1.5x 20-period avg
    "rsi_divergence_or_os": 15, # RSI <= 40 or Bullish Divergence
    "prior_level_flip": 10,     # Support-to-Resistance Flip
}

RSI_LENGTH = 14
RSI_OVERSOLD_THRESHOLD = 40
VOLUME_LOOKBACK = 20
VOLUME_SPIKE_MULTIPLIER = 1.5
EMA_LENGTH = 50
EMA_PROXIMITY_PCT = 0.6
PRIOR_LEVEL_TOLERANCE_PCT = 0.5

# ============================================================
# RISK-REWARD & EXECUTION MODEL
# ============================================================
MIN_RR = float(os.environ.get("MIN_RR", 1.5))  # Minimum 1:1.5 Risk-to-Reward
STOP_LOSS_ATR_MULT = 1.5     # Volatility-based stop loss: 1.5x ATR buffer below Swing Low
MIN_RANGE_PCT = 1.0          # Minimum swing range jo valid maana jaye
TP1_SWING_HIGH_FACTOR = 0.90 # TP1 @ 90% of Swing High distance
TP2_EXTENSION = 1.618        # TP2 @ 1.618 Fib Extension

# Real Execution Cost Modeling (Binance)
BINANCE_FEE_PCT = 0.075      # 0.075% fee per side (with BNB discount)
SLIPPAGE_PCT = 0.04          # 0.04% realistic slippage assumption

# ============================================================
# DYNAMIC BINANCE LIQUIDITY UNIVERSE ENGINE
# ============================================================
QUOTE_CURRENCY = "USDT"
DYNAMIC_UNIVERSE_LIMIT = 50
MIN_24H_VOLUME_USD = 15_000_000   # Min $15 Million 24h Volume
MAX_BID_ASK_SPREAD_PCT = 0.08    # Max 0.08% Spread
MIN_DAILY_VOLATILITY_PCT = 2.5   # Min 2.5% Daily Volatility (Range)
MAX_DAILY_VOLATILITY_PCT = 12.0  # Max 12.0% Daily Volatility

# Fallback Fixed Universe (agar dynamic fetch network error se fail ho jaye)
FIXED_COIN_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT",
    "NEAR/USDT", "DOGE/USDT", "ADA/USDT", "SUI/USDT", "LINK/USDT",
    "PEPE/USDT", "ICP/USDT", "TAO/USDT", "ENA/USDT", "LTC/USDT",
    "TON/USDT", "CRV/USDT", "ONDO/USDT", "BOME/USDT", "UNI/USDT",
    "XLM/USDT", "PENGU/USDT", "FET/USDT", "AVAX/USDT", "AAVE/USDT",
    "WLD/USDT", "TRX/USDT", "BICO/USDT", "UTK/USDT", "ACT/USDT",
]
UNIVERSE_SIZE = len(FIXED_COIN_UNIVERSE)

# ============================================================
# SAFEGUARDS & BTC REGIME FILTER
# ============================================================
ENABLE_BTC_REGIME_FILTER = True
BTC_MAX_1H_DROP_PCT = 2.0        # Block altcoin longs if BTC drops > 2% in 1 hour

# ============================================================
# SYSTEM & EVALUATION WINDOW
# ============================================================
SYSTEM_START_DATETIME = os.environ.get("SYSTEM_START_DATETIME", None)
EVALUATION_WINDOW_DAYS = 15      # 15-day rolling evaluation window

# ============================================================
# LOGGING & DATABASE
# ============================================================
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = os.environ.get("LOG_FILE", "scanner.log")
DB_PATH = os.environ.get("DB_PATH", "trading_system.db")

# ============================================================
# EMAIL CREDENTIALS
# ============================================================
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
REPORT_EMAIL_TO = os.environ.get("REPORT_EMAIL_TO", "")

# ============================================================
# EXCHANGE PRIORITY & DATA FETCH
# ============================================================
EXCHANGE_PRIORITY = ["binance", "kucoin", "okx", "bybit", "gate", "mexc"]
CANDLES_TO_FETCH = 300
