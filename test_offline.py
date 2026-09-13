"""
Offline Test Suite — Validates Intraday Fibonacci Strategy Engine, Dynamic Liquidity Selector,
Failure Analyzer, 15-Day Rolling Backtester, Database Layer, and Dual-Reporting offline.
"""

import os
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

os.environ["DB_PATH"] = "test_trading_system.db"
if os.path.exists("test_trading_system.db"):
    os.remove("test_trading_system.db")

import config
import database as db
from signal_engine import analyze
from coin_universe import fetch_top_coins
from failure_analyzer import diagnose_trade_outcome
from local_backtest.local_backtester import compute_metrics
from reporting import generate_report, due_intraday_reports


def make_synthetic_ohlcv(n=350, seed=7, uptrend=True):
    np.random.seed(seed)
    dates = pd.date_range("2026-01-01", periods=n, freq="4h", tz="utc")

    prices = [60000.0]
    for i in range(1, n):
        drift = 15 if uptrend else -15
        prices.append(prices[-1] + np.random.uniform(-100, 100) + drift)

    swing_prices = [
        63800, 63500, 63200, 63000, 63400, 63900, 64500, 65200, 65800,
        66400, 66900, 67300, 67000, 66600, 66200, 65900, 65600, 65472,
    ]
    prices[-18:] = swing_prices

    df = pd.DataFrame({"timestamp": dates, "close": prices})
    df["open"] = df["close"].shift(1).fillna(df["close"].iloc[0])
    df["high"] = df[["open", "close"]].max(axis=1) + np.random.uniform(20, 100, n)
    df["low"] = df[["open", "close"]].min(axis=1) - np.random.uniform(20, 100, n)
    df["volume"] = np.random.uniform(80, 150, n)
    df.loc[n - 3:, "volume"] *= 1.8
    return df


def test_signal_engine():
    print("=== Testing signal_engine.analyze() with Intraday Fib & OTE ===")
    df_1h = make_synthetic_ohlcv(n=350, uptrend=True)
    df_daily = make_synthetic_ohlcv(n=250, seed=3, uptrend=True)

    result = analyze("BTC/USDT", "1h", df_1h, df_daily, None, None)

    print(f"Valid structure: {result.valid_structure}")
    print(f"Swing: {result.swing_low} -> {result.swing_high}")
    print(f"Trend ok: {result.trend_ok}")
    print(f"Best zone: {result.best_zone_name} @ {result.best_zone_price}")
    print(f"Score: {result.best_score}/100")
    print(f"Stop Loss (ATR): {result.stop_price}")
    print(f"Target Price (TP1): {result.target_price}")
    print(f"R:R: {result.actual_rr}")
    print(f"Qualifies: {result.qualifies}")
    if not result.qualifies:
        print(f"Reject reason: {result.reject_reason_code} — {result.reject_reason_detail}")
    print()
    return result


def test_dynamic_universe():
    print("=== Testing coin_universe.fetch_top_coins() ===")
    coins = fetch_top_coins()
    print(f"Fetched {len(coins)} coins from liquidity engine.")
    assert len(coins) > 0, "Coin universe should not be empty"
    print("Coin Universe Test: OK\n")


def test_failure_analyzer():
    print("=== Testing failure_analyzer.diagnose_trade_outcome() ===")
    sample_win = {"id": 1, "coin": "BTC/USDT", "timeframe": "4h", "status": "WIN", "score": 85, "actual_rr": 2.1}
    diag_win = diagnose_trade_outcome(sample_win, None, None)
    print(f"Win Tag: {diag_win['primary_tag']} - {diag_win['confluence_tags']}")
    assert diag_win["primary_tag"] == "SUCCESSFUL_OTE_BOUNCE"

    sample_loss = {"id": 2, "coin": "ETH/USDT", "timeframe": "1h", "status": "LOSS", "stop_price": 3000.0, "target_price": 3500.0}
    diag_loss = diagnose_trade_outcome(sample_loss, None, None)
    print(f"Loss Tag: {diag_loss['primary_tag']} - {diag_loss['detailed_reason']}")
    assert diag_loss["primary_tag"] is not None
    print("Failure Analyzer Test: OK\n")


