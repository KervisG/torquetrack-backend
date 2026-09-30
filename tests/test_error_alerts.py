"""Alertas por correo de los errores del servidor (`config/error_alerts.py`).

El handler cuelga del root en `LOGGING`, así que cubre los 500 (`django.request`)
y todo `logger.error`/`logger.exception`. Resend se falsea en el adaptador
(`apps.integrations.email.resend.send_email`) con un doble propio que acepta
`text` y `timeout`; ningún test sale a la red.

Los tests unitarios usan un logger propio con `propagate = False` para que el
handler del root (el de settings) no mande un segundo correo. El límite de un
correo por firma cada 15 minutos vive en el cache compartido (`DatabaseCache`),
que se limpia alrededor de cada test junto con el respaldo en memoria.
"""
import logging

import pytest
from django.core.cache import cache
from django.db import DatabaseError
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import path

from config import error_alerts
from config.error_alerts import ErrorEmailHandler

RESEND_SEND_EMAIL = "apps.integrations.email.resend.send_email"
OPERATOR = "ops@example.com"


class RecordingResend:
    """`resend.send_email` falso que guarda cada llamada tal cual."""

    def __init__(self, on_send=None):
        self.calls = []
        self.on_send = on_send

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        if self.on_send:
            self.on_send()
        return {"sent": True, "id": "email_alert"}


@pytest.fixture
def clean_rate_limit(db):
    cache.clear()
    error_alerts._local_last_sent.clear()
    yield
    cache.clear()
    error_alerts._local_last_sent.clear()


@pytest.fixture
def alerts_enabled(settings, clean_rate_limit):
    settings.ERROR_ALERT_EMAILS = [OPERATOR]
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "TorqueTrack <no-reply@example.com>"
    return settings


@pytest.fixture
def fake_resend(monkeypatch):
    fake = RecordingResend()
    monkeypatch.setattr(RESEND_SEND_EMAIL, fake.send_email)
    return fake


@pytest.fixture
def alert_logger():
    logger = logging.getLogger("tests.error_alerts.subject")
    handler = ErrorEmailHandler()
    logger.addHandler(handler)
    previous_propagate, previous_level = logger.propagate, logger.level
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    yield logger
    logger.removeHandler(handler)
    logger.propagate = previous_propagate
    logger.setLevel(previous_level)


def _raise_value_error():
    raise ValueError("boom")


def _raise_key_error():
    raise KeyError("missing")


def test_an_error_sends_one_plain_text_alert(alerts_enabled, fake_resend, alert_logger):
    try:
        _raise_value_error()
    except ValueError:
        alert_logger.exception("Payment sync failed for %s", "O1001")

    assert len(fake_resend.calls) == 1
    call = fake_resend.calls[0]
    assert call["to"] == [OPERATOR]
    assert call["subject"] == (
        "[TorqueTrack] ERROR tests.error_alerts.subject: Payment sync failed for O1001"
    )
    assert "html" not in call
    assert call["timeout"] == 5
    body = call["text"]
    assert "Level: ERROR" in body
    assert "Logger: tests.error_alerts.subject" in body
    assert "Message: Payment sync failed for O1001" in body
    assert "UTC" in body
    assert "Traceback (most recent call last)" in body
    assert "ValueError: boom" in body


def test_warnings_and_info_are_ignored(alerts_enabled, monkeypatch, alert_logger):
    monkeypatch.setattr(RESEND_SEND_EMAIL, _forbidden_send)

    alert_logger.warning("Low stock")
    alert_logger.info("Started")


def _forbidden_send(**kwargs):
    raise AssertionError("No alert email must be sent")


def test_same_signature_is_sent_once_per_window(alerts_enabled, fake_resend, alert_logger):
    for _ in range(3):
        try:
            _raise_value_error()
        except ValueError:
            alert_logger.exception("Payment sync failed")

    alert_logger.error("Order %s failed", "O1")
    alert_logger.error("Order %s failed", "O2")

    # Misma excepción y mismo frame: una sola alerta; mismo template sin
    # excepción: otra sola, aunque cambien los argumentos.
    assert len(fake_resend.calls) == 2


def test_different_signatures_each_send(alerts_enabled, fake_resend, alert_logger):
    try:
        _raise_value_error()
    except ValueError:
        alert_logger.exception("Sync failed")
    try:
        _raise_key_error()
    except KeyError:
        alert_logger.exception("Sync failed")
    alert_logger.error("Another failure")

    assert len(fake_resend.calls) == 3


def test_the_rate_limit_is_shared_through_the_cache(alerts_enabled, fake_resend, alert_logger):
    # Otro worker ya mandó esta alerta: el respaldo local está vacío, pero la
    # clave del cache compartido la frena.
    alert_logger.error("Shared failure")
    error_alerts._local_last_sent.clear()
    other_worker = ErrorEmailHandler()
    record = alert_logger.makeRecord(
        alert_logger.name, logging.ERROR, __file__, 1, "Shared failure", (), None
    )
    other_worker.handle(record)

    assert len(fake_resend.calls) == 1


