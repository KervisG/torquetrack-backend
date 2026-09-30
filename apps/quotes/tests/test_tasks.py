"""Tarea periódica `apps.quotes.tasks.expire_quotes` (Celery Beat).

Envuelve `expire_stale_quotes`, el mismo service de `manage.py expire_quotes`.
Bajo pytest las tareas corren en el proceso (`task_always_eager`,
`conftest.py`), así que `.delay()` no necesita Redis. Se assertea el efecto en
la base, el valor de retorno y la línea INFO con el conteo.
"""

import logging

import pytest
from django.utils import timezone

from apps.quotes.models import Quote
from apps.quotes.tasks import expire_quotes


def _insert_quote(quote_id, number, status, expires_at):
    now = timezone.now()
    return Quote.objects.create(
        id=quote_id,
        number=number,
        status=status,
        data={},
        created_at=now,
        expires_at=expires_at,
        updated_at=now,
    )


@pytest.mark.django_db
def test_expire_quotes_task_expires_only_stale_open_quotes_and_returns_the_count():
    past = timezone.now() - timezone.timedelta(days=1)
    future = timezone.now() + timezone.timedelta(days=30)
    _insert_quote("quo_a", "Q1", "ACTIVE", past)
    _insert_quote("quo_b", "Q2", "BUILDING", past)
    _insert_quote("quo_c", "Q3", "CONVERTED", past)
    _insert_quote("quo_d", "Q4", "ACTIVE", future)

    result = expire_quotes.delay()

    assert result.get() == 2
    assert dict(Quote.objects.values_list("pk", "status")) == {
        "quo_a": "EXPIRED",
        "quo_b": "EXPIRED",
        "quo_c": "CONVERTED",
        "quo_d": "ACTIVE",
    }


@pytest.mark.django_db
def test_expire_quotes_task_logs_one_info_line_with_the_count(caplog):
    with caplog.at_level(logging.INFO, logger="apps.quotes.tasks"):
        result = expire_quotes.apply()

    assert result.get() == 0
    records = [r for r in caplog.records if r.name == "apps.quotes.tasks"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert "0" in records[0].getMessage()


def test_expire_quotes_task_has_a_stable_name():
    # `CELERY_BEAT_SCHEDULE` referencia la tarea por este nombre.
    assert expire_quotes.name == "apps.quotes.tasks.expire_quotes"
