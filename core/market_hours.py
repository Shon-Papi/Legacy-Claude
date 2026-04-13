"""
US equity market hours helper.

Provides session status, open/close predicates, and time-to-open for
NYSE/NASDAQ regular hours (9:30 AM – 4:00 PM ET).

Usage:
    from core.market_hours import is_market_open, session_status, minutes_to_open
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Regular session
MARKET_OPEN  = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Extended hours (informational only — bot only trades regular session)
PREMARKET_OPEN       = time(4, 0)
AFTER_HOURS_CLOSE    = time(20, 0)

# NYSE/NASDAQ market holidays 2025–2026
_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1),    # New Year's Day
    date(2025, 1, 20),   # MLK Day
    date(2025, 2, 17),   # Presidents' Day
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 26),   # Memorial Day
    date(2025, 6, 19),   # Juneteenth
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas Day
    # 2026
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas Day
}


def _now_et() -> datetime:
    return datetime.now(ET)


def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _HOLIDAYS


def is_market_open(now: datetime | None = None) -> bool:
    """Return True if NYSE/NASDAQ is in regular session right now."""
    now = now or _now_et()
    if not _is_trading_day(now.date()):
        return False
    t = now.timetz() if now.tzinfo else now.time()
    # Strip timezone from time for comparison
    t_naive = time(t.hour, t.minute, t.second)
    return MARKET_OPEN <= t_naive < MARKET_CLOSE


def is_premarket(now: datetime | None = None) -> bool:
    """Return True if we are in the pre-market window (4:00–9:30 AM ET)."""
    now = now or _now_et()
    if not _is_trading_day(now.date()):
        return False
    t = time(now.hour, now.minute, now.second)
    return PREMARKET_OPEN <= t < MARKET_OPEN


def is_after_hours(now: datetime | None = None) -> bool:
    """Return True if we are in after-hours (4:00–8:00 PM ET)."""
    now = now or _now_et()
    if not _is_trading_day(now.date()):
        return False
    t = time(now.hour, now.minute, now.second)
    return MARKET_CLOSE <= t < AFTER_HOURS_CLOSE


def session_status(now: datetime | None = None) -> str:
    """Return human-readable session status string."""
    now = now or _now_et()
    if is_market_open(now):
        return "OPEN"
    if is_premarket(now):
        return "PRE-MARKET"
    if is_after_hours(now):
        return "AFTER-HOURS"
    return "CLOSED"


def minutes_to_open(now: datetime | None = None) -> int:
    """
    Return minutes until the next regular-session open.
    Returns 0 if the market is currently open.
    """
    now = now or _now_et()
    if is_market_open(now):
        return 0

    # Walk forward day by day to find next trading day
    check = now
    for _ in range(14):
        check = check + timedelta(days=1)
        if _is_trading_day(check.date()):
            open_dt = check.replace(
                hour=MARKET_OPEN.hour,
                minute=MARKET_OPEN.minute,
                second=0,
                microsecond=0,
            )
            delta = open_dt - now
            return max(0, int(delta.total_seconds() / 60))

    return 0  # fallback — should never reach here


def minutes_to_close(now: datetime | None = None) -> int:
    """
    Return minutes until the market closes today.
    Returns 0 if market is not open.
    """
    now = now or _now_et()
    if not is_market_open(now):
        return 0
    close_dt = now.replace(
        hour=MARKET_CLOSE.hour,
        minute=MARKET_CLOSE.minute,
        second=0,
        microsecond=0,
    )
    delta = close_dt - now
    return max(0, int(delta.total_seconds() / 60))
