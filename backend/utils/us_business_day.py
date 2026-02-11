"""
US market calendar: business days (weekdays excluding US market holidays).
Used for overnight window and session_label rules (e.g. intraday-by-time only on business days).
"""
from datetime import date, datetime
from typing import Set

# US Market Holidays (2025-2026)
# Note: This is a simplified list. Actual holidays may vary by exchange.
US_MARKET_HOLIDAYS: Set[date] = {
    # 2025
    datetime(2025, 1, 1).date(),   # New Year's Day
    datetime(2025, 1, 20).date(),  # Martin Luther King Jr. Day
    datetime(2025, 2, 17).date(),  # Presidents' Day
    datetime(2025, 4, 18).date(),  # Good Friday
    datetime(2025, 5, 26).date(),  # Memorial Day
    datetime(2025, 6, 19).date(),  # Juneteenth
    datetime(2025, 7, 4).date(),   # Independence Day
    datetime(2025, 9, 1).date(),   # Labor Day
    datetime(2025, 11, 27).date(), # Thanksgiving
    datetime(2025, 12, 25).date(), # Christmas
    # 2026
    datetime(2026, 1, 1).date(),   # New Year's Day
    datetime(2026, 1, 19).date(),  # Martin Luther King Jr. Day
    datetime(2026, 2, 16).date(),  # Presidents' Day
    datetime(2026, 4, 3).date(),   # Good Friday
    datetime(2026, 5, 25).date(),  # Memorial Day
    datetime(2026, 6, 19).date(),  # Juneteenth
    datetime(2026, 7, 3).date(),   # Independence Day (observed)
    datetime(2026, 9, 7).date(),   # Labor Day
    datetime(2026, 11, 26).date(), # Thanksgiving
    datetime(2026, 12, 25).date(), # Christmas
}


def is_us_business_day(d: date) -> bool:
    """
    True if d is a US market business day (Monday–Friday and not a US market holiday).
    """
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if d in US_MARKET_HOLIDAYS:
        return False
    return True
