"""Verificar el correo vincula con la cuenta el historial de compras como
invitado; sin verificar se puede comprar, pero el historial no se toca."""
import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import AccountToken, User
from apps.authentication.services import issue_account_token, issue_activation_token
from apps.authentication.utils.background import run_in_background as real_run_in_background
from apps.authentication.utils.throttling import (
    VerifyEmailRateThrottle,
    VerifyEmailResendRateThrottle,
)
from apps.checkout.models import Order
from apps.common.emails import email_logo_url
from apps.customers.models import Customer
from apps.quotes.models import Quote
from tests.factories import create_customer, create_user, session_client
from tests.fakes import SlowResend, forbid_resend, install_resend

STRONG_PASSWORD = "Diesel-Torque-2026!"
INVALID = {"error": "Invalid or expired verification link"}


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
        "apps.authentication.services.tokens.run_in_background",
        lambda func, *args, **kwargs: func(*args, **kwargs),
    )


@pytest.fixture
def slow_resend(settings, monkeypatch):
    settings.APP_URL = "https://shop.example.com"
    monkeypatch.setattr(
        "apps.authentication.services.tokens.run_in_background", real_run_in_background
    )
    fake = install_resend(monkeypatch, SlowResend())
    yield fake
    fake.release.set()
    fake.delivered.wait(5)


@pytest.fixture
def resend(settings, monkeypatch):
    settings.APP_URL = "https://shop.example.com"
    return install_resend(monkeypatch).sent


def _token_from(email_payload) -> str:
    html = email_payload["html"]
    marker = "/verify-email?token="
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


def _verify(token):
    return APIClient().post("/api/verify-email/", {"token": token}, format="json")


def _insert_order(order_id, customer, number):
    return Order.objects.create(
        id=order_id, number=number, customer=customer, data={"totals": {"total": 10.0}}
    )


def _insert_quote(quote_id, customer, number):
    return Quote.objects.create(
        id=quote_id,
        number=number,
        status="ACTIVE",
        customer=customer,
        data={},
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )


def _account_with_profile(email="pat@example.com"):
    user = create_user("U_PAT", email=email)
    customer = create_customer("C_PAT", email=email, user=user, data={"name": "Pat"})
    return user, customer


# --- registro ------------------------------------------------------------------


@pytest.mark.django_db
def test_register_sends_a_verification_email_and_reports_unverified(resend):
    response = APIClient().post(
        "/api/register/",
        {"email": "Pat@Example.com", "password": STRONG_PASSWORD, "name": "Pat Fleet"},
        format="json",
    )

    assert response.status_code == 201
    assert User.objects.get(email="pat@example.com").email_verified_at is None
    assert len(resend) == 1
    assert resend[0]["to"] == ["pat@example.com"]
    assert resend[0]["subject"] == "Verify your TorqueTrack email"
    assert f'<img src="{email_logo_url()}"' in resend[0]["html"]
    token = _token_from(resend[0])
    stored = AccountToken.objects.get(purpose=AccountToken.EMAIL_VERIFICATION)
    assert token not in stored.token_hash
    assert stored.expires_at > timezone.now() + timezone.timedelta(hours=47)


@pytest.mark.django_db
def test_register_with_an_existing_email_tells_the_owner_instead_of_verifying(resend):
    create_user("U_OWNER", email="pat@example.com")

    response = APIClient().post(
        "/api/register/",
        {"email": "Pat@Example.com", "password": STRONG_PASSWORD, "name": "Someone Else"},
        format="json",
    )

    assert response.status_code == 201
    assert len(resend) == 1
    assert resend[0]["to"] == ["pat@example.com"]
    assert resend[0]["subject"] == "You already have a TorqueTrack account"
    assert "https://shop.example.com/login" in resend[0]["html"]
    assert "https://shop.example.com/forgot-password" in resend[0]["html"]
    # No se emite ningún enlace: un tercero no puede anular los pendientes del dueño.
    assert not AccountToken.objects.exists()
    assert "Someone Else" not in resend[0]["html"]
    assert f'<img src="{email_logo_url()}"' in resend[0]["html"]


