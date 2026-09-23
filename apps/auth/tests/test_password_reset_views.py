"""Ni el body ni el tiempo de respuesta pueden revelar qué correos tienen
cuenta: el pedido siempre responde lo mismo y el correo sale fuera del request."""
import pytest
from django.contrib.auth.hashers import check_password
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auth.models import AccountToken, User
from apps.auth.services import issue_account_token
from apps.auth.utils.background import run_in_background as real_run_in_background
from apps.auth.utils.throttling import (
    PasswordResetAccountRateThrottle,
    PasswordResetConfirmRateThrottle,
    PasswordResetRateThrottle,
)
from tests.factories import DEFAULT_PASSWORD, create_user, session_client
from tests.fakes import SlowResend, forbid_resend, install_resend

NEW_PASSWORD = "Fresh-Injector-2026!"
NEUTRAL_BODY = {
    "ok": True,
    "message": "If an account exists for that email, we sent a link to reset the password.",
}


@pytest.fixture(autouse=True)
def _clear_throttle_history(db):
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _send_emails_inline(monkeypatch):
    """Los correos de cuenta salen en un hilo aparte (`run_in_background`).
    Aquí se ejecutan en línea para que el test lea el payload apenas vuelve la
    respuesta y para que un `AssertionError` de `_no_email` falle el request
    en lugar de quedar en el log del hilo. Los tests de `*_outside_the_request`
    restauran el hilo real."""
    monkeypatch.setattr(
        "apps.auth.services.run_in_background", lambda func, *args, **kwargs: func(*args, **kwargs)
    )


@pytest.fixture
def resend(settings, monkeypatch):
    """Resend falso; guarda cada correo enviado."""
    settings.APP_URL = "https://shop.example.com"
    return install_resend(monkeypatch).sent


def _no_email(monkeypatch):
    forbid_resend(monkeypatch)


def _token_from(email_payload) -> str:
    html = email_payload["html"]
    marker = "/reset-password?token="
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


def _confirm(token, password=NEW_PASSWORD):
    return APIClient().post(
        "/api/password-reset/confirm/", {"token": token, "password": password}, format="json"
    )


@pytest.fixture
def slow_resend(settings, monkeypatch):
    settings.APP_URL = "https://shop.example.com"
    monkeypatch.setattr("apps.auth.services.run_in_background", real_run_in_background)
    fake = install_resend(monkeypatch, SlowResend())
    yield fake
    fake.release.set()
    fake.delivered.wait(5)


# --- request --------------------------------------------------------------------


@pytest.mark.django_db
def test_request_sends_the_email_outside_the_request(slow_resend):
    create_user("U_PAT", email="pat@example.com")

    response = APIClient().post("/api/password-reset/", {"email": "pat@example.com"}, format="json")

    assert response.status_code == 200
    assert response.json() == NEUTRAL_BODY
    # La respuesta volvió con Resend todavía bloqueado: no se esperó al proveedor.
    assert slow_resend.sent == []
    slow_resend.release.set()
    assert slow_resend.delivered.wait(5)
    assert slow_resend.sent[0]["to"] == ["pat@example.com"]
    assert slow_resend.sent[0]["subject"] == "Reset your TorqueTrack password"


