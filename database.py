"""
Database layer — SQLite. Store permanent records for zones, rejected_zones,
swing_state, processing_cursor, scan_log (including dynamic coin_list), and config.
"""

import sqlite3
import json
from datetime import datetime, timezone
from contextlib import contextmanager

import config


def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                level_name TEXT,
                entry_price REAL,
                stop_price REAL,
                target_price REAL,
                swing_low REAL,
                swing_high REAL,
                score INTEGER,
                actual_rr REAL,
                pivot_len INTEGER,
                created_at TEXT,
                touched_at TEXT,
                resolved_at TEXT,
                status TEXT DEFAULT 'PENDING',
                score_breakdown TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rejected_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                reason_code TEXT,
                reason_detail TEXT,
                score INTEGER,
                actual_rr REAL,
                checked_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rejection_state (
                coin TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                reason_code TEXT,
                last_checked_at TEXT,
                PRIMARY KEY (coin, timeframe)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS processing_cursor (
                coin TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                last_processed_time TEXT,
                PRIMARY KEY (coin, timeframe)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS swing_state (
                coin TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                swing_high REAL,
                swing_high_time TEXT,
                swing_low REAL,
                swing_low_time TEXT,
                last_recorded_zone_price REAL,
                PRIMARY KEY (coin, timeframe)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scan_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_time TEXT,
                coins_scanned INTEGER,
                zones_qualified INTEGER,
                zones_rejected INTEGER,
                coin_list TEXT
            )
        """)
        # Safe migration if table exists without new columns
        for col_def in [
            ("scan_log", "coin_list TEXT"),
            ("zones", "entry_1 REAL"),
            ("zones", "entry_2 REAL"),
            ("zones", "tp1_price REAL"),
            ("zones", "tp2_price REAL"),
            ("zones", "is_alert_sent INTEGER DEFAULT 0"),
            ("zones", "tier1_filled INTEGER DEFAULT 0"),
            ("zones", "tier2_filled INTEGER DEFAULT 0"),
            ("zones", "partial_tp_hit INTEGER DEFAULT 0"),
            ("zones", "post_sl_behavior TEXT"),
            ("zones", "post_sl_details TEXT"),
            ("zones", "diagnosis TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]};")
            except Exception:
                pass  # column already exists


# ---------------- system_config helpers ----------------

def get_config(key, default=None):
    with db_cursor() as cur:
        cur.execute("SELECT value FROM system_config WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def set_config(key, value):
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO system_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


# ---------------- swing_state helpers ----------------

def get_swing_state(coin, timeframe):
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM swing_state WHERE coin = ? AND timeframe = ?",
            (coin, timeframe),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def set_swing_state(coin, timeframe, swing_high, swing_high_time, swing_low, swing_low_time, last_recorded_zone_price):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO swing_state (coin, timeframe, swing_high, swing_high_time,
                                     swing_low, swing_low_time, last_recorded_zone_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(coin, timeframe) DO UPDATE SET
                swing_high = excluded.swing_high,
                swing_high_time = excluded.swing_high_time,
                swing_low = excluded.swing_low,
                swing_low_time = excluded.swing_low_time,
                last_recorded_zone_price = excluded.last_recorded_zone_price
        """, (coin, timeframe, swing_high, swing_high_time, swing_low, swing_low_time, last_recorded_zone_price))


# ---------------- zones helpers ----------------

def insert_zone(coin, timeframe, level_name, entry_price, stop_price, target_price,
                swing_low, swing_high, score, actual_rr, pivot_len, created_at,
                score_breakdown=None, entry_1=None, entry_2=None, tp1_price=None, tp2_price=None):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO zones (coin, timeframe, level_name, entry_price, stop_price, target_price,
                                swing_low, swing_high, score, actual_rr, pivot_len, created_at,
                                status, score_breakdown, entry_1, entry_2, tp1_price, tp2_price, is_alert_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, 0)
        """, (coin, timeframe, level_name, entry_price, stop_price, target_price,
              swing_low, swing_high, score, actual_rr, pivot_len, created_at,
              json.dumps(score_breakdown) if score_breakdown else None, entry_1, entry_2, tp1_price, tp2_price))
        return cur.lastrowid


def mark_zone_alert_sent(zone_id):
    with db_cursor() as cur:
        cur.execute("UPDATE zones SET is_alert_sent=1 WHERE id=?", (zone_id,))


def get_pending_zones(coin=None, timeframe=None):
    query = "SELECT * FROM zones WHERE status IN ('PENDING', 'ACTIVE')"
    params = []
    if coin:
        query += " AND coin = ?"
        params.append(coin)
    if timeframe:
        query += " AND timeframe = ?"
        params.append(timeframe)
    with db_cursor() as cur:
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def get_distinct_pending_coin_timeframes():
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT coin, timeframe FROM zones WHERE status IN ('PENDING', 'ACTIVE')")
        return [(r["coin"], r["timeframe"]) for r in cur.fetchall()]


def update_zone_status(zone_id, status, touched_at=None, resolved_at=None):
    with db_cursor() as cur:
        if touched_at and resolved_at:
            cur.execute("UPDATE zones SET status=?, touched_at=?, resolved_at=? WHERE id=?",
                        (status, touched_at, resolved_at, zone_id))
        elif touched_at:
            cur.execute("UPDATE zones SET status=?, touched_at=? WHERE id=?",
                        (status, touched_at, zone_id))
        elif resolved_at:
            cur.execute("UPDATE zones SET status=?, resolved_at=? WHERE id=?",
                        (status, resolved_at, zone_id))
        else:
            cur.execute("UPDATE zones SET status=? WHERE id=?", (status, zone_id))


def get_zones_in_window(start_iso, end_iso):
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM zones WHERE created_at >= ? AND created_at < ? ORDER BY created_at ASC",
            (start_iso, end_iso),
        )
        return [dict(r) for r in cur.fetchall()]


def get_all_zones():
    """Day 1 se aaj tak ke tamam recorded zones return karta hai."""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM zones ORDER BY created_at ASC")
        return [dict(r) for r in cur.fetchall()]


def get_daily_zone_count(date_str: str) -> int:
    """Returns count of zones created on the given date (YYYY-MM-DD)."""
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM zones WHERE created_at LIKE ?", (f"{date_str}%",))
        row = cur.fetchone()
        return row["count"] if row else 0


def get_daily_realized_loss_count(date_str: str) -> int:
    """Returns count of resolved losses on the given date (YYYY-MM-DD)."""
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM zones WHERE status='LOSS' AND resolved_at LIKE ?", (f"{date_str}%",))
        row = cur.fetchone()
        return row["count"] if row else 0


def get_active_zones_count() -> int:
    """Returns count of currently PENDING or ACTIVE trades across portfolio."""
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM zones WHERE status IN ('PENDING', 'ACTIVE')")
        row = cur.fetchone()
        return row["count"] if row else 0


def get_recent_consecutive_losses() -> int:
    """Returns count of recent consecutive losses."""
    with db_cursor() as cur:
        cur.execute("SELECT status FROM zones WHERE status IN ('WIN', 'LOSS', 'BREAKEVEN') ORDER BY resolved_at DESC LIMIT 10")
        rows = cur.fetchall()
        consec = 0
        for r in rows:
            if r["status"] == "LOSS":
                consec += 1
            else:
                break
        return consec


def update_zone_post_sl_info(zone_id: int, behavior: str, details: str):
    """Loss trade ke baad price action diagnosis (Fakeout vs Dump) save karta hai."""
    with db_cursor() as cur:
        cur.execute("UPDATE zones SET post_sl_behavior=?, post_sl_details=? WHERE id=?",
                    (behavior, details, zone_id))


# ---------------- rejected_zones helpers ----------------

def get_rejection_state(coin, timeframe):
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM rejection_state WHERE coin = ? AND timeframe = ?",
            (coin, timeframe),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def set_rejection_state(coin, timeframe, reason_code, checked_at):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO rejection_state (coin, timeframe, reason_code, last_checked_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(coin, timeframe) DO UPDATE SET
                reason_code = excluded.reason_code,
                last_checked_at = excluded.last_checked_at
        """, (coin, timeframe, reason_code, checked_at))


