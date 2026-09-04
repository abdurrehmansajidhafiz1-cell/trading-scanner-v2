"""
Config — Complete Trading & Backtesting System Settings.
Updated for Intraday Fibonacci Strategy with Dynamic Binance Liquidity Universe,
ATR-based Stop Losses, Dual Take-Profit targets, and 15-Day Rolling Evaluation.
"""

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ============================================================
# TIMEZONE
# ============================================================
TIMEZONE = "Asia/Karachi"  # Pakistan Time (PKT, UTC+5, no DST)

# ============================================================
# TIMEFRAMES SCAN KARNI HAIN (30m & 1h Intraday Only)
# ============================================================
TIMEFRAMES = ["1h", "30m"]

TF_SETTINGS = {
    "1h": {
        "max_structure_age_bars": 48,      # ~2 din
        "min_score": 80,                   # 1H quality threshold (High Confluence)
        "zone_tolerance_pct": 0.3,
        "intermediate_tf": "4h",           # Daily + 4H alignment check
    },
    "30m": {
        "max_structure_age_bars": 40,      # ~20 ghante
        "min_score": 75,
        "zone_tolerance_pct": 0.25,
        "intermediate_tf": "1h",           # Daily + 1H alignment check
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
MIN_RR = float(os.environ.get("MIN_RR", 1.3))  # Minimum 1:1.3 Risk-to-Reward
STOP_LOSS_ATR_MULT = 1.2     # Volatility-based stop loss: 1.2x ATR buffer
MIN_RANGE_PCT = 1.0          # Minimum swing range jo valid maana jaye
TP1_SWING_HIGH_FACTOR = 0.95 # Primary Take Profit (TP1) @ 95% of Swing High distance
TP2_EXTENSION = 1.618        # Extended Take Profit (TP2) @ 1.618 Fib Extension

# Breakeven Stop Loss Mechanism
ENABLE_BREAKEVEN_SL = True
BREAKEVEN_TRIGGER_RATIO = 0.55  # 55% target move hone par SL entry pe shift (risk-free runner)

# Strict 24-Hour Trade Expiry & Timeout Limits
MAX_HOLDING_HOURS = 24          # Max 24 ghante tak trade active/pending reh sakti hai, uske baad auto-close

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
BINANCE_FEE_PCT = 0.075      # 0.075% fee per side (with standard/BNB spot rate)
SLIPPAGE_PCT = 0.04          # 0.04% realistic slippage assumption
USDT_PKR_RATE = float(os.environ.get("USDT_PKR_RATE", 280.0))  # 1 USDT = 280 PKR for PKR Playbook

# Portfolio Exposure Limit (Anti-Cascade Dump Protection)
MAX_ACTIVE_TRADES = int(os.environ.get("MAX_ACTIVE_TRADES", 3))  # Max 3 concurrent active trades

# Sunday Shield (Weekly Close & Asian Open Noise Defense)
ENABLE_SUNDAY_SHIELD = True

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
# SAFEGUARDS & SMART BTC REGIME FILTER
# ============================================================
ENABLE_BTC_REGIME_FILTER = True
BTC_MAX_1H_DROP_PCT = 1.5        # Block altcoin longs if BTC drops > 1.5% in 1 hour
BTC_MAX_4H_DROP_PCT = 3.0        # Block altcoin longs if BTC drops > 3.0% in 4 hours (Slow bleed dump defense)
BTC_MIN_RSI_1H = 40.0            # Block altcoin longs if BTC 1H RSI < 40 (Bear momentum)
BTC_REQUIRE_EMA_TREND = True     # Block altcoin longs if BTC is below EMA 50 (Bear regime)

# ============================================================
# SYSTEM & EVALUATION WINDOW (15-Day Live System Starting Sep 3, 2026 09:30 AM PKT)
# ============================================================
SYSTEM_START_DATETIME = os.environ.get("SYSTEM_START_DATETIME", "2026-09-03 09:30:00")
EVALUATION_WINDOW_DAYS = 15      # 15-Day Fresh Live Evaluation System
SCHEDULED_REPORT_INTERVAL_HOURS = 12  # Har 12 ghante baad subah 6 AM aur shaam 6 PM PKT report

# Real-Time Instant Alerts & Scheduled Reporting
ENABLE_INSTANT_ALERTS = True     # Har naye qualifying zone par foran email alert
ENABLE_SCHEDULED_REPORTS = True   # 12-hour routine morning/evening reports active (06:00 AM & 06:00 PM PKT)

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