@pytest.mark.django_db
def test_request_emails_a_reset_link_and_stores_only_the_hash(resend):
    user = create_user("U_PAT", email="pat@example.com", password=DEFAULT_PASSWORD)

    response = APIClient().post(
        "/api/password-reset/", {"email": " Pat@Example.com "}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == NEUTRAL_BODY
    assert len(resend) == 1
    assert resend[0]["to"] == ["pat@example.com"]
    assert resend[0]["subject"] == "Reset your TorqueTrack password"
    assert "https://shop.example.com/reset-password?token=" in resend[0]["html"]
    token = _token_from(resend[0])
    stored = AccountToken.objects.get(user=user, purpose=AccountToken.PASSWORD_RESET)
    assert stored.token_hash != token
    assert token not in stored.token_hash
    assert stored.used_at is None
    assert stored.expires_at > timezone.now() + timezone.timedelta(minutes=55)
    assert stored.expires_at < timezone.now() + timezone.timedelta(minutes=65)


@pytest.mark.django_db
def test_request_for_unknown_email_returns_the_same_body_and_sends_nothing(
    settings, monkeypatch
):
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "no-reply@example.com"
    _no_email(monkeypatch)

    response = APIClient().post(
        "/api/password-reset/", {"email": "nobody@example.com"}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == NEUTRAL_BODY
    assert AccountToken.objects.count() == 0


@pytest.mark.django_db
def test_request_for_inactive_account_sends_nothing(settings, monkeypatch):
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "no-reply@example.com"
    create_user("U_OFF", email="off@example.com", active=False)
    _no_email(monkeypatch)

    response = APIClient().post("/api/password-reset/", {"email": "off@example.com"}, format="json")

    assert response.status_code == 200
    assert response.json() == NEUTRAL_BODY
    assert AccountToken.objects.count() == 0


@pytest.mark.parametrize("body", [{}, {"email": ""}, {"email": "not-an-email"}, {"email": 7}])
@pytest.mark.django_db
def test_request_with_invalid_email_still_returns_the_neutral_body(body, monkeypatch):
    _no_email(monkeypatch)

    response = APIClient().post("/api/password-reset/", body, format="json")

    assert response.status_code == 200
    assert response.json() == NEUTRAL_BODY


@pytest.mark.django_db
def test_request_without_email_provider_still_returns_200(settings, monkeypatch):
    # Adaptador real sin key: devuelve `sent: False` sin llamar a la red.
    settings.RESEND_API_KEY = ""
    settings.FROM_EMAIL = ""
    create_user("U_PAT", email="pat@example.com")

    response = APIClient().post("/api/password-reset/", {"email": "pat@example.com"}, format="json")

    assert response.status_code == 200
    assert response.json() == NEUTRAL_BODY


@pytest.mark.django_db
def test_request_is_rate_limited_by_ip(monkeypatch):
    monkeypatch.setattr(PasswordResetRateThrottle, "rate", "2/min", raising=False)
    _no_email(monkeypatch)
    client = APIClient()

    for index in range(2):
        client.post("/api/password-reset/", {"email": f"a{index}@example.com"}, format="json")
    blocked = client.post("/api/password-reset/", {"email": "a9@example.com"}, format="json")

    assert blocked.status_code == 429


@pytest.mark.django_db
def test_request_is_rate_limited_per_account_across_ips(monkeypatch):
    monkeypatch.setattr(PasswordResetAccountRateThrottle, "rate", "2/hour", raising=False)
    _no_email(monkeypatch)

    for index in range(2):
        APIClient(REMOTE_ADDR=f"10.0.0.{index}").post(
            "/api/password-reset/", {"email": "victim@example.com"}, format="json"
        )
    blocked = APIClient(REMOTE_ADDR="10.0.0.99").post(
        "/api/password-reset/", {"email": "VICTIM@example.com"}, format="json"
    )

    assert blocked.status_code == 429


# --- confirm --------------------------------------------------------------------


@pytest.mark.django_db
def test_confirm_sets_the_password_and_revokes_every_session(resend):
    user = create_user("U_PAT", email="pat@example.com", password=DEFAULT_PASSWORD)
    _, session_key = session_client("U_PAT")
    APIClient().post("/api/password-reset/", {"email": "pat@example.com"}, format="json")
    token = _token_from(resend[0])

    response = _confirm(token)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    user.refresh_from_db()
    assert check_password(NEW_PASSWORD, user.password_hash)
    assert not Session.objects.filter(session_key=session_key).exists()
    assert AccountToken.objects.get(user=user).used_at is not None

    login = APIClient().post(
        "/api/login/", {"email": "pat@example.com", "password": NEW_PASSWORD}, format="json"
    )
    assert login.status_code == 200


@pytest.mark.django_db
def test_confirm_token_cannot_be_reused(resend):
    create_user("U_PAT", email="pat@example.com")
    APIClient().post("/api/password-reset/", {"email": "pat@example.com"}, format="json")
    token = _token_from(resend[0])
    assert _confirm(token).status_code == 200

    second = _confirm(token, password="Another-Pass-2026!")

    assert second.status_code == 400
    assert second.json() == {"error": "Invalid or expired reset link"}


@pytest.mark.django_db
def test_confirm_invalidates_other_outstanding_reset_links(resend):
    create_user("U_PAT", email="pat@example.com")
    client = APIClient()
    client.post("/api/password-reset/", {"email": "pat@example.com"}, format="json")
    client.post("/api/password-reset/", {"email": "pat@example.com"}, format="json")
    first, second = _token_from(resend[0]), _token_from(resend[1])

    assert _confirm(second).status_code == 200

    assert _confirm(first, password="Another-Pass-2026!").status_code == 400


@pytest.mark.django_db
def test_confirm_rejects_an_expired_token():
    user = create_user("U_PAT", email="pat@example.com")
    token = issue_account_token(user, AccountToken.PASSWORD_RESET)
    AccountToken.objects.filter(user=user).update(
        expires_at=timezone.now() - timezone.timedelta(minutes=1)
    )

    response = _confirm(token)

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid or expired reset link"}


@pytest.mark.parametrize("token", ["", "unknown-token", None, 12])
@pytest.mark.django_db
def test_confirm_rejects_missing_or_unknown_token(token):
    response = _confirm(token)

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid or expired reset link"}


@pytest.mark.django_db
def test_confirm_rejects_an_email_verification_token():
    user = create_user("U_PAT", email="pat@example.com")
    token = issue_account_token(user, AccountToken.EMAIL_VERIFICATION)

    assert _confirm(token).status_code == 400


@pytest.mark.django_db
def test_confirm_rejects_a_token_after_the_email_changed():
    user = create_user("U_PAT", email="pat@example.com")
    token = issue_account_token(user, AccountToken.PASSWORD_RESET)
    User.objects.filter(pk=user.pk).update(email="new@example.com")

    assert _confirm(token).status_code == 400


@pytest.mark.django_db
def test_confirm_rejects_a_token_for_an_inactive_account():
    user = create_user("U_PAT", email="pat@example.com")
    token = issue_account_token(user, AccountToken.PASSWORD_RESET)
    User.objects.filter(pk=user.pk).update(active=False)

    assert _confirm(token).status_code == 400


@pytest.mark.django_db
def test_confirm_rejects_a_weak_password_and_keeps_the_token_usable():
    user = create_user("U_PAT", email="pat@example.com")
    token = issue_account_token(user, AccountToken.PASSWORD_RESET)

    weak = _confirm(token, password="123")

    assert weak.status_code == 400
    assert "error" in weak.json()
    assert weak.json()["error"] != "Invalid or expired reset link"
    assert _confirm(token).status_code == 200


@pytest.mark.django_db
def test_admin_password_change_invalidates_outstanding_reset_links():
    from apps.auth.admin_services import update_admin_user
    from tests.factories import create_staff_user

    actor = create_staff_user("U_ADMIN", full_access=True)
    user = create_user("U_PAT", email="pat@example.com")
    token = issue_account_token(user, AccountToken.PASSWORD_RESET)

    result = update_admin_user(user.pk, {"password": "Staff-Set-Pass-2026!"}, actor)

    assert result.get("ok") is True
    assert _confirm(token).status_code == 400


@pytest.mark.django_db
def test_confirm_is_rate_limited_by_ip(monkeypatch):
    monkeypatch.setattr(PasswordResetConfirmRateThrottle, "rate", "2/min", raising=False)
    client = APIClient()

    for _ in range(2):
        client.post("/api/password-reset/confirm/", {"token": "x", "password": "y"}, format="json")
    blocked = client.post(
        "/api/password-reset/confirm/", {"token": "x", "password": "y"}, format="json"
    )

    assert blocked.status_code == 429
