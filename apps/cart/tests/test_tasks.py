"""Tarea periódica `apps.cart.tasks.purge_carts` (Celery Beat).

Envuelve `purge_empty_carts`, el mismo service de `manage.py purge_carts`. Bajo
pytest las tareas corren en el proceso (`task_always_eager`, `conftest.py`), así
que `.delay()` no necesita Redis. Se assertea el efecto en la base, el valor de
retorno (lo que el worker muestra en su log) y la línea INFO con el conteo.
"""

import logging

import pytest

from apps.cart.models import Cart
from apps.cart.tasks import purge_carts

ITEM = [{"id": "p1", "qty": 1}]


@pytest.mark.django_db
def test_purge_carts_task_deletes_only_empty_carts_and_returns_the_count():
    Cart.objects.create(id="cart_empty_1", data={"items": []})
    Cart.objects.create(id="cart_empty_2", data={})
    Cart.objects.create(id="cart_full", data={"items": ITEM})

    result = purge_carts.delay()

    assert result.get() == 2
    assert list(Cart.objects.values_list("pk", flat=True)) == ["cart_full"]


@pytest.mark.django_db
def test_purge_carts_task_logs_one_info_line_with_the_count(caplog):
    Cart.objects.create(id="cart_empty", data={"items": []})

    with caplog.at_level(logging.INFO, logger="apps.cart.tasks"):
        purge_carts.apply()

    records = [r for r in caplog.records if r.name == "apps.cart.tasks"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert "1" in records[0].getMessage()


def test_purge_carts_task_has_a_stable_name():
    # `CELERY_BEAT_SCHEDULE` referencia la tarea por este nombre.
    assert purge_carts.name == "apps.cart.tasks.purge_carts"


# --- send_cart_recovery_emails ------------------------------------------------


@pytest.mark.django_db
def test_cart_recovery_task_returns_the_count_and_logs_it(monkeypatch, caplog, settings):
    from datetime import timedelta

    from django.utils import timezone

    from apps.cart.tasks import send_cart_recovery_emails
    from tests.factories import create_user
    from tests.fakes import install_resend

    settings.APP_URL = "https://shop.example.com"
    resend = install_resend(monkeypatch)
    user = create_user("usr_task_recovery")
    Cart.objects.create(
        id="cart_task_recovery",
        user=user,
        data={"items": ITEM, "stage": "CART"},
        updated_at=timezone.now() - timedelta(hours=2),
    )

    with caplog.at_level(logging.INFO, logger="apps.cart.tasks"):
        result = send_cart_recovery_emails.delay()

    assert result.get() == 1
    assert len(resend.sent) == 1
    records = [r for r in caplog.records if r.name == "apps.cart.tasks"]
    assert len(records) == 1
    assert "1" in records[0].getMessage()


def test_cart_recovery_task_has_a_stable_name():
    from apps.cart.tasks import send_cart_recovery_emails

    assert send_cart_recovery_emails.name == "apps.cart.tasks.send_cart_recovery_emails"