def insert_rejected_zone_deduped(coin, timeframe, reason_code, reason_detail, score, actual_rr, checked_at):
    prev = get_rejection_state(coin, timeframe)
    reason_changed = prev is None or prev["reason_code"] != reason_code

    if reason_changed:
        with db_cursor() as cur:
            cur.execute("""
                INSERT INTO rejected_zones (coin, timeframe, reason_code, reason_detail, score, actual_rr, checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (coin, timeframe, reason_code, reason_detail, score, actual_rr, checked_at))

    set_rejection_state(coin, timeframe, reason_code, checked_at)
    return reason_changed


def get_rejected_in_window(start_iso, end_iso):
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM rejected_zones WHERE checked_at >= ? AND checked_at < ? ORDER BY checked_at",
            (start_iso, end_iso),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------- scan_log helpers ----------------

def insert_scan_log(scan_time, coins_scanned, zones_qualified, zones_rejected, coin_list=None):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO scan_log (scan_time, coins_scanned, zones_qualified, zones_rejected, coin_list)
            VALUES (?, ?, ?, ?, ?)
        """, (scan_time, coins_scanned, zones_qualified, zones_rejected, coin_list))


def get_scan_logs_in_window(start_iso, end_iso):
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM scan_log WHERE scan_time >= ? AND scan_time < ? ORDER BY scan_time",
            (start_iso, end_iso),
        )
        return [dict(r) for r in cur.fetchall()]


def get_processing_cursor(coin, timeframe):
    with db_cursor() as cur:
        cur.execute(
            "SELECT last_processed_time FROM processing_cursor WHERE coin = ? AND timeframe = ?",
            (coin, timeframe),
        )
        row = cur.fetchone()
        return row["last_processed_time"] if row else None


def set_processing_cursor(coin, timeframe, last_processed_time):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO processing_cursor (coin, timeframe, last_processed_time)
            VALUES (?, ?, ?)
            ON CONFLICT(coin, timeframe) DO UPDATE SET
                last_processed_time = excluded.last_processed_time
        """, (coin, timeframe, last_processed_time))


def now_iso():
    return datetime.now(timezone.utc).isoformat()