@pytest.mark.django_db
def test_register_with_the_email_of_an_inactive_account_sends_nothing(monkeypatch):
    create_user("U_OFF", email="off@example.com", active=False)
    forbid_resend(monkeypatch)

    response = APIClient().post(
        "/api/register/",
        {"email": "off@example.com", "password": STRONG_PASSWORD, "name": "Off"},
        format="json",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_register_succeeds_without_an_email_provider(settings):
    settings.RESEND_API_KEY = ""
    settings.FROM_EMAIL = ""

    response = APIClient().post(
        "/api/register/",
        {"email": "pat@example.com", "password": STRONG_PASSWORD, "name": "Pat Fleet"},
        format="json",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_session_reports_email_verified_true_after_verification():
    user, _ = _account_with_profile()
    User.objects.filter(pk=user.pk).update(email_verified_at=timezone.now())
    client, _ = session_client("U_PAT")

    assert client.get("/api/session/").json()["user"]["emailVerified"] is True


# --- verify --------------------------------------------------------------------


@pytest.mark.django_db
def test_verify_marks_the_email_verified_and_consumes_the_token():
    user, _ = _account_with_profile()
    token = issue_account_token(user, AccountToken.EMAIL_VERIFICATION)

    response = _verify(token)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "linkedOrders": 0, "linkedQuotes": 0}
    user.refresh_from_db()
    assert user.email_verified_at is not None
    assert _verify(token).status_code == 400


@pytest.mark.django_db
def test_verify_links_guest_orders_and_quotes_with_the_same_email():
    user, own = _account_with_profile()
    guest = create_customer("C_GUEST", email="PAT@example.com", data={"name": "Guest"})
    other = create_customer("C_OTHER", email="someone@example.com")
    _insert_order("ord_guest", guest, "O10001")
    _insert_quote("quo_guest", guest, "Q20001")
    _insert_order("ord_other", other, "O10002")
    _insert_order("ord_own", own, "O10003")
    token = issue_account_token(user, AccountToken.EMAIL_VERIFICATION)

    response = _verify(token)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "linkedOrders": 1, "linkedQuotes": 1}
    assert Order.objects.get(pk="ord_guest").customer_id == own.pk
    assert Quote.objects.get(pk="quo_guest").customer_id == own.pk
    assert Order.objects.get(pk="ord_other").customer_id == other.pk
    assert Order.objects.get(pk="ord_own").customer_id == own.pk
    assert not Customer.objects.filter(pk="C_GUEST").exists()
    assert Customer.objects.filter(pk="C_OTHER").exists()

    client, _ = session_client("U_PAT")
    numbers = {order["number"] for order in client.get("/api/account/orders/").json()}
    assert numbers == {"O10001", "O10003"}


@pytest.mark.django_db
def test_verify_does_not_touch_another_accounts_profile_with_the_same_email():
    user, own = _account_with_profile()
    other_user = create_user("U_OTHER", email="other@example.com")
    registered = create_customer("C_REG", email="pat@example.com", user=other_user)
    _insert_order("ord_reg", registered, "O10001")
    token = issue_account_token(user, AccountToken.EMAIL_VERIFICATION)

    assert _verify(token).json()["linkedOrders"] == 0

    assert Order.objects.get(pk="ord_reg").customer_id == registered.pk


@pytest.mark.django_db
def test_verify_adopts_the_guest_profile_when_the_account_has_none():
    user = create_user("U_STAFFLESS", email="solo@example.com")
    guest = create_customer("C_GUEST", email="solo@example.com")
    _insert_order("ord_guest", guest, "O10001")
    token = issue_account_token(user, AccountToken.EMAIL_VERIFICATION)

    response = _verify(token)

    assert response.json() == {"ok": True, "linkedOrders": 1, "linkedQuotes": 0}
    guest.refresh_from_db()
    assert guest.user_id == user.pk
    assert Order.objects.get(pk="ord_guest").customer_id == guest.pk


@pytest.mark.django_db
def test_unverified_account_does_not_see_guest_history():
    _account_with_profile()
    guest = create_customer("C_GUEST", email="pat@example.com")
    _insert_order("ord_guest", guest, "O10001")
    client, _ = session_client("U_PAT")

    assert client.get("/api/account/orders/").json() == []


@pytest.mark.parametrize("token", ["", "nope", None, 5])
@pytest.mark.django_db
def test_verify_rejects_missing_or_unknown_token(token):
    response = _verify(token)

    assert response.status_code == 400
    assert response.json() == INVALID


@pytest.mark.django_db
def test_verify_rejects_an_expired_token():
    user, _ = _account_with_profile()
    token = issue_account_token(user, AccountToken.EMAIL_VERIFICATION)
    AccountToken.objects.update(expires_at=timezone.now() - timezone.timedelta(minutes=1))

    assert _verify(token).json() == INVALID


@pytest.mark.django_db
def test_verify_rejects_a_password_reset_token():
    user, _ = _account_with_profile()
    token = issue_account_token(user, AccountToken.PASSWORD_RESET)

    assert _verify(token).status_code == 400


@pytest.mark.django_db
def test_verify_rejects_a_token_issued_for_a_previous_email():
    user, _ = _account_with_profile()
    token = issue_account_token(user, AccountToken.EMAIL_VERIFICATION)
    User.objects.filter(pk=user.pk).update(email="changed@example.com")

    assert _verify(token).status_code == 400
    user.refresh_from_db()
    assert user.email_verified_at is None


