"""
Dashboard Generator: Generates markdown live tracking tables and KPIs
from SQLite database and updates the README.md automatically.
"""

import sqlite3
import json
from datetime import datetime, timezone
import os

import database as db
import timezone_utils as tz
import config

START_MARKER = "<!-- LIVE_DASHBOARD_START -->"
END_MARKER = "<!-- LIVE_DASHBOARD_END -->"


def generate_dashboard_markdown() -> str:
    all_zones = db.get_all_zones()
    start_dt = tz.parse_pkt_input(config.SYSTEM_START_DATETIME) if config.SYSTEM_START_DATETIME else datetime.now(timezone.utc)
    now_utc = datetime.now(timezone.utc)
    
    elapsed = now_utc - start_dt
    days_elapsed = max(1, elapsed.days + 1)
    day_str = f"Day {min(days_elapsed, config.EVALUATION_WINDOW_DAYS)} of {config.EVALUATION_WINDOW_DAYS}"
    
    wins = [z for z in all_zones if z["status"] == "WIN"]
    losses = [z for z in all_zones if z["status"] == "LOSS"]
    breakevens = [z for z in all_zones if z["status"] == "BREAKEVEN"]
    pending = [z for z in all_zones if z["status"] in ("PENDING", "ACTIVE")]
    timeouts = [z for z in all_zones if z["status"] in ("EXPIRED", "TIMEOUT")]
    
    resolved_count = len(wins) + len(losses)
    win_rate = (len(wins) / resolved_count * 100) if resolved_count > 0 else 0.0
    
    fee_cost = (getattr(config, "BINANCE_FEE_PCT", 0.075) + getattr(config, "SLIPPAGE_PCT", 0.04)) / 100 * 2
    net_r = sum((z.get("actual_rr") or 0) - fee_cost for z in wins) - sum(1.0 + fee_cost for z in losses)
    net_r += sum((z.get("actual_rr") or 0) - fee_cost for z in breakevens if (z.get("actual_rr") or 0) > 0)
    
    gross_profit = sum(z.get("actual_rr") or 0 for z in wins) + sum(z.get("actual_rr") or 0 for z in breakevens if (z.get("actual_rr") or 0) > 0)
    gross_loss = len(losses) * 1.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 1.0)
    pf_str = f"{profit_factor:.2f}" if profit_factor != float("inf") else "inf"
    
    updated_pkt = tz.format_pkt(now_utc)
    updated_utc = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append(START_MARKER)
    lines.append(f"> **Last Engine Sync:** `{updated_pkt}` (`{updated_utc}`) | **Cycle:** `{day_str}`")
    lines.append("")
    lines.append("### 📈 Live Performance Key Metrics")
    lines.append("")
    lines.append("| Metric | Value | Status Indicator |")
    lines.append("|---|---|---|")
    lines.append(f"| **Production Phase** | `{day_str}` | 🟢 Active Tracking |")
    lines.append(f"| **Total Setups Qualified** | `{len(all_zones)}` | 🎯 High Confluence (>=75/100) |")
    lines.append(f"| **Resolved Trades** | `{resolved_count}` ({len(wins)}W / {len(losses)}L / {len(breakevens)}BE) | ⚖️ Real Execution Cost Modeled |")
    lines.append(f"| **Cumulative Win Rate** | **`{win_rate:.1f}%`** | {'🟢 Profitable' if win_rate >= 50 else '🟡 Calibrating'} |")
    lines.append(f"| **Net Realized P&L** | **`{net_r:+.2f} R`** | {'🟢 Positive Expectancy' if net_r >= 0 else '🔴 Drawdown Managed'} |")
    lines.append(f"| **Profit Factor** | **`{pf_str}`** | Target: > 1.50 |")
    lines.append(f"| **Active / Pending Setups** | `{len(pending)}` open positions | Max 3 Concurrent Allowed |")
    lines.append("")
    
    # Active Trades Table
    lines.append("### 🔴 Active & Monitored Trades Live Tracker")
    lines.append("")
    if pending:
        lines.append("| ID | Coin | TF | Status | Stage / Position | Entry 1 (61.8%) | Entry 2 (78.6%) | Stop Loss | Target 1 (TP1) | Target 2 (TP2) | R:R | Created Time (PKT) |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for z in pending:
            created_t = tz.format_pkt(datetime.fromisoformat(z['created_at'])) if z.get('created_at') else "N/A"
            status_badge = f"🟡 **{z['status']}**" if z['status'] == "ACTIVE" else f"⏳ {z['status']}"
            e1 = z.get("entry_1") or z.get("entry_price")
            e2 = z.get("entry_2") or z.get("entry_price")
            tp1 = z.get("tp1_price") or z.get("target_price")
            tp2 = z.get("tp2_price") or 0.0
            rr = z.get("actual_rr") or 0.0

            if z["status"] == "PENDING":
                stage_str = "⏳ Pending Retracement"
            else:
                sold = float(z.get("sold_pct") or 0.0)
                fill = z.get("fill_type") or "SINGLE_618"
                tier_str = "$50 (61.8%)" if fill == "SINGLE_618" else "$100 (61.8%+78.6%)"
                if z.get("is_tp1_alert_sent") or sold >= 80.0:
                    stage_str = f"💰 **TP1 Hit** (80% Sold, 20% Runner)"
                elif z.get("is_be_alert_sent") or sold >= 50.0:
                    stage_str = f"🛡️ **BE Secured** (50% Sold, Risk-Free)"
                else:
                    stage_str = f"🟡 In Trade ({tier_str})"

            lines.append(f"| #{z['id']} | **{z['coin']}** | `{z['timeframe']}` | {status_badge} | {stage_str} | `{e1:.4f}` | `{e2:.4f}` | `{z['stop_price']:.4f}` | `{tp1:.4f}` | `{tp2:.4f}` | 1:{rr:.2f} | {created_t} |")
    else:
        lines.append("> *Abhi market mein koi active/pending trade nahi hai — engine har 5 minute baad high-confluence OTE setups dhoond raha hai.*")
    lines.append("")
    
    # Closed Trades History Table
    resolved_trades = [z for z in all_zones if z["status"] in ("WIN", "LOSS", "BREAKEVEN", "TIMEOUT", "EXPIRED")]
    lines.append("### 📜 Recent Closed Trades Ledger (Day 1 se Aaj Tak)")
    lines.append("")
    if resolved_trades:
        lines.append("| ID | Coin | TF | Result | Realized P&L ($100 Base) | Entry Price | Target 1 | Stop Loss | Resolved Time (PKT) |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for z in reversed(resolved_trades[-10:]):
            res = z["status"]
            if res == "WIN":
                badge = "🟢 **WIN (Target Hit)**"
            elif res == "LOSS":
                badge = "🔴 **LOSS (SL Hit)**"
            elif res == "BREAKEVEN":
                badge = "⚪ **BREAKEVEN (Profit Locked)**"
            elif res == "TIMEOUT":
                badge = "⏱️ **TIMEOUT (24h Auto-Exit)**"
            else:
                badge = f"⚪ {res}"

            if z.get("realized_pnl_usd") is not None and z.get("realized_pnl_usd") != 0.0:
                pnl_u = z["realized_pnl_usd"]
                pnl_p = z.get("realized_pnl_pkr") or (pnl_u * 280.0)
                pnl_display = f"**{pnl_u:+.2f} USDT** (Rs. {pnl_p:+,.0f})"
            else:
                rr = z.get("actual_rr") or 0.0
                if res == "WIN":
                    pnl_display = f"**+${rr*10:.2f} USDT**"
                elif res == "BREAKEVEN":
                    pnl_display = "**+$2.50 USDT** (Risk-Free)"
                elif res == "LOSS":
                    pnl_display = "**-$10.00 USDT**"
                else:
                    pnl_display = "0.00 USDT"

            resolved_t = tz.format_pkt(datetime.fromisoformat(z['resolved_at'])) if z.get('resolved_at') else "N/A"
            lines.append(f"| #{z['id']} | **{z['coin']}** | `{z['timeframe']}` | {badge} | {pnl_display} | `{z['entry_price']:.4f}` | `{z['target_price']:.4f}` | `{z['stop_price']:.4f}` | {resolved_t} |")
    else:
        lines.append("> *Abhi tak koi trade close nahi hui hai (Fresh 15-day cycle active).*")
    lines.append("")
    lines.append(END_MARKER)
    
    return "\n".join(lines)


def update_readme_dashboard(readme_path: str = "README.md"):
    if not os.path.exists(readme_path):
        return
        
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    dashboard_md = generate_dashboard_markdown()
    
    if START_MARKER in content and END_MARKER in content:
        start_idx = content.find(START_MARKER)
        end_idx = content.find(END_MARKER) + len(END_MARKER)
        new_content = content[:start_idx] + dashboard_md + content[end_idx:]
    else:
        # Insert right after the top badges / intro
        split_point = "## 📊 Live System Status & Dashboard"
        if split_point in content:
            parts = content.split(split_point, 1)
            new_content = parts[0] + split_point + "\n\n" + dashboard_md + "\n\n" + parts[1]
        else:
            new_content = content + "\n\n" + dashboard_md
            
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("README.md Live Tracker Dashboard updated successfully!")


if __name__ == "__main__":
    update_readme_dashboard()
