from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

from marketcap.models import DataError

SEOUL = ZoneInfo("Asia/Seoul")
NEW_YORK = ZoneInfo("America/New_York")


@lru_cache(maxsize=128)
def sessions(start: date, end: date) -> dict[date, datetime]:
    if end < start:
        return {}
    schedule = mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)
    return {index.date(): row.market_close.to_pydatetime() for index, row in schedule.iterrows()}


def latest_completed(now: datetime) -> date:
    if now.tzinfo is None:
        raise DataError("Current time must include a timezone")
    local_day = now.astimezone(NEW_YORK).date()
    complete = [
        d
        for d, close in sessions(local_day - timedelta(days=45), local_day).items()
        if close <= now.astimezone(UTC)
    ]
    if not complete:
        raise DataError("No completed trading session found")
    return max(complete)


def previous_session(day: date) -> date:
    return max(sessions(day - timedelta(days=45), day - timedelta(days=1)))


def regular_session_open(now: datetime) -> bool:
    day = now.astimezone(NEW_YORK).date()
    schedule = mcal.get_calendar("NYSE").schedule(start_date=day, end_date=day)
    return any(row.market_open <= now < row.market_close for row in schedule.itertuples())
