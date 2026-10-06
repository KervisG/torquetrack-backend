"""Correo de recuperación de carrito abandonado (`send_abandoned_cart_emails`,
que corre la tarea `apps.cart.tasks.send_cart_recovery_emails` cada hora).

Resend se reemplaza con `install_resend`/`forbid_resend` de `tests/fakes.py`.
Reglas que se assertean a propósito:

- Solo un carrito de una cuenta activa, con items, en etapa CART y abandonado
  según `classify_cart` (más de `CART_IDLE_WINDOW` sin cambios). Un invitado
  no tiene email: se salta.
- Sale UNA vez por carrito: la marca `recovery_email_sent_at` es columna (cada
  `PUT` reescribe `data`) y se toma antes de enviar. Si Resend falla, la marca
  se libera para reintentar en la corrida siguiente.
- Un carrito abandonado hace más de `RECOVERY_MAX_AGE` no se escribe: evita una
  ráfaga de correos viejos el día del deploy.
- Enviar no cambia `updated_at`: el panel lo sigue viendo abandonado.
"""
import logging
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.cart.models import Cart
from apps.cart.services.recovery import RECOVERY_MAX_AGE, send_abandoned_cart_emails
from tests.factories import create_user
from tests.fakes import FakeResend, forbid_resend, install_resend

ITEMS = [{"id": "pump", "qty": 2, "title": "Bosch CP3 Injection Pump", "partNumber": "0445020150"}]


@pytest.fixture(autouse=True)
def _app_url(settings):
    settings.APP_URL = "https://shop.example.com"


def _cart(cart_id, *, user=None, idle=timedelta(hours=2), stage="CART", items=None, **fields):
    return Cart.objects.create(
        id=cart_id,
        user=user,
        data={"items": ITEMS if items is None else items, "stage": stage},
        updated_at=timezone.now() - idle,
        **fields,
    )


@pytest.mark.django_db
def test_emails_an_abandoned_account_cart_once(monkeypatch):
    resend = install_resend(monkeypatch)
    user = create_user("usr_pat", email="pat@example.com", first_name="Pat")
    _cart("cart_pat", user=user)

    first = send_abandoned_cart_emails()
    second = send_abandoned_cart_emails()

    assert (first, second) == (1, 0)
    assert len(resend.sent) == 1
    email = resend.sent[0]
    assert email["to"] == ["pat@example.com"]
    assert email["subject"] == "You left something in your TorqueTrack cart"
    assert "Hi Pat," in email["html"]
    assert "Bosch CP3 Injection Pump" in email["html"]
    assert 'href="https://shop.example.com/cart"' in email["html"]
    assert Cart.objects.get(pk="cart_pat").recovery_email_sent_at is not None


@pytest.mark.django_db
def test_sending_keeps_the_cart_abandoned(monkeypatch):
    install_resend(monkeypatch)
    user = create_user("usr_keep")
    cart = _cart("cart_keep", user=user)

    send_abandoned_cart_emails()

    assert Cart.objects.get(pk="cart_keep").updated_at == cart.updated_at


@pytest.mark.django_db
def test_skips_carts_that_do_not_qualify(monkeypatch):
    forbid_resend(monkeypatch)
    _cart("cart_guest")
    _cart("cart_recent", user=create_user("usr_recent"), idle=timedelta(minutes=5))
    _cart("cart_checkout", user=create_user("usr_checkout"), stage="CHECKOUT")
    _cart("cart_quote", user=create_user("usr_quote"), stage="BUILDING_QUOTE")
    _cart("cart_empty", user=create_user("usr_empty"), items=[])
    _cart("cart_inactive", user=create_user("usr_inactive", active=False))
    _cart("cart_sent", user=create_user("usr_sent"), recovery_email_sent_at=timezone.now())
    _cart("cart_stale", user=create_user("usr_stale"), idle=RECOVERY_MAX_AGE + timedelta(hours=1))

    assert send_abandoned_cart_emails() == 0


@pytest.mark.django_db
def test_a_failed_send_releases_the_marker_for_the_next_run(monkeypatch, caplog):
    install_resend(monkeypatch, FakeResend({"sent": False, "reason": "not configured"}))
    _cart("cart_fail", user=create_user("usr_fail"))

    with caplog.at_level(logging.WARNING, logger="apps.cart.services.recovery"):
        assert send_abandoned_cart_emails() == 0

    assert Cart.objects.get(pk="cart_fail").recovery_email_sent_at is None
    assert "cart_fail" in caplog.text
    # Sin datos del cliente en el log.
    assert "usr_fail@example.com" not in caplog.text
