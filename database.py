"""
Database layer — SQLite. Poore system ka permanent record yahan store hota hai:
zones (qualified aur unke outcomes), rejected_zones (skip hui setups + wajah),
swing_state (locked pivot values, Pine Script ke 'var' jaisa), scan_log, config.
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
    """Pehli baar chalane par tables bana deta hai. Baar baar chalane se koi nuksan nahi."""
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
                zones_rejected INTEGER
            )
        """)


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
            INSERT INTO swing_state (coin, timeframe, swing_high, swing_high_time, swing_low, swing_low_time, last_recorded_zone_price)
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
                 swing_low, swing_high, score, actual_rr, pivot_len, created_at, score_breakdown):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO zones (coin, timeframe, level_name, entry_price, stop_price, target_price,
                                swing_low, swing_high, score, actual_rr, pivot_len, created_at,
                                status, score_breakdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        """, (coin, timeframe, level_name, entry_price, stop_price, target_price,
              swing_low, swing_high, score, actual_rr, pivot_len, created_at,
              json.dumps(score_breakdown)))
        return cur.lastrowid


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
    """
    Saare distinct (coin, timeframe) jinke koi PENDING/ACTIVE zones abhi
    khule hain — fixed coin universe se bahar ho chuke ("legacy") coins ke
    purane zones ko bhi resolve karte rehne ke liye use hota hai, taake
    unka Win/Loss/Timeout result zaya na ho.
    """
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
            "SELECT * FROM zones WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
            (start_iso, end_iso),
        )
        return [dict(r) for r in cur.fetchall()]


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
    """
    Sirf tab naya row insert karta hai jab reason PICHLI baar se DIFFERENT ho
    (ya yeh pehli baar reject ho raha ho). Agar coin consistently same wajah
    se reject hota rahe (jaisa zyada tar hota hai), har 30-min scan pe naya
    duplicate row nahi banega — database chhota aur reports cleaner rahenge.
    """
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

def insert_scan_log(scan_time, coins_scanned, zones_qualified, zones_rejected):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO scan_log (scan_time, coins_scanned, zones_qualified, zones_rejected)
            VALUES (?, ?, ?, ?)
        """, (scan_time, coins_scanned, zones_qualified, zones_rejected))


def get_scan_logs_in_window(start_iso, end_iso):
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM scan_log WHERE scan_time >= ? AND scan_time < ? ORDER BY scan_time",
            (start_iso, end_iso),
        )
        return [dict(r) for r in cur.fetchall()]


def get_processing_cursor(coin, timeframe):
    """Wapas karta hai: 'yahan tak candles process ho chuki hain' ka timestamp, ya None agar pehli baar hai."""
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
