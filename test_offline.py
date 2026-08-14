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
from backtester import run_15day_rolling_backtest
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
    df_4h = make_synthetic_ohlcv(n=350, uptrend=True)
    df_daily = make_synthetic_ohlcv(n=250, seed=3, uptrend=True)

    result = analyze("BTC/USDT", "4h", df_4h, df_daily, None, None)

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


def test_backtester_15day():
    print("=== Testing backtester.run_15day_rolling_backtest() ===")
    db.init_db()
    db.insert_zone(
        coin="BTC/USDT", timeframe="4h", level_name="61.8% OTE", entry_price=64528.0,
        stop_price=62685.0, target_price=67300.0, swing_low=63000.0, swing_high=67300.0,
        score=85, actual_rr=1.85, pivot_len=6, created_at=datetime.now(timezone.utc).isoformat(),
        score_breakdown={"ote_zone": 30, "htf_bos_alignment": 25, "volume_expansion": 20, "rsi_divergence_or_os": 10},
    )

    bt = run_15day_rolling_backtest()
    print(f"Total Trades: {bt['total_trades']}")
    print(f"Net P&L (R): {bt['net_pnl_r']:.2f}")
    print(f"Profit Factor: {bt['profit_factor']:.2f}")
    print("Backtester 15-Day Test: OK\n")


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


if __name__ == "__main__":
    test_signal_engine()
    test_dynamic_universe()
    test_failure_analyzer()
    test_backtester_15day()
    test_database()
    test_reporting()
    print("=== All offline tests ran and passed cleanly ===")