def test_no_recipients_disables_the_handler(settings, monkeypatch, alert_logger):
    settings.ERROR_ALERT_EMAILS = []
    monkeypatch.setattr(RESEND_SEND_EMAIL, _forbidden_send)

    def _no_cache(*args, **kwargs):
        raise AssertionError("A disabled handler must not touch the cache")

    monkeypatch.setattr(error_alerts, "cache", _ExplodingCache(_no_cache))

    alert_logger.error("Nobody listens")


def test_disallowed_host_is_ignored(alerts_enabled, monkeypatch):
    monkeypatch.setattr(RESEND_SEND_EMAIL, _forbidden_send)
    handler = ErrorEmailHandler()
    record = logging.getLogger("django.security.DisallowedHost").makeRecord(
        "django.security.DisallowedHost",
        logging.ERROR,
        __file__,
        1,
        "Invalid HTTP_HOST header: %s",
        ("evil.example",),
        None,
    )

    handler.handle(record)


def test_a_failing_provider_neither_raises_nor_recurses(alerts_enabled, monkeypatch, alert_logger):
    calls = []

    def _failing_send(**kwargs):
        calls.append(kwargs)
        # Lo que loguearía un adaptador roto, y un error del mismo logger
        # mientras se manda: ninguno puede disparar otra alerta.
        logging.getLogger("apps.integrations.email.resend").error("Resend exploded")
        alert_logger.error("Error while alerting")
        raise RuntimeError("provider down")

    monkeypatch.setattr(RESEND_SEND_EMAIL, _failing_send)

    alert_logger.error("Original failure")

    assert len(calls) == 1


def test_records_from_the_adapter_logger_are_ignored(alerts_enabled, monkeypatch):
    monkeypatch.setattr(RESEND_SEND_EMAIL, _forbidden_send)
    handler = ErrorEmailHandler()
    for name in ("apps.integrations.email.resend", "config.error_alerts"):
        record = logging.getLogger(name).makeRecord(
            name, logging.ERROR, __file__, 1, "Loop", (), None
        )
        handler.handle(record)


class _ExplodingCache:
    def __init__(self, add):
        self.add = add


def test_a_broken_cache_falls_back_to_in_process_limiting(
    alerts_enabled, fake_resend, monkeypatch, alert_logger
):
    def _db_down(*args, **kwargs):
        raise DatabaseError("connection refused")

    monkeypatch.setattr(error_alerts, "cache", _ExplodingCache(_db_down))

    alert_logger.error("Database is down")
    alert_logger.error("Database is down")
    alert_logger.error("Another failure while down")

    assert len(fake_resend.calls) == 2


def test_the_body_carries_only_method_path_and_user(alerts_enabled, fake_resend, alert_logger, rf):
    request = rf.post(
        "/api/checkout/?token=secret-token&email=pat@example.com",
        data={"password": "hunter2", "card": "4242"},
        HTTP_COOKIE="sessionid=abc123",
        HTTP_AUTHORIZATION="Bearer leaked",
    )

    class _User:
        pk = 42
        is_authenticated = True

    request.user = _User()

    alert_logger.error("Checkout crashed", extra={"request": request})

    body = fake_resend.calls[0]["text"]
    assert "Request: POST /api/checkout/" in body
    assert "User: 42" in body
    leaks = ("secret-token", "token=", "pat@example.com", "hunter2", "4242", "abc123", "leaked")
    for leaked in leaks:
        assert leaked not in body


def test_the_subject_is_one_short_line(alerts_enabled, fake_resend, alert_logger):
    alert_logger.error("First line\nsecond line " + "x" * 300)

    subject = fake_resend.calls[0]["subject"]
    assert "\n" not in subject
    assert len(subject) <= 120
    assert subject.startswith("[TorqueTrack] ERROR tests.error_alerts.subject: First line")


# --- 500 de punta a punta ------------------------------------------------------


def _crashing_view(request):
    raise RuntimeError("unexpected crash")


def _ok_view(request):
    return HttpResponse("ok")


urlpatterns = [
    path("crash/", _crashing_view),
    path("ok/", _ok_view),
]


@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_an_unhandled_exception_in_a_view_sends_exactly_one_alert(alerts_enabled, fake_resend):
    client = Client(raise_request_exception=False)

    response = client.get("/crash/?token=secret-token")

    assert response.status_code == 500
    assert len(fake_resend.calls) == 1
    call = fake_resend.calls[0]
    assert call["subject"].startswith("[TorqueTrack] ERROR django.request: Internal Server Error")
    assert "Request: GET /crash/" in call["text"]
    assert "RuntimeError: unexpected crash" in call["text"]
    assert "secret-token" not in call["text"]

    assert client.get("/ok/").status_code == 200
    assert len(fake_resend.calls) == 1
