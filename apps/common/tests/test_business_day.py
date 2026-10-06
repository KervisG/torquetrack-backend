"""`apps/common/business_day.py`: "hoy" es el día calendario de la tienda
(`settings.STORE_TIME_ZONE`, Florida), no el de UTC. Se assertea a propósito
el borde de las 8 p. m. ET, cuando UTC ya pasó al día siguiente, y los días de
23 y 25 horas del cambio de horario."""
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import override_settings

from apps.common.business_day import (
    store_day_bounds,
    store_timezone,
    store_today,
    store_today_bounds,
)

NEW_YORK = ZoneInfo("America/New_York")


def test_the_default_store_time_zone_is_florida():
    assert store_timezone() == NEW_YORK


@override_settings(STORE_TIME_ZONE="America/Chicago")
def test_the_store_time_zone_comes_from_settings():
    assert store_timezone() == ZoneInfo("America/Chicago")


def test_late_evening_in_florida_is_still_today_even_if_utc_is_tomorrow():
    # 23:30 EDT del 5 de octubre = 03:30 UTC del 6.
    now = datetime(2026, 10, 6, 3, 30, tzinfo=UTC)

    assert store_today(now) == date(2026, 10, 5)
    start, end = store_today_bounds(now)
    assert start == datetime(2026, 10, 5, tzinfo=NEW_YORK)
    assert end == datetime(2026, 10, 6, tzinfo=NEW_YORK)
    assert start.astimezone(UTC) == datetime(2026, 10, 5, 4, tzinfo=UTC)


def test_dst_days_are_23_and_25_hours_long():
    spring_start, spring_end = store_day_bounds(date(2026, 3, 8))
    fall_start, fall_end = store_day_bounds(date(2026, 11, 1))

    # En UTC: restar dos datetimes de la misma zona da la diferencia de reloj.
    assert spring_end.astimezone(UTC) - spring_start.astimezone(UTC) == timedelta(hours=23)
    assert fall_end.astimezone(UTC) - fall_start.astimezone(UTC) == timedelta(hours=25)