@pytest.mark.django_db
def test_verify_is_rate_limited_by_ip(monkeypatch):
    monkeypatch.setattr(VerifyEmailRateThrottle, "rate", "2/min", raising=False)
    client = APIClient()

    for _ in range(2):
        client.post("/api/verify-email/", {"token": "x"}, format="json")

    assert client.post("/api/verify-email/", {"token": "x"}, format="json").status_code == 429


# --- resend --------------------------------------------------------------------


@pytest.mark.django_db
def test_resend_sends_a_new_link_to_the_session_user(resend):
    _account_with_profile()
    client, _ = session_client("U_PAT")

    response = client.post("/api/verify-email/resend/", {}, format="json")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "emailVerified": False}
    assert resend[0]["to"] == ["pat@example.com"]
    assert _verify(_token_from(resend[0])).status_code == 200


@pytest.mark.django_db
def test_resend_for_verified_account_sends_nothing(monkeypatch):
    user, _ = _account_with_profile()
    User.objects.filter(pk=user.pk).update(email_verified_at=timezone.now())

    forbid_resend(monkeypatch, "A verified account must not get another email")
    client, _ = session_client("U_PAT")

    response = client.post("/api/verify-email/resend/", {}, format="json")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "emailVerified": True}


@pytest.mark.django_db
def test_resend_requires_a_session():
    response = APIClient().post("/api/verify-email/resend/", {}, format="json")

    assert response.status_code == 401


@pytest.mark.django_db
def test_resend_requires_the_csrf_token():
    _account_with_profile()
    client, _ = session_client("U_PAT", enforce_csrf=True)

    response = client.post("/api/verify-email/resend/", {}, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_resend_is_rate_limited_per_user(monkeypatch, resend):
    monkeypatch.setattr(VerifyEmailResendRateThrottle, "rate", "2/hour", raising=False)
    _account_with_profile()
    client, _ = session_client("U_PAT")

    for _ in range(2):
        client.post("/api/verify-email/resend/", {}, format="json")

    assert client.post("/api/verify-email/resend/", {}, format="json").status_code == 429


# --- activación del portal ----------------------------------------------------


@pytest.mark.django_db
def test_portal_activation_counts_as_a_verified_email():
    create_customer("C_INVITED", email="invited@example.com", data={"name": "Invited Buyer"})
    token = issue_activation_token("invited@example.com")

    response = APIClient().post(
        "/api/activate/", {"token": token, "password": STRONG_PASSWORD}, format="json"
    )

    assert response.status_code == 201
    assert response.json()["user"]["emailVerified"] is True
    assert User.objects.get(email="invited@example.com").email_verified_at is not None


# --- el correo sale fuera del request ------------------------------------------


@pytest.mark.django_db
def test_register_sends_the_verification_email_outside_the_request(slow_resend):
    response = APIClient().post(
        "/api/register/",
        {"email": "new@example.com", "password": STRONG_PASSWORD, "name": "New Driver"},
        format="json",
    )

    assert response.status_code == 201
    assert slow_resend.sent == []
    slow_resend.release.set()
    assert slow_resend.delivered.wait(5)
    assert slow_resend.sent[0]["to"] == ["new@example.com"]
    assert slow_resend.sent[0]["subject"] == "Verify your TorqueTrack email"


@pytest.mark.django_db
def test_register_sends_the_existing_account_email_outside_the_request(slow_resend):
    create_user("U_OWNER", email="owner@example.com")

    response = APIClient().post(
        "/api/register/",
        {"email": "owner@example.com", "password": STRONG_PASSWORD, "name": "Owner"},
        format="json",
    )

    assert response.status_code == 201
    assert slow_resend.sent == []
    slow_resend.release.set()
    assert slow_resend.delivered.wait(5)
    assert slow_resend.sent[0]["subject"] == "You already have a TorqueTrack account"


@pytest.mark.django_db
def test_resend_sends_the_verification_email_outside_the_request(slow_resend):
    create_user("U_PAT", email="pat@example.com")
    client, _ = session_client("U_PAT")

    response = client.post("/api/verify-email/resend/")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "emailVerified": False}
    assert slow_resend.sent == []
    slow_resend.release.set()
    assert slow_resend.delivered.wait(5)
    assert slow_resend.sent[0]["to"] == ["pat@example.com"]


@pytest.mark.django_db
def test_resend_voids_the_previous_verification_link(resend):
    _account_with_profile()
    client, _ = session_client("U_PAT")
    client.post("/api/verify-email/resend/", {}, format="json")
    client.post("/api/verify-email/resend/", {}, format="json")
    first, second = _token_from(resend[0]), _token_from(resend[1])

    assert _verify(first).status_code == 400
    assert _verify(second).status_code == 200
