"""Día de negocio de la tienda: "hoy" es el día calendario en
`settings.STORE_TIME_ZONE` (la tienda está en Florida), no en UTC.

`settings.TIME_ZONE` sigue en UTC (lo usan Celery y los timestamps); esta zona
solo decide dónde se corta el día de las métricas del panel ("Sales today", la
analítica) y del filtro `date=today` de los pedidos. Los límites se arman con
`datetime.combine` en la zona, así un día de cambio de horario dura 23 o 25
horas.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def store_timezone() -> ZoneInfo:
    return ZoneInfo(settings.STORE_TIME_ZONE)


def store_today(now: datetime | None = None) -> date:
    return timezone.localtime(now or timezone.now(), store_timezone()).date()


def store_day_bounds(day: date) -> tuple[datetime, datetime]:
    """[medianoche del día, medianoche del siguiente) en la zona de la tienda."""
    tz = store_timezone()
    start = datetime.combine(day, time.min, tz)
    return start, datetime.combine(day + timedelta(days=1), time.min, tz)


def store_today_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    return store_day_bounds(store_today(now))
