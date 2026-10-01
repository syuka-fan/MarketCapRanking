from datetime import UTC, date, datetime

import pytest

from marketcap.calendar import SEOUL, latest_completed, previous_session, sessions
from marketcap.models import DataError


@pytest.mark.parametrize(("day", "hour"), [(date(2026, 1, 5), 21), (date(2026, 7, 6), 20)])
def test_standard_and_daylight_session_closes(day, hour):
    assert sessions(day, day)[day].hour == hour
    korean_close = sessions(day, day)[day].astimezone(SEOUL)
    assert korean_close.hour == (6 if hour == 21 else 5)


def test_holiday_and_early_close():
    assert sessions(date(2026, 7, 3), date(2026, 7, 3)) == {}
    day = date(2026, 11, 27)
    assert sessions(day, day)[day].hour == 18  # 13:00 New York, standard time.
    assert previous_session(day) == date(2026, 11, 25)


def test_latest_completed_before_after_close_and_korean_tuesday():
    assert latest_completed(datetime(2026, 9, 30, 19, 59, tzinfo=UTC)) == date(2026, 9, 29)
    assert latest_completed(datetime(2026, 9, 30, 20, 0, tzinfo=UTC)) == date(2026, 9, 30)
    assert latest_completed(datetime(2026, 9, 29, 9, 0, tzinfo=SEOUL)) == date(2026, 9, 28)


def test_naive_time_is_rejected():
    with pytest.raises(DataError, match="timezone"):
        latest_completed(datetime(2026, 9, 30))
