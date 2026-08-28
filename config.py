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
        "max_structure_age_bars": 24,      # ~4 din
        "min_score": 70,                   # 4H high-reliability score threshold
        "zone_tolerance_pct": 0.4,
        "intermediate_tf": None,           # sirf Daily/4H check
    },
    "1h": {
        "max_structure_age_bars": 48,      # ~2 din
        "min_score": 80,                   # 1H quality threshold (High Confluence)
        "zone_tolerance_pct": 0.3,
        "intermediate_tf": "4h",           # 4H + 1H check
    },
    "30m": {
        "max_structure_age_bars": 40,      # ~20 ghante
        "min_score": 75,
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
    "ote_zone": 30,             # 61.8% to 78.6% Fib OTE zone
    "htf_bos_alignment": 25,     # 4H Market Structure / BOS Alignment
    "volume_expansion": 20,     # Volume > 1.5x 20-period avg
    "rsi_divergence_or_os": 15, # RSI <= 48 or Pullback momentum
    "prior_level_flip": 10,     # Support-to-Resistance Flip
}

RSI_LENGTH = 14
RSI_OVERSOLD_THRESHOLD = 48
VOLUME_LOOKBACK = 20
VOLUME_SPIKE_MULTIPLIER = 1.5
EMA_LENGTH = 50
EMA_PROXIMITY_PCT = 0.6
PRIOR_LEVEL_TOLERANCE_PCT = 0.5

# ============================================================
# RISK-REWARD & EXECUTION MODEL
# ============================================================
MIN_RR = float(os.environ.get("MIN_RR", 1.25))  # Minimum 1:1.25 Risk-to-Reward (Accommodates 1.75x ATR Safe SL)
STOP_LOSS_ATR_MULT = 1.75      # Volatility-based safe stop loss: 1.75x ATR (Sweeps & fakeouts protection)
STOP_LOSS_SWING_LOW_BUFFER_PCT = 0.8 # 0.8% structural buffer below Swing Low
MIN_RANGE_PCT = 1.0           # Minimum swing range jo valid maana jaye

# Primary Entry Level: 78.6% Deep OTE Sniper Entry (100% Allocation for max asymmetric R:R)
ENTRY_FIB_RATIO = 0.786
TP1_SWING_HIGH_FACTOR = 0.95   # Primary Target @ 95% of Swing High
TP2_EXTENSION = 1.272          # Extended Target @ 1.272 Fib Extension (for shallow 61.8% reversals)
TP3_EXTENSION = 1.618          # Runner Target @ 1.618 Fib Extension

# Dynamic Trailing Profit-Locking Mechanism (Never return to 0.00R Breakeven!)
ENABLE_PROFIT_LOCK = True
PROFIT_LOCK_STAGE1_TRIGGER = 0.60  # At 60% of Target move (~+1.0R gain)
PROFIT_LOCK_STAGE1_LOCK    = 0.25  # Lock SL to +25% of Target move (+0.40R Guaranteed Cash Profit)
PROFIT_LOCK_STAGE2_TRIGGER = 0.80  # At 80% of Target move (~+1.4R gain)
PROFIT_LOCK_STAGE2_LOCK    = 0.50  # Lock SL to +50% of Target move (+0.80R Guaranteed Cash Profit)
ENABLE_BREAKEVEN_SL = True

# ============================================================
# MANDATORY QUALITY FILTERS (Hard Filters — Score se alag)
# ============================================================
# Agar yeh True hain to zone tab bhi reject hoga jab score pass ho
REQUIRE_RSI_OVERSOLD = True    # RSI > RSI_HARD_THRESHOLD hone par zone reject
RSI_HARD_THRESHOLD = 50        # RSI is se upar ho to zone invalid (shallow pullback trap elimination)

REQUIRE_VOLUME_SPIKE = True    # Last 3 bars mein volume spike ZAROOR hona chahiye
VOLUME_SPIKE_LOOKBACK = 3      # Kitne bars mein spike check karein

# ============================================================
# DAILY PROTECTION RULES (Circuit Breaker + Zone Cap)
# ============================================================
ENABLE_DAILY_CIRCUIT_BREAKER = True
DAILY_MAX_LOSS_R = -2.0        # Portfolio-wide max loss per day (-2.0R)

ENABLE_DAILY_ZONE_CAP = True
MAX_SAME_DAY_ZONES = 3         # Portfolio-wide max 3 highest-quality setups per day

# ============================================================
# IMPROVEMENT 1: ALTCOIN INDIVIDUAL TREND FILTER
# ============================================================
# Altcoin ka khud ka Daily EMA check — agar coin khud Bear mein ho to long skip
ENABLE_ALTCOIN_TREND_FILTER = True
ALTCOIN_TREND_EMA_LENGTH = 200   # Daily EMA 200 — long-term trend gauge

# ============================================================
# IMPROVEMENT 2: MONTHLY TRADE CAP
# ============================================================
# Note: Market logic filters (EMA, RSI, BOS) already filter bad trades dynamically.
# Artificial trade caps suppress genuine bull-market wins, so kept False for pure performance.
ENABLE_MONTHLY_TRADE_CAP = False
MONTHLY_MAX_TRADES = 30

# ============================================================
# IMPROVEMENT 3: CONSECUTIVE LOSS PAUSE (Cooling Period)
# ============================================================
ENABLE_CONSEC_LOSS_PAUSE = True
MAX_CONSEC_LOSSES_BEFORE_PAUSE = 3  # 3 consecutive losses ke baad pause
CONSEC_LOSS_PAUSE_HOURS = 36        # 36 ghante ka cooling period

# Real Execution Cost Modeling (Binance)
BINANCE_FEE_PCT = 0.075      # 0.075% fee per side (with BNB discount)
SLIPPAGE_PCT = 0.04          # 0.04% realistic slippage assumption

# Portfolio Exposure Limit (Anti-Cascade Dump Protection)
MAX_ACTIVE_TRADES = int(os.environ.get("MAX_ACTIVE_TRADES", 4))

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
BTC_REQUIRE_EMA_TREND = True     # Block altcoin longs if BTC is below EMA 50 (Bear regime)

# ============================================================
# SYSTEM & EVALUATION WINDOW
# ============================================================
SYSTEM_START_DATETIME = os.environ.get("SYSTEM_START_DATETIME", None)
EVALUATION_WINDOW_DAYS = 30      # 30-day rolling evaluation window (1-Month Plan)

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