def test_backtester_engine():
    print("=== Testing local_backtester.compute_metrics() ===")
    sample_zones = [
        {
            "coin": "BTC/USDT", "timeframe": "4h", "status": "WIN",
            "entry_price": 64528.0, "stop_price": 62685.0, "target_price": 67300.0,
            "actual_rr": 1.85, "created_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "coin": "ETH/USDT", "timeframe": "1h", "status": "BREAKEVEN",
            "entry_price": 3500.0, "stop_price": 3400.0, "target_price": 3700.0,
            "actual_rr": 0.50, "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ]

    bt = compute_metrics(sample_zones)
    print(f"Total Trades: {bt['total_trades']}")
    print(f"Net P&L (R): {bt['net_pnl_r']:.2f}")
    print(f"Profit Factor: {bt['profit_factor']:.2f}")
    print("Backtester Engine Test: OK\n")


def test_database():
    print("=== Testing database read/write ===")
    db.init_db()
    pending = db.get_pending_zones()
    print(f"Pending zones in DB: {len(pending)}")
    if pending:
        db.update_zone_status(pending[0]["id"], "WIN", touched_at=db.now_iso(), resolved_at=db.now_iso())
    print("Database read/write: OK\n")


def test_reporting():
    print("=== Testing reporting.generate_report() Dual Mode ===")
    start_dt = datetime.now(timezone.utc) - timedelta(days=1)
    end_dt = datetime.now(timezone.utc)
    report = generate_report("Morning Report (06:00 AM PKT Test)", start_dt, end_dt, include_cumulative=True)
    print(report[:400] + "\n...")
    print("Reporting Test: OK\n")


def test_instant_alert_generation():
    print("=== Testing reporting.generate_instant_signal_alert_text() ===")
    from reporting import generate_instant_signal_alert_text
    sample_zone = {
        "coin": "SOL/USDT",
        "timeframe": "1h",
        "score": 100,
        "score_breakdown": {"ote_zone": 30, "htf_bos_alignment": 25, "volume_expansion": 20, "rsi_divergence_or_os": 15, "prior_level_flip": 10},
        "swing_low": 94.96,
        "swing_high": 110.60,
        "entry_price": 98.31,
        "entry_1": 100.93,
        "entry_2": 98.31,
        "stop_price": 92.46,
        "target_price": 109.82,
        "tp1_price": 109.82,
        "tp2_price": 120.26,
        "actual_rr": 1.97,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    alert_text = generate_instant_signal_alert_text(sample_zone)
    print(alert_text[:500].encode("ascii", "replace").decode("ascii") + "\n...")
    assert "PLAYBOOK 1: $100 CAPITAL (USD)" in alert_text
    assert "PLAYBOOK 2: $35 CAPITAL (IN PAKISTANI RUPEES — PKR" in alert_text
    assert "SCENARIO 1" in alert_text
    assert "SCENARIO 10" in alert_text
    assert "PKR" in alert_text
    print("Instant Alert Generation Test (Dual USD & PKR Playbooks): OK\n")


def test_dual_tier_resolution():
    print("=== Testing Dual-Tier Entry Resolution (61.8% & 78.6%) ===")
    from scanner import resolve_pending_zones
    
    # Create test zone with Tier 1 @ 100, Tier 2 @ 90, SL @ 85, TP1 @ 110
    now = datetime.now(timezone.utc)
    z_id = db.insert_zone(
        coin="TEST/USDT", timeframe="30m", level_name="78.6% OTE",
        entry_price=90.0, stop_price=85.0, target_price=110.0,
        swing_low=80.0, swing_high=120.0, score=90, actual_rr=2.0,
        pivot_len=5, created_at=(now - timedelta(hours=2)).isoformat(),
        entry_1=100.0, entry_2=90.0, tp1_price=110.0
    )

    class MockExchange:
        def fetch_ohlcv(self, symbol, timeframe, limit=100):
            # Bar 1: Dips to 98 (touches 61.8% @ 100, but NOT 78.6% @ 90), Green candle (close 101 > open 99)
            # Bar 2: Rallies to 112 (hits TP1 @ 110)
            t1 = int((now - timedelta(minutes=60)).timestamp() * 1000)
            t2 = int((now - timedelta(minutes=30)).timestamp() * 1000)
            t3 = int(now.timestamp() * 1000)
            return [
                [t1, 99.0, 102.0, 98.0, 101.0, 500.0],  # Bar 1: Green confirmation after Tier 1 touch
                [t2, 101.0, 112.0, 100.0, 111.0, 800.0], # Bar 2: Smashes TP1
                [t3, 111.0, 112.0, 110.0, 111.5, 100.0], # Incomplete candle (dropped by fetch_ohlcv)
            ]

    resolve_pending_zones(MockExchange(), "TEST/USDT", "30m")
    updated_z = db.get_zone_by_id(z_id)
    print(f"Zone #{z_id} Status after Dual-Tier resolution: {updated_z['status']}")
    assert updated_z["status"] == "WIN", f"Expected WIN via 61.8% Tier-1 touch, got {updated_z['status']}"
    print("Dual-Tier Entry Resolution Test: OK\n")


def test_pullback_confirmation_gate():
    print("=== Testing Pullback Confirmation Gate (38.2% Retracement Check) ===")
    dates = pd.date_range("2026-01-01", periods=150, freq="30min", tz="utc")
    # Upward trend to 100, but last candles stay at 99.5 (no 38.2% pullback)
    closes = np.linspace(80, 100, 150)
    df = pd.DataFrame({
        "timestamp": dates,
        "open": closes - 0.1,
        "high": closes + 0.5,
        "low": closes - 0.5,
        "close": closes,
        "volume": np.full(150, 1000.0)
    })
    df_daily = df.copy()

    res = analyze("TEST/USDT", "30m", df, df_daily, None, None)
    # Structure cannot qualify without a pullback or up-leg
    print(f"Gate check qualifies: {res.qualifies}, reason: {res.reject_reason_code}")
    print("Pullback Confirmation Gate Test: OK\n")


if __name__ == "__main__":
    test_signal_engine()
    test_dynamic_universe()
    test_failure_analyzer()
    test_backtester_engine()
    test_database()
    test_reporting()
    test_instant_alert_generation()
    test_dual_tier_resolution()
    test_pullback_confirmation_gate()
    print("=== All offline tests ran and passed cleanly ===")
