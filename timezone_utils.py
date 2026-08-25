"""
Timezone utils — poore system mein internal calculation UTC mein hoti hai
(yeh standard practice hai, kyunke Binance/exchanges bhi UTC use karte hain),
lekin JO BHI insaan ko dikhaya jata hai (reports, emails, start-date input)
Pakistan Time (PKT) mein convert ho kar dikhta hai.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import config

UTC = ZoneInfo("UTC")
PKT = ZoneInfo(config.TIMEZONE)


def parse_pkt_input(datetime_str: str) -> datetime:
    """
    User se aaya hua datetime string (jaise SYSTEM_START_DATETIME env var)
    ko PKT wall-clock time maan kar UTC-aware datetime mein convert karta hai.
    """
    naive = datetime.strptime(datetime_str.strip(), "%Y-%m-%d %H:%M:%S")
    pkt_aware = naive.replace(tzinfo=PKT)
    return pkt_aware.astimezone(UTC)


def to_pkt(dt: datetime) -> datetime:
    """UTC (ya kisi bhi) datetime ko PKT mein convert karta hai display ke liye."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(PKT)


def now_pkt() -> datetime:
    return datetime.now(UTC).astimezone(PKT)


def format_pkt(dt: datetime, fmt: str = "%Y-%m-%d %I:%M %p PKT") -> str:
    return to_pkt(dt).strftime(fmt)


def format_both(dt: datetime, fmt_pkt: str = "%Y-%m-%d %I:%M %p", fmt_utc: str = "%Y-%m-%d %H:%M") -> str:
    """
    Kisi bhi event ka time DONO formats mein ek sath deta hai:
    Pakistan Time (insaan ke padhne ke liye) aur UTC (jo TradingView/exchange
    data ke context mein use hota hai) — taake exact time samajhne mein
    koi confusion na ho.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    pkt_str = dt.astimezone(PKT).strftime(fmt_pkt)
    utc_str = dt.astimezone(UTC).strftime(fmt_utc)
    return f"{pkt_str} PKT  ({utc_str} UTC)"
